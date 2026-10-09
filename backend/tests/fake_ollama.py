"""A scriptable stand-in for the Ollama HTTP API (tests only).

It speaks the real wire format (NDJSON streaming) so the production client, timeouts and
cancellation are exercised over a real socket. Counters let tests prove that no model call
happened (cache, refusals, consent).
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


@dataclass
class Script:
    reply: str = "Root login is risky [kb:ssh-root-login#why-it-matters]."
    token_delay_s: float = 0.0
    installed: list[str] = field(
        default_factory=lambda: ["qwen2.5:7b-instruct", "nomic-embed-text:latest"]
    )
    vram: int = 0
    pull_steps: int = 5
    pull_delay_s: float = 0.0
    chat_calls: int = 0
    pull_calls: int = 0
    last_chat: dict[str, Any] = field(default_factory=dict)


class _Handler(BaseHTTPRequestHandler):
    script: Script

    def log_message(self, *_: Any) -> None:
        return

    def _json(self, payload: object, status: int = 200) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _stream(self, items: Iterator[dict[str, Any]]) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.end_headers()
        try:
            for item in items:
                self.wfile.write(json.dumps(item).encode() + b"\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            return

    def do_GET(self) -> None:  # justification: http.server naming
        s = self.script
        if self.path == "/api/version":
            self._json({"version": "0.0.0-fake"})
        elif self.path == "/api/tags":
            self._json({"models": [{"name": n} for n in s.installed]})
        elif self.path == "/api/ps":
            self._json({"models": [{"name": n, "size_vram": s.vram} for n in s.installed[:1]]})
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self) -> None:  # justification: http.server naming
        s = self.script
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))) or b"{}")
        if self.path == "/api/chat":
            s.chat_calls += 1
            s.last_chat = body

            def tokens() -> Iterator[dict[str, Any]]:
                words = s.reply.split(" ")
                for i, word in enumerate(words):
                    if s.token_delay_s:
                        time.sleep(s.token_delay_s)
                    yield {
                        "message": {"content": word + (" " if i < len(words) - 1 else "")},
                        "done": False,
                    }
                yield {"message": {"content": ""}, "done": True}

            self._stream(tokens())
        elif self.path == "/api/pull":
            s.pull_calls += 1

            def progress() -> Iterator[dict[str, Any]]:
                yield {"status": "pulling manifest"}
                for step in range(1, s.pull_steps + 1):
                    if s.pull_delay_s:
                        time.sleep(s.pull_delay_s)
                    yield {
                        "status": "pulling abc",
                        "total": 1000,
                        "completed": step * 1000 // s.pull_steps,
                    }
                yield {"status": "success"}

            self._stream(progress())
        elif self.path == "/api/embed":
            texts = body.get("input", [])
            self._json({"embeddings": [[float(len(t) % 7), 1.0] for t in texts]})
        else:
            self._json({"error": "not found"}, 404)


@contextmanager
def fake_ollama(script: Script | None = None) -> Iterator[tuple[str, Script]]:
    script = script or Script()
    handler = type("Handler", (_Handler,), {"script": script})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", script
    finally:
        server.shutdown()
        server.server_close()
