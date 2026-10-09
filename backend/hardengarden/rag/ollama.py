"""Minimal Ollama HTTP client (stdlib only). Loopback endpoints only (R7, ADR-002 #4)."""

from __future__ import annotations

import http.client
import json
import socket
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

DEFAULT_URL = "http://127.0.0.1:11434"
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
CONNECT_TIMEOUT_S = 5.0
MAX_RESPONSE_BYTES = 8 * 1024 * 1024


class OllamaError(Exception):
    """Ollama is unreachable or answered with an error."""


class OllamaUnavailableError(OllamaError):
    """Nothing is listening at the configured endpoint (not installed or not running)."""


class EndpointNotAllowedError(ValueError):
    """The configured URL is not a loopback HTTP endpoint."""


@dataclass(frozen=True, slots=True)
class Endpoint:
    host: str
    port: int

    @property
    def url(self) -> str:
        host = f"[{self.host}]" if ":" in self.host else self.host
        return f"http://{host}:{self.port}"


def parse_endpoint(url: str) -> Endpoint:
    """Accept only ``http://`` URLs whose host is 127.0.0.1, localhost or ::1."""
    parts = urlsplit(url.strip())
    if parts.scheme != "http":
        msg = "Ollama URL must use http:// on a loopback address"
        raise EndpointNotAllowedError(msg)
    host = (parts.hostname or "").lower()
    if host not in LOOPBACK_HOSTS:
        msg = f"Ollama URL host must be one of {sorted(LOOPBACK_HOSTS)}, got {host or 'nothing'!r}"
        raise EndpointNotAllowedError(msg)
    if parts.username or parts.password or parts.query or parts.fragment:
        msg = "Ollama URL must not contain credentials, a query or a fragment"
        raise EndpointNotAllowedError(msg)
    if parts.path not in {"", "/"}:
        msg = "Ollama URL must not contain a path"
        raise EndpointNotAllowedError(msg)
    try:
        port = parts.port or 11434
    except ValueError as exc:
        msg = "Ollama URL has an invalid port"
        raise EndpointNotAllowedError(msg) from exc
    return Endpoint(host, port)


class OllamaClient:
    def __init__(self, url: str = DEFAULT_URL, *, timeout_s: float = 120.0) -> None:
        self.endpoint = parse_endpoint(url)
        self.timeout_s = timeout_s

    def _connection(self, timeout: float) -> http.client.HTTPConnection:
        return http.client.HTTPConnection(self.endpoint.host, self.endpoint.port, timeout=timeout)

    def _open(
        self, method: str, path: str, body: dict[str, Any] | None, timeout: float
    ) -> tuple[http.client.HTTPConnection, http.client.HTTPResponse]:
        conn = self._connection(timeout)
        payload = json.dumps(body).encode() if body is not None else None
        headers = {"Content-Type": "application/json"} if payload else {}
        try:
            conn.request(method, path, body=payload, headers=headers)
        except (OSError, socket.gaierror) as exc:  # refused, unreachable, connect timeout
            conn.close()
            msg = f"Ollama is not reachable at {self.endpoint.url}. Is it installed and running?"
            raise OllamaUnavailableError(msg) from exc
        try:
            response = conn.getresponse()
        except (OSError, http.client.HTTPException) as exc:
            conn.close()
            msg = f"Ollama request failed: {type(exc).__name__}"
            raise OllamaError(msg) from exc
        if response.status >= 400:  # noqa: PLR2004  # justification: HTTP error class boundary
            detail = response.read(4096).decode("utf-8", "replace")
            conn.close()
            msg = f"Ollama returned HTTP {response.status}: {detail[:200]}"
            raise OllamaError(msg)
        return conn, response

    def request_json(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        *,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        conn, response = self._open(method, path, body, timeout or self.timeout_s)
        try:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
        finally:
            conn.close()
        if len(raw) > MAX_RESPONSE_BYTES:
            msg = "Ollama response too large"
            raise OllamaError(msg)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            msg = "Ollama returned invalid JSON"
            raise OllamaError(msg) from exc
        if not isinstance(data, dict):
            msg = "Ollama returned an unexpected payload"
            raise OllamaError(msg)
        return data

    def stream_json(
        self, path: str, body: dict[str, Any], *, timeout: float | None = None
    ) -> Iterator[dict[str, Any]]:
        """Yield one JSON object per NDJSON line. Closing the generator closes the socket."""
        conn, response = self._open("POST", path, body, timeout or self.timeout_s)
        try:
            while True:
                line = response.readline(MAX_RESPONSE_BYTES)
                if not line:
                    return
                if not line.strip():
                    continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError as exc:
                    msg = "Ollama stream contained invalid JSON"
                    raise OllamaError(msg) from exc
                if isinstance(item, dict):
                    if "error" in item:
                        msg = f"Ollama error: {str(item['error'])[:200]}"
                        raise OllamaError(msg)
                    yield item
        except TimeoutError as exc:
            msg = "Ollama did not respond in time"
            raise OllamaError(msg) from exc
        finally:
            conn.close()

    # ------------------------------------------------------------------ endpoints
    def version(self) -> str:
        return str(
            self.request_json("GET", "/api/version", timeout=CONNECT_TIMEOUT_S).get("version", "")
        )

    def installed_models(self) -> list[str]:
        data = self.request_json("GET", "/api/tags", timeout=CONNECT_TIMEOUT_S)
        models = data.get("models", [])
        return sorted(str(m.get("name", "")) for m in models if isinstance(m, dict))

    def embed(self, model: str, texts: list[str]) -> list[list[float]]:
        data = self.request_json("POST", "/api/embed", {"model": model, "input": texts})
        vectors = data.get("embeddings")
        if not isinstance(vectors, list) or len(vectors) != len(texts):
            msg = "Ollama returned an unexpected embedding payload"
            raise OllamaError(msg)
        return [[float(x) for x in v] for v in vectors]


class OllamaEmbedder:
    """Embedding model adapter used by ingestion and retrieval.

    nomic-embed-text is trained with task prefixes; documents and queries get different ones.
    """

    DOCUMENT_PREFIX = "search_document: "
    QUERY_PREFIX = "search_query: "
    BATCH = 32

    def __init__(self, client: OllamaClient, model: str = "nomic-embed-text") -> None:
        self.client = client
        self.model = model

    @property
    def name(self) -> str:
        return self.model

    def _embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.BATCH):
            vectors.extend(self.client.embed(self.model, texts[start : start + self.BATCH]))
        return vectors

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._embed([self.DOCUMENT_PREFIX + t for t in texts])

    def embed_query(self, text: str) -> list[float]:
        return self._embed([self.QUERY_PREFIX + text])[0]
