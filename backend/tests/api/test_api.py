"""Phase 4: local API security and behaviour."""

from __future__ import annotations

import io
import json
import logging
import os
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
import uvicorn
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from fake_ollama import Script, fake_ollama
from hardengarden.api.app import MAX_STORED_SCANS, ApiState, create_app
from hardengarden.api.security import (
    MAX_BODY_BYTES,
    TOKEN_BYTES,
    LoopbackOnlyError,
    configure_logging,
    new_token,
    require_loopback,
    validate_dev_origin,
)
from hardengarden.api.server import bind_socket, serve
from hardengarden.core.settings import Settings, save_settings
from hardengarden.rag.assistant import Assistant, ExplanationCache
from hardengarden.rag.generate import Generation
from hardengarden.rag.models import Hardware, Memory
from hardengarden.rag.service import KnowledgeService
from hgtest import FIXTURES

TOKEN = new_token()
AUTH = {"Authorization": f"Bearer {TOKEN}"}
SNAPSHOT = Path(__file__).parent / "openapi.snapshot.json"
RICH = Hardware(Memory(32 * 1024**3, 24 * 1024**3), cpu_cores=8, gpu=None)


def _state(tmp_path: Path, url: str = "http://127.0.0.1:9", **kwargs: Any) -> ApiState:
    save_settings(Settings(ollama_url=url, chat_model="qwen2.5:7b-instruct"), tmp_path / "data")

    def factory(settings: Settings) -> Assistant:
        knowledge = KnowledgeService(settings, base=tmp_path / "data")
        return Assistant(
            settings, knowledge, cache=ExplanationCache(tmp_path / "cache"), hardware=RICH
        )

    return ApiState(
        token=TOKEN,
        scan_root=FIXTURES / "misconfigured" / "root",
        data_base=tmp_path / "data",
        cache_base=tmp_path / "cache",
        assistant_factory=factory,
        **kwargs,
    )


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    with TestClient(create_app(_state(tmp_path)), base_url="http://127.0.0.1") as c:
        yield c


def _lines(response: Any) -> list[dict[str, Any]]:
    return [json.loads(line) for line in response.text.splitlines() if line.strip()]


# ------------------------------------------------------------------ authentication


def _concrete(path: str) -> str:
    return path.replace("{scan_id}", "00000000-0000-0000-0000-000000000000").replace(
        "{check_id}", "HG-SSH-001"
    )


def test_every_route_except_health_requires_the_token(client: TestClient) -> None:
    routes = [r for r in client.app.routes if isinstance(r, APIRoute)]  # type: ignore[attr-defined]
    assert len(routes) >= 12
    for route in routes:
        for method in route.methods or ():
            url = _concrete(route.path)
            unauthenticated = client.request(method, url)
            wrong = client.request(method, url, headers={"Authorization": "Bearer wrong-token"})
            if route.path == "/health":
                assert unauthenticated.status_code == 200
                continue
            assert unauthenticated.status_code == 401, (method, route.path)
            assert wrong.status_code == 401, (method, route.path)
            assert unauthenticated.headers["www-authenticate"] == "Bearer"


def test_basic_auth_scheme_is_rejected(client: TestClient) -> None:
    assert client.get("/checks", headers={"Authorization": f"Basic {TOKEN}"}).status_code == 401


def test_token_is_long_and_random() -> None:
    tokens = {new_token() for _ in range(50)}
    assert len(tokens) == 50
    assert all(len(t) >= TOKEN_BYTES * 4 // 3 for t in tokens)


# ------------------------------------------------------------------ network exposure


@pytest.mark.parametrize(
    "host", ["0.0.0.0", "::", "192.168.1.5", "localhost", ""]
)  # justification: proving these are refused
def test_non_loopback_bind_is_impossible(host: str) -> None:
    with pytest.raises(LoopbackOnlyError):
        require_loopback(host)
    with pytest.raises(LoopbackOnlyError):
        bind_socket(host)
    with pytest.raises(LoopbackOnlyError):
        serve(host=host)


def test_bound_socket_is_loopback_on_a_random_port() -> None:
    first, second = bind_socket(), bind_socket()
    try:
        assert first.getsockname()[0] == "127.0.0.1"
        assert first.getsockname()[1] != second.getsockname()[1]
    finally:
        first.close()
        second.close()


@pytest.mark.parametrize("host", ["evil.example", "192.168.1.5:8080", "127.0.0.1.nip.io"])
def test_non_loopback_host_header_is_rejected(client: TestClient, host: str) -> None:
    assert client.get("/health", headers={"Host": host}).status_code == 400


@pytest.mark.parametrize("origin", ["tauri://localhost", "http://tauri.localhost"])
def test_cors_allows_only_the_tauri_origin(client: TestClient, origin: str) -> None:
    preflight = client.options(
        "/checks",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )
    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == origin
    assert "access-control-allow-credentials" not in preflight.headers


@pytest.mark.parametrize("origin", ["https://evil.example", "http://localhost:3000", "null"])
def test_cors_rejects_other_origins(client: TestClient, origin: str) -> None:
    preflight = client.options(
        "/checks", headers={"Origin": origin, "Access-Control-Request-Method": "GET"}
    )
    assert preflight.status_code == 400
    assert "access-control-allow-origin" not in preflight.headers
    simple = client.get("/health", headers={"Origin": origin})
    assert "access-control-allow-origin" not in simple.headers


def test_dev_origin_must_be_loopback(tmp_path: Path) -> None:
    assert validate_dev_origin("http://localhost:1420/") == "http://localhost:1420"
    for bad in [
        "https://localhost:1420",
        "http://evil.example:1420",
        "http://localhost",
        "http://localhost:1/x",
    ]:
        with pytest.raises(LoopbackOnlyError):
            validate_dev_origin(bad)
    state = _state(tmp_path, dev_origins=("http://localhost:1420",))
    with TestClient(create_app(state), base_url="http://127.0.0.1") as c:
        ok = c.options(
            "/checks",
            headers={"Origin": "http://localhost:1420", "Access-Control-Request-Method": "GET"},
        )
        assert ok.headers["access-control-allow-origin"] == "http://localhost:1420"


# ------------------------------------------------------------------ limits


def test_oversize_request_is_413(client: TestClient) -> None:
    big = json.dumps({"question": "x" * (MAX_BODY_BYTES + 10)})
    response = client.post(
        "/chat", content=big, headers={**AUTH, "Content-Type": "application/json"}
    )
    assert response.status_code == 413


def test_oversize_streamed_request_is_413(client: TestClient) -> None:
    def chunks() -> Iterator[bytes]:
        for _ in range(10):
            yield b"x" * (MAX_BODY_BYTES // 4)

    response = client.post(
        "/chat", content=chunks(), headers={**AUTH, "Content-Type": "application/json"}
    )
    assert response.status_code == 413


def test_bad_content_length_is_413(client: TestClient) -> None:
    response = client.post("/chat", content=b"{}", headers={**AUTH, "Content-Length": "abc"})
    assert response.status_code in {400, 413}


def test_rate_limiting(client: TestClient) -> None:
    statuses = [client.post("/ai/pull", json={}, headers=AUTH).status_code for _ in range(5)]
    assert statuses[:3] == [422, 422, 422]
    assert statuses[3] == 429


def test_input_validation(client: TestClient) -> None:
    assert client.post("/chat", json={"question": ""}, headers=AUTH).status_code == 422
    assert client.post("/chat", json={"question": "q", "extra": 1}, headers=AUTH).status_code == 422
    assert (
        client.post(
            "/explain", json={"scan_id": "nope", "check_id": "HG-SSH-001"}, headers=AUTH
        ).status_code
        == 422
    )
    assert client.get("/results/not-a-uuid", headers=AUTH).status_code == 422


# ------------------------------------------------------------------ logging


def test_logs_are_redacted_and_never_contain_the_token(client: TestClient) -> None:
    stream = io.StringIO()
    logger = configure_logging(stream)
    logger.info("db password=hunter2 Authorization: Bearer abcdefghijklmnop")
    client.get("/checks", headers=AUTH)
    output = stream.getvalue()
    assert "hunter2" not in output
    assert "abcdefghijklmnop" not in output
    assert TOKEN not in output
    records = [json.loads(line) for line in output.splitlines()]
    assert records[-1]["path"] == "/checks"
    assert set(records[-1]) == {"ts", "level", "logger", "msg", "method", "path", "status", "ms"}
    logging.getLogger("hardengarden.api").handlers.clear()


# ------------------------------------------------------------------ schema


def test_openapi_schema_snapshot(client: TestClient) -> None:
    schema = json.dumps(client.app.openapi(), indent=2, sort_keys=True) + "\n"  # type: ignore[attr-defined]
    if os.environ.get("HG_UPDATE_SNAPSHOTS") == "1":
        SNAPSHOT.write_text(schema)
    assert SNAPSHOT.read_text() == schema, "API changed: review it, then HG_UPDATE_SNAPSHOTS=1"


def test_no_public_docs_or_schema(client: TestClient) -> None:
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path, headers=AUTH).status_code == 404


# ------------------------------------------------------------------ behaviour


def test_health_and_checks(client: TestClient) -> None:
    assert client.get("/health").json()["status"] == "ok"
    checks = client.get("/checks", headers=AUTH).json()
    assert [c["id"] for c in checks][:2] == ["HG-SSH-001", "HG-SSH-002"]


def test_scan_and_results(client: TestClient) -> None:
    scan = client.post("/scan", headers=AUTH).json()
    assert len(scan["report"]["results"]) == 12
    assert isinstance(scan["report"]["summary"]["score"], int)
    again = client.get(f"/results/{scan['id']}", headers=AUTH)
    assert again.json() == scan["report"]
    missing = client.get("/results/00000000-0000-0000-0000-000000000000", headers=AUTH)
    assert missing.status_code == 404


def test_scan_store_is_bounded(tmp_path: Path) -> None:
    state = _state(tmp_path, rate_limits=(("/", 1000),))
    with TestClient(create_app(state), base_url="http://127.0.0.1") as client:
        ids = [client.post("/scan", headers=AUTH).json()["id"] for _ in range(MAX_STORED_SCANS + 1)]
        assert client.get(f"/results/{ids[0]}", headers=AUTH).status_code == 404
        assert client.get(f"/results/{ids[-1]}", headers=AUTH).status_code == 200


def test_remediation_text(client: TestClient) -> None:
    script = client.get("/remediation/HG-KRN-001", headers=AUTH)
    assert script.status_code == 200
    assert script.headers["content-type"].startswith("text/plain")
    assert script.text.startswith("#!/usr/bin/env bash")
    assert client.get("/remediation/HG-NET-001", headers=AUTH).status_code == 404
    assert client.get("/remediation/HG-XXX-999", headers=AUTH).status_code == 404


def test_explain_streams_and_chat_refuses(tmp_path: Path) -> None:
    with (
        fake_ollama() as (url, script),
        TestClient(create_app(_state(tmp_path, url)), base_url="http://127.0.0.1") as c,
    ):
        scan_id = c.post("/scan", headers=AUTH).json()["id"]
        response = c.post(
            "/explain", json={"scan_id": scan_id, "check_id": "HG-SSH-001"}, headers=AUTH
        )
        assert response.headers["content-type"].startswith("application/x-ndjson")
        events = _lines(response)
        assert events[0]["type"] == "delta"
        assert events[-1]["type"] == "final"
        assert events[-1]["answer"]["outcome"] == "answered"
        assert events[-1]["answer"]["citations"] == ["ssh-root-login#why-it-matters"]
        refusal = _lines(c.post("/chat", json={"question": "How do I bake bread?"}, headers=AUTH))
        assert refusal == [
            {
                "type": "final",
                "answer": {
                    "outcome": "not_enough_information",
                    "text": refusal[0]["answer"]["text"],
                    "citations": [],
                    "model": None,
                    "cached": False,
                },
            }
        ]
        assert script.chat_calls == 1
        unknown = c.post(
            "/explain", json={"scan_id": scan_id, "check_id": "HG-XXX-001"}, headers=AUTH
        )
        assert unknown.status_code == 404


def test_explain_without_ollama_is_a_final_event(client: TestClient) -> None:
    scan_id = client.post("/scan", headers=AUTH).json()["id"]
    events = _lines(
        client.post("/explain", json={"scan_id": scan_id, "check_id": "HG-FS-001"}, headers=AUTH)
    )
    assert len(events) == 1
    assert events[0]["answer"]["outcome"] == "ollama_unavailable"


def test_ai_status_and_pull(tmp_path: Path) -> None:
    with (
        fake_ollama() as (url, script),
        TestClient(create_app(_state(tmp_path, url)), base_url="http://127.0.0.1") as c,
    ):
        assert c.get("/ai/status", headers=AUTH).json()["state"] == "ready"
        no_consent = c.post(
            "/ai/pull", json={"model": "qwen2.5:1.5b-instruct", "consent": False}, headers=AUTH
        )
        assert no_consent.status_code == 422
        assert script.pull_calls == 0
        unknown = c.post("/ai/pull", json={"model": "evil/model", "consent": True}, headers=AUTH)
        assert unknown.status_code == 400
        events = _lines(
            c.post(
                "/ai/pull",
                json={"model": "qwen2.5:1.5b-instruct", "consent": True},
                headers=AUTH,
            )
        )
        assert events[0]["status"] == "pulling manifest"
        assert events[-1] == {"type": "done", "cancelled": False}
        assert script.pull_calls == 1


def test_pull_when_ollama_is_down(client: TestClient) -> None:
    response = client.post(
        "/ai/pull", json={"model": "qwen2.5:1.5b-instruct", "consent": True}, headers=AUTH
    )
    assert response.status_code == 503


def test_settings_roundtrip_and_validation(client: TestClient, tmp_path: Path) -> None:
    assert client.get("/settings", headers=AUTH).json()["chat_model"] == "qwen2.5:7b-instruct"
    updated = client.put(
        "/settings", json={"max_tokens": 256, "clear_chat_model": True}, headers=AUTH
    )
    assert updated.status_code == 200
    assert updated.json()["max_tokens"] == 256
    assert updated.json()["chat_model"] is None
    remote = client.put("/settings", json={"ollama_url": "http://10.0.0.5:11434"}, headers=AUTH)
    assert remote.status_code == 422
    assert "must be one of" in remote.json()["detail"]
    unknown_model = client.put("/settings", json={"chat_model": "llama"}, headers=AUTH)
    assert unknown_model.status_code == 422
    assert client.get("/settings", headers=AUTH).json()["ollama_url"] == "http://127.0.0.1:9"


def test_kb_ingest_without_ollama(client: TestClient) -> None:
    result = client.post("/kb/ingest", headers=AUTH).json()
    assert result["chunks"] == 60
    assert "Keyword search still works" in result["note"]


# ------------------------------------------------------------------ real server


@pytest.fixture
def live_server(tmp_path: Path) -> Iterator[tuple[str, ApiState, Script]]:
    with fake_ollama(
        Script(
            reply=" ".join(["word"] * 200) + " [kb:ssh-root-login#what-it-is]", token_delay_s=0.1
        )
    ) as (url, script):
        state = _state(tmp_path, url)
        sock = bind_socket()
        server = uvicorn.Server(uvicorn.Config(create_app(state), log_config=None, lifespan="off"))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
        thread.start()
        while not server.started:
            time.sleep(0.05)
        yield f"http://127.0.0.1:{sock.getsockname()[1]}", state, script
        server.should_exit = True
        thread.join(timeout=10)


def test_client_disconnect_cancels_the_generation(
    live_server: tuple[str, ApiState, Script],
) -> None:
    base, state, _ = live_server
    generations: list[Generation] = []
    original = state.assistant_factory
    assert original is not None

    def tracking(settings: Settings) -> Assistant:
        assistant = original(settings)
        real_explain = assistant.explain

        def explain(*args: Any, **kwargs: Any) -> Any:
            result = real_explain(*args, **kwargs)
            if isinstance(result, Generation):
                generations.append(result)
            return result

        assistant.explain = explain  # type: ignore[method-assign]
        return assistant

    state.assistant_factory = tracking
    with httpx.Client(base_url=base, headers=AUTH) as http:
        scan_id = http.post("/scan").json()["id"]
        with http.stream(
            "POST",
            "/explain",
            json={"scan_id": scan_id, "check_id": "HG-SSH-001", "use_cache": False},
        ) as r:
            for _ in r.iter_lines():
                break  # read one event, then hang up like the UI's Stop button
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and not (generations and generations[0].answer):
        time.sleep(0.1)
    assert generations
    answer = generations[0].answer
    assert answer is not None
    assert answer.outcome.value == "cancelled"


def test_sidecar_handshake_and_stdin_shutdown(tmp_path: Path) -> None:
    env = {**os.environ, "XDG_DATA_HOME": str(tmp_path), "XDG_CACHE_HOME": str(tmp_path)}
    argv = [
        sys.executable,
        "-c",
        "from hardengarden.cli import app; app()",
        "serve",
        "--watch-stdin",
        "--root",
        str(FIXTURES / "hardened" / "root"),
    ]
    with subprocess.Popen(  # noqa: S603  # justification: starts our own server module with fixed arguments
        argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env
    ) as proc:
        try:
            assert proc.stdout is not None
            assert proc.stdin is not None
            assert proc.stderr is not None
            handshake = json.loads(proc.stdout.readline())
            assert handshake["event"] == "ready"
            assert len(handshake["token"]) >= 43
            base = f"http://127.0.0.1:{handshake['port']}"
            with httpx.Client(base_url=base) as http:
                assert http.get("/health").json()["status"] == "ok"
                auth = {"Authorization": f"Bearer {handshake['token']}"}
                report = http.post("/scan", headers=auth).json()
                assert report["report"]["scanned_root"].endswith("hardened/root")
            with socket.create_connection(("127.0.0.1", handshake["port"]), timeout=2):
                pass
            proc.stdin.close()  # the parent "died": the sidecar must exit on its own
            assert proc.wait(timeout=10) == 0
            assert handshake["token"] not in proc.stderr.read().decode()
        finally:
            if proc.poll() is None:
                proc.kill()


def test_serve_command_rejects_bad_dev_origin() -> None:
    result = subprocess.run(  # justification: our own CLI with fixed arguments
        [
            sys.executable,
            "-c",
            "from hardengarden.cli import app; app()",
            "serve",
            "--dev-origin",
            "https://evil.example",
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 2
    assert "dev origin" in result.stderr
