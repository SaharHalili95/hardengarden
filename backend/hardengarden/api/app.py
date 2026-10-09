"""Local HTTP API used by the desktop app (Phase 4).

No ``from __future__ import annotations`` here: FastAPI resolves dependency annotations
at runtime, and postponed annotations would turn the closure-scoped auth dependency into
a query parameter (found by the Phase 4 smoke test).

Every route except ``GET /health`` requires the per-launch bearer token. No route reads an
arbitrary path or runs a command chosen by the client (R8): the scan root is fixed when the
server starts, checks are fixed in code, and remediation scripts are returned as text.
"""

import asyncio
import json
import threading
import uuid
from collections import OrderedDict
from collections.abc import AsyncIterator, Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from hardengarden import __version__
from hardengarden.checks import ALL_CHECKS
from hardengarden.core.check import Check
from hardengarden.core.engine import run_scan
from hardengarden.core.models import CHECK_ID_PATTERN, CheckMeta, ScanReport
from hardengarden.core.paths import cache_dir, data_dir
from hardengarden.core.settings import Settings, load_settings, save_settings
from hardengarden.core.systemview import SystemView
from hardengarden.rag.assistant import Assistant, ExplanationCache, start_pull
from hardengarden.rag.generate import Answer, Generation
from hardengarden.rag.ollama import OllamaClient, OllamaError
from hardengarden.rag.service import KnowledgeService
from hardengarden.remediation import render

from .security import (
    RATE_LIMITS,
    TAURI_ORIGINS,
    AccessLogMiddleware,
    BodyLimitMiddleware,
    HostCheckMiddleware,
    RateLimitMiddleware,
    tokens_match,
)

MAX_STORED_SCANS = 20
CheckId = Annotated[str, Field(pattern=CHECK_ID_PATTERN.pattern)]


@dataclass
class ApiState:
    token: str
    scan_root: Path = Path("/")
    data_base: Path = field(default_factory=data_dir)
    cache_base: Path = field(default_factory=cache_dir)
    dev_origins: tuple[str, ...] = ()
    rate_limits: tuple[tuple[str, int], ...] = RATE_LIMITS
    assistant_factory: Callable[[Settings], Assistant] | None = None
    _scans: OrderedDict[str, ScanReport] = field(default_factory=OrderedDict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def settings(self) -> Settings:
        return load_settings(self.data_base)

    def assistant(self) -> Assistant:
        settings = self.settings()
        if self.assistant_factory is not None:
            return self.assistant_factory(settings)
        knowledge = KnowledgeService(settings, base=self.data_base)
        return Assistant(
            settings, knowledge, cache=ExplanationCache(self.cache_base / "explanations")
        )

    def remember(self, report: ScanReport) -> str:
        scan_id = str(uuid.uuid4())
        with self._lock:
            self._scans[scan_id] = report
            while len(self._scans) > MAX_STORED_SCANS:
                self._scans.popitem(last=False)
        return scan_id

    def recall(self, scan_id: str) -> ScanReport | None:
        with self._lock:
            return self._scans.get(scan_id)


# ------------------------------------------------------------------ request models


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ExplainRequest(_Strict):
    scan_id: uuid.UUID
    check_id: CheckId
    use_cache: bool = True


class ChatRequest(_Strict):
    question: Annotated[str, Field(min_length=1, max_length=500)]


class PullRequest(_Strict):
    model: Annotated[str, Field(min_length=1, max_length=100)]
    consent: Literal[True]  # R37: the UI must send an explicit consent flag


class SettingsUpdate(_Strict):
    ollama_url: str | None = None
    chat_model: str | None = None
    clear_chat_model: bool = False
    generation_timeout_s: Annotated[int, Field(ge=10, le=600)] | None = None
    max_tokens: Annotated[int, Field(ge=64, le=1024)] | None = None


class ScanResponse(BaseModel):
    id: str
    report: ScanReport


class HealthResponse(BaseModel):
    status: Literal["ok"]
    version: str


# ------------------------------------------------------------------ streaming


def _ndjson(event: dict[str, Any]) -> bytes:
    return json.dumps(event, ensure_ascii=False).encode() + b"\n"


async def _drain_in_thread(
    request: Request, source: Iterator[dict[str, Any]], cancel: Callable[[], None]
) -> AsyncIterator[bytes]:
    """Iterate a blocking iterator in a thread; cancel it if the client goes away."""
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()

    def worker() -> None:
        try:
            for item in source:
                loop.call_soon_threadsafe(queue.put_nowait, ("item", item))
        except Exception as exc:  # noqa: BLE001  # justification: errors must reach the client as an event, never crash the server
            loop.call_soon_threadsafe(queue.put_nowait, ("error", type(exc).__name__))
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, ("end", None))

    threading.Thread(target=worker, daemon=True).start()
    finished = False
    try:
        while True:
            try:
                kind, value = await asyncio.wait_for(queue.get(), timeout=0.5)
            except TimeoutError:
                if await request.is_disconnected():
                    return
                continue
            if kind == "end":
                finished = True
                return
            if kind == "error":
                yield _ndjson({"type": "error", "detail": f"failed ({value})"})
                continue
            yield _ndjson(value)
    finally:
        if not finished:
            cancel()


def _answer_stream(request: Request, result: Generation | Answer) -> StreamingResponse:
    if isinstance(result, Answer):

        async def immediate() -> AsyncIterator[bytes]:
            yield _ndjson({"type": "final", "answer": result.to_dict()})

        return StreamingResponse(immediate(), media_type="application/x-ndjson")

    def events() -> Iterator[dict[str, Any]]:
        for delta in result:
            yield {"type": "delta", "text": delta}
        answer = result.answer
        if answer is not None:
            yield {"type": "final", "answer": answer.to_dict()}

    return StreamingResponse(
        _drain_in_thread(request, events(), result.cancel), media_type="application/x-ndjson"
    )


# ------------------------------------------------------------------ app


def create_app(state: ApiState) -> FastAPI:
    app = FastAPI(
        title="HardenGarden local API",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,  # nothing to browse: the API is private to the desktop app
    )
    bearer = HTTPBearer(auto_error=False)

    def authorized(
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    ) -> None:
        if credentials is None or not tokens_match(credentials.credentials, state.token):
            raise HTTPException(
                status_code=401, detail="unauthorized", headers={"WWW-Authenticate": "Bearer"}
            )

    auth = [Depends(authorized)]
    _scan_routes(app, state, auth)
    _ai_routes(app, state, auth)
    _settings_routes(app, state, auth)
    _add_middleware(app, state)
    return app


Auth = list[Any]
_CHECKS_BY_ID: dict[str, Check] = {c.meta.id: c for c in ALL_CHECKS}


def _scan_routes(app: FastAPI, state: ApiState, auth: Auth) -> None:
    checks_by_id = _CHECKS_BY_ID

    @app.get("/health")
    def health() -> HealthResponse:
        return HealthResponse(status="ok", version=__version__)

    @app.get("/checks", dependencies=auth)
    def list_checks() -> list[CheckMeta]:
        return [c.meta for c in ALL_CHECKS]

    @app.post("/scan", dependencies=auth)
    def scan() -> ScanResponse:
        report = run_scan(SystemView(state.scan_root), ALL_CHECKS)
        return ScanResponse(id=state.remember(report), report=report)

    @app.get("/results/{scan_id}", dependencies=auth)
    def results(scan_id: uuid.UUID) -> ScanReport:
        report = state.recall(str(scan_id))
        if report is None:
            raise HTTPException(status_code=404, detail="unknown scan id")
        return report

    @app.get("/remediation/{check_id}", dependencies=auth, response_class=PlainTextResponse)
    def remediation(check_id: str) -> str:
        check = checks_by_id.get(check_id)
        if check is None:
            raise HTTPException(status_code=404, detail="unknown check")
        script = render(check.meta)
        if script is None:
            raise HTTPException(status_code=404, detail="this check has guidance only")
        return script


def _ai_routes(app: FastAPI, state: ApiState, auth: Auth) -> None:
    checks_by_id = _CHECKS_BY_ID

    @app.post("/explain", dependencies=auth)
    def explain(body: ExplainRequest, request: Request) -> StreamingResponse:
        report = state.recall(str(body.scan_id))
        check = checks_by_id.get(body.check_id)
        if report is None or check is None:
            raise HTTPException(status_code=404, detail="unknown scan or check")
        result = next(r for r in report.results if r.check_id == body.check_id)
        return _answer_stream(
            request, state.assistant().explain(check, result, use_cache=body.use_cache)
        )

    @app.post("/chat", dependencies=auth)
    def chat(body: ChatRequest, request: Request) -> StreamingResponse:
        return _answer_stream(request, state.assistant().chat(body.question))

    @app.get("/ai/status", dependencies=auth)
    def ai_status() -> dict[str, Any]:
        return state.assistant().status().to_dict()

    @app.post("/ai/pull", dependencies=auth)
    def ai_pull(body: PullRequest, request: Request) -> StreamingResponse:
        settings = state.settings()
        try:
            pull = start_pull(OllamaClient(settings.ollama_url), body.model, consent=body.consent)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except OllamaError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

        def events() -> Iterator[dict[str, Any]]:
            for p in pull:
                yield {
                    "type": "progress",
                    "status": p.status,
                    "completed": p.completed,
                    "total": p.total,
                }
            yield {"type": "done", "cancelled": pull.cancelled}

        return StreamingResponse(
            _drain_in_thread(request, events(), pull.cancel), media_type="application/x-ndjson"
        )


def _settings_routes(app: FastAPI, state: ApiState, auth: Auth) -> None:
    @app.get("/settings", dependencies=auth)
    def get_settings() -> Settings:
        return state.settings()

    @app.put("/settings", dependencies=auth)
    def put_settings(update: SettingsUpdate) -> Settings:
        current = state.settings().model_dump()
        changes = update.model_dump(exclude_none=True, exclude={"clear_chat_model"})
        if update.clear_chat_model:
            changes["chat_model"] = None
        try:
            settings = Settings.model_validate({**current, **changes})
        except ValidationError as exc:
            detail = "; ".join(str(e["msg"]).removeprefix("Value error, ") for e in exc.errors())
            raise HTTPException(status_code=422, detail=detail) from exc
        save_settings(settings, state.data_base)
        return settings

    @app.post("/kb/ingest", dependencies=auth)
    def kb_ingest() -> dict[str, Any]:
        summary = KnowledgeService(state.settings(), base=state.data_base).ingest()
        return {
            "kb_version": summary.kb_version,
            "chunks": summary.lexical_chunks,
            "vectors": [r.added + r.updated + r.unchanged for r in summary.vector_reports],
            "note": summary.vectors_skipped_reason,
        }


def _add_middleware(app: FastAPI, state: ApiState) -> None:
    # add_middleware wraps outward, so the last added runs first:
    # host check -> body limit -> rate limit -> CORS -> access log -> routes.
    app.add_middleware(AccessLogMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[*TAURI_ORIGINS, *state.dev_origins],
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT"],
        allow_headers=["Authorization", "Content-Type"],
        max_age=600,
    )
    app.add_middleware(RateLimitMiddleware, limits=state.rate_limits)
    app.add_middleware(BodyLimitMiddleware)
    app.add_middleware(HostCheckMiddleware)
