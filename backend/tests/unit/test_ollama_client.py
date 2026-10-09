"""Ollama client: loopback-only endpoints, error mapping, streaming, against a local fake."""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, ClassVar

import pytest

from hardengarden.rag.ollama import (
    EndpointNotAllowedError,
    OllamaClient,
    OllamaEmbedder,
    OllamaError,
    OllamaUnavailableError,
    parse_endpoint,
)


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("http://127.0.0.1:11434", "http://127.0.0.1:11434"),
        ("http://localhost:8080/", "http://localhost:8080"),
        ("http://[::1]:11434", "http://[::1]:11434"),
        ("http://LOCALHOST", "http://localhost:11434"),
    ],
)
def test_loopback_urls_are_accepted(url: str, expected: str) -> None:
    assert parse_endpoint(url).url == expected


@pytest.mark.parametrize(
    "url",
    [
        "http://192.168.1.10:11434",
        "http://10.0.0.1",
        "http://ollama.example.com",
        "https://127.0.0.1:11434",
        "ftp://127.0.0.1",
        "http://user:pw@127.0.0.1",
        "http://127.0.0.1/api",
        "http://127.0.0.1:11434?x=1",
        "http://127.0.0.2:11434",
        "http://0.0.0.0:11434",
        "http://127.0.0.1:99999",
        "",
    ],
)
def test_non_loopback_urls_are_rejected(url: str) -> None:
    with pytest.raises(EndpointNotAllowedError):
        parse_endpoint(url)


class _Fake(BaseHTTPRequestHandler):
    routes: ClassVar[dict[str, tuple[int, bytes]]] = {}
    bodies: ClassVar[list[dict[str, Any]]] = []

    def log_message(self, *_: Any) -> None:
        return

    def _reply(self) -> None:
        status, body = self.routes.get(self.path, (404, b'{"error":"not found"}'))
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # justification: http.server naming
        self._reply()

    def do_POST(self) -> None:  # justification: http.server naming
        length = int(self.headers.get("Content-Length", "0"))
        self.bodies.append(json.loads(self.rfile.read(length) or b"{}"))
        self._reply()


@pytest.fixture
def server() -> Iterator[str]:
    _Fake.routes = {}
    _Fake.bodies = []
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Fake)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()


def test_version_tags_and_embed(server: str) -> None:
    _Fake.routes = {
        "/api/version": (200, b'{"version":"0.12.0"}'),
        "/api/tags": (
            200,
            b'{"models":[{"name":"qwen2.5:7b-instruct"},{"name":"nomic-embed-text:latest"}]}',
        ),
        "/api/embed": (200, b'{"embeddings":[[0.1,0.2],[0.3,0.4]]}'),
    }
    client = OllamaClient(server)
    assert client.version() == "0.12.0"
    assert client.installed_models() == ["nomic-embed-text:latest", "qwen2.5:7b-instruct"]
    embedder = OllamaEmbedder(client)
    assert embedder.embed_documents(["a", "b"]) == [[0.1, 0.2], [0.3, 0.4]]
    assert _Fake.bodies[-1] == {
        "model": "nomic-embed-text",
        "input": ["search_document: a", "search_document: b"],
    }


def test_embed_rejects_wrong_shape(server: str) -> None:
    _Fake.routes = {"/api/embed": (200, b'{"embeddings":[[1.0]]}')}
    with pytest.raises(OllamaError, match="unexpected embedding"):
        OllamaClient(server).embed("m", ["a", "b"])


def test_http_errors_and_bad_json(server: str) -> None:
    _Fake.routes = {"/api/version": (500, b"boom"), "/api/tags": (200, b"not json")}
    client = OllamaClient(server)
    with pytest.raises(OllamaError, match="HTTP 500"):
        client.version()
    with pytest.raises(OllamaError, match="invalid JSON"):
        client.installed_models()
    _Fake.routes = {"/api/tags": (200, b"[1, 2]")}
    with pytest.raises(OllamaError, match="unexpected payload"):
        client.installed_models()


def test_streaming(server: str) -> None:
    lines = b'{"message":{"content":"Hel"}}\n\n{"message":{"content":"lo"},"done":true}\n'
    _Fake.routes = {"/api/chat": (200, lines), "/api/pull": (200, b'{"error":"model not found"}\n'),
                    "/api/bad": (200, b"{oops\n")}  # fmt: skip
    client = OllamaClient(server)
    parts = list(client.stream_json("/api/chat", {"model": "m"}))
    assert [p["message"]["content"] for p in parts] == ["Hel", "lo"]
    with pytest.raises(OllamaError, match="model not found"):
        list(client.stream_json("/api/pull", {"model": "m"}))
    with pytest.raises(OllamaError, match="invalid JSON"):
        list(client.stream_json("/api/bad", {}))


def test_unreachable_is_unavailable() -> None:
    with pytest.raises(OllamaUnavailableError):
        OllamaClient("http://127.0.0.1:9").version()


def test_client_rejects_remote_url() -> None:
    with pytest.raises(EndpointNotAllowedError):
        OllamaClient("http://203.0.113.5:11434")
