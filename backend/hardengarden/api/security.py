"""API hardening (R8, R9): bearer token, loopback-only hosts and origins, body size limit,
rate limiting and redacted structured logging. Pure ASGI middleware, so limits also apply
to streamed request bodies and nothing depends on framework internals.
"""

from __future__ import annotations

import json
import logging
import secrets
import threading
import time
from collections.abc import Awaitable, Callable, MutableMapping
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

from hardengarden.core.redaction import redact

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
TAURI_ORIGINS = ("tauri://localhost", "http://tauri.localhost", "https://tauri.localhost")
MAX_BODY_BYTES = 64 * 1024
TOKEN_BYTES = 32


def new_token() -> str:
    """At least 32 random bytes from ``secrets`` (R8), URL-safe encoded."""
    return secrets.token_urlsafe(TOKEN_BYTES)


def tokens_match(presented: str, expected: str) -> bool:
    return secrets.compare_digest(presented.encode(), expected.encode())


class LoopbackOnlyError(ValueError):
    pass


def require_loopback(host: str) -> str:
    """The API may only ever bind to 127.0.0.1 (R8). Anything else is a configuration error."""
    if host != "127.0.0.1":
        msg = f"the API binds to 127.0.0.1 only; refusing {host!r}"
        raise LoopbackOnlyError(msg)
    return host


def validate_dev_origin(origin: str) -> str:
    """Development UIs (Vite) are allowed only as http://localhost:PORT or 127.0.0.1."""
    parts = urlsplit(origin)
    if parts.scheme != "http" or parts.hostname not in {"localhost", "127.0.0.1"} or not parts.port:
        msg = f"dev origin must be http://localhost:PORT or http://127.0.0.1:PORT, got {origin!r}"
        raise LoopbackOnlyError(msg)
    if parts.path not in {"", "/"} or parts.query or parts.fragment or parts.username:
        msg = f"dev origin must not contain a path, query or credentials: {origin!r}"
        raise LoopbackOnlyError(msg)
    return f"http://{parts.hostname}:{parts.port}"


def _header(scope: Scope, name: bytes) -> str | None:
    for key, value in scope.get("headers", []):
        if key.lower() == name:
            return bytes(value).decode("latin-1")
    return None


async def _reply(
    send: Send, status: int, body: dict[str, Any], headers: list[tuple[bytes, bytes]] | None = None
) -> None:
    payload = json.dumps(body).encode()
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(payload)).encode()),
                *(headers or []),
            ],
        }
    )
    await send({"type": "http.response.body", "body": payload})


class HostCheckMiddleware:
    """Rejects requests whose Host header is not loopback (defeats DNS rebinding)."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            host = _header(scope, b"host") or ""
            hostname = urlsplit(f"//{host}").hostname or ""
            if hostname not in LOOPBACK_HOSTS:
                await _reply(send, 400, {"detail": "invalid host"})
                return
        await self.app(scope, receive, send)


class BodyLimitMiddleware:
    """413 for bodies over the limit, declared (Content-Length) or streamed (chunked).

    The API never needs streamed request bodies, so the body is read and size-checked here,
    before the framework sees it (the framework would turn a mid-parse error into a 400).
    """

    def __init__(self, app: ASGIApp, limit: int = MAX_BODY_BYTES) -> None:
        self.app = app
        self.limit = limit

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        declared = _header(scope, b"content-length")
        if declared is not None and (not declared.isdigit() or int(declared) > self.limit):
            await _reply(send, 413, {"detail": "request body too large"})
            return
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body.extend(message.get("body", b""))
            if len(body) > self.limit:
                await _reply(send, 413, {"detail": "request body too large"})
                return
            if not message.get("more_body", False):
                break
        replayed = False

        async def replay() -> Message:
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.app(scope, replay, send)


@dataclass
class _Bucket:
    capacity: int
    per_seconds: float
    tokens: float = -1.0
    updated: float = field(default_factory=time.monotonic)

    def take(self) -> bool:
        now = time.monotonic()
        if self.tokens < 0:
            self.tokens = float(self.capacity)
        self.tokens = min(
            self.capacity, self.tokens + (now - self.updated) * self.capacity / self.per_seconds
        )
        self.updated = now
        if self.tokens >= 1:
            self.tokens -= 1
            return True
        return False


# (path prefix, requests per minute). The first matching prefix applies.
RATE_LIMITS: tuple[tuple[str, int], ...] = (
    ("/ai/pull", 3),
    ("/scan", 10),
    ("/explain", 30),
    ("/chat", 30),
    ("/kb/ingest", 5),
    ("/", 300),
)


class RateLimitMiddleware:
    """Per-route token buckets. One local client, so buckets are global, not per IP."""

    def __init__(self, app: ASGIApp, limits: tuple[tuple[str, int], ...] = RATE_LIMITS) -> None:
        self.app = app
        self.limits = limits
        self._buckets = {prefix: _Bucket(per_minute, 60.0) for prefix, per_minute in limits}
        self._lock = threading.Lock()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope.get("method") != "OPTIONS":
            path = scope.get("path", "")
            prefix = next(p for p, _ in self.limits if path.startswith(p))
            with self._lock:
                allowed = self._buckets[prefix].take()
            if not allowed:
                await _reply(send, 429, {"detail": "too many requests"}, [(b"retry-after", b"10")])
                return
        await self.app(scope, receive, send)


class RedactingJsonFormatter(logging.Formatter):
    """One JSON object per line; message and arguments pass through ``redact`` (R9)."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": round(record.created, 3),
            "level": record.levelname,
            "logger": record.name,
            "msg": redact(record.getMessage()),
        }
        extra = getattr(record, "fields", None)
        if isinstance(extra, dict):
            payload.update({k: redact(str(v)) for k, v in extra.items()})
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(stream: Any = None, level: int = logging.INFO) -> logging.Logger:  # noqa: ANN401  # justification: any text stream (stderr in production, StringIO in tests)
    logger = logging.getLogger("hardengarden.api")
    logger.handlers.clear()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(RedactingJsonFormatter())
    logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False
    return logger


class AccessLogMiddleware:
    """Logs method, path template-free path, status and duration. Never headers or bodies."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self.log = logging.getLogger("hardengarden.api")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = time.perf_counter()
        status = 0

        async def capture(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = int(message["status"])
            await send(message)

        try:
            await self.app(scope, receive, capture)
        finally:
            self.log.info(
                "request",
                extra={
                    "fields": {
                        "method": scope.get("method"),
                        "path": scope.get("path"),
                        "status": status,
                        "ms": round((time.perf_counter() - started) * 1000, 1),
                    }
                },
            )
