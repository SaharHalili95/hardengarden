"""Grounded generation (R13-R16, R38).

Flow: retrieval decides answerability BEFORE any model call; the prompt keeps untrusted
system data in delimited blocks; tokens stream through the sanitizer; the final answer must
cite at least one retrieved passage or it is replaced by a fixed message.
"""

from __future__ import annotations

import re
import threading
import time
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from importlib import resources
from typing import Any, Protocol

from hardengarden.rag.models import InsufficientMemoryError, Memory, ModelInfo, ensure_memory
from hardengarden.rag.ollama import NDJSONStream, OllamaClient, OllamaError, OllamaUnavailableError
from hardengarden.rag.retrieve import RetrievalResult
from hardengarden.rag.sanitize import StreamSanitizer, neutralize_untrusted, sanitize_text

NOT_ENOUGH_INFORMATION = "Not enough information in the knowledge base to answer this."
UNGROUNDED = (
    "The model's answer did not cite the knowledge base, so it is not shown. "
    "Try again, or read the linked knowledge-base article."
)
OLLAMA_MISSING = (
    "AI explanations need Ollama running on this computer. Install Ollama, start it, and "
    "download a model from Settings. Scanning, scores and remediation scripts work without it."
)
REFUSAL_MARKER = "NOT_ENOUGH_INFORMATION"
_CITATION = re.compile(r"\[kb:([A-Za-z0-9_.:#-]+)\]")
TEMPERATURE = 0.0
SEED = 42


def system_prompt() -> str:
    return (
        resources.files("hardengarden.rag")
        .joinpath("prompts/system.txt")
        .read_text(encoding="utf-8")
    )


class Outcome(StrEnum):
    ANSWERED = "answered"
    NOT_ENOUGH_INFORMATION = "not_enough_information"
    UNGROUNDED = "ungrounded"
    OLLAMA_UNAVAILABLE = "ollama_unavailable"
    INSUFFICIENT_MEMORY = "insufficient_memory"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class Answer:
    outcome: Outcome
    text: str
    citations: tuple[str, ...] = ()
    model: str | None = None
    cached: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome.value,
            "text": self.text,
            "citations": list(self.citations),
            "model": self.model,
            "cached": self.cached,
        }


@dataclass(frozen=True, slots=True)
class Finding:
    """What the model is told about a finding. Evidence is untrusted system data."""

    check_id: str
    title: str
    status: str
    severity: str
    evidence: Sequence[str] = field(default_factory=tuple)


def build_messages(
    question: str, retrieval: RetrievalResult, finding: Finding | None = None
) -> list[dict[str, str]]:
    parts: list[str] = []
    if finding is not None:
        parts.append(
            f"Finding: {finding.check_id} ({finding.title}); status {finding.status}; "
            f"severity {finding.severity}."
        )
        evidence = "\n".join(neutralize_untrusted(e) for e in finding.evidence) or "(none)"
        parts.append(f"<untrusted_system_data>\n{evidence}\n</untrusted_system_data>")
    parts.append(f"Question: {neutralize_untrusted(question)}")
    parts.append("Knowledge-base passages:")
    for hit in retrieval.hits:
        body = neutralize_untrusted(hit.passage.text)
        parts.append(f'<kb_passage id="{hit.passage.id}">\n{body}\n</kb_passage>')
    return [
        {"role": "system", "content": system_prompt()},
        {"role": "user", "content": "\n\n".join(parts)},
    ]


def finalize(raw: str, retrieval: RetrievalResult, model: str) -> Answer:
    """Validate grounding and sanitize the complete model output."""
    if REFUSAL_MARKER in raw:
        return Answer(Outcome.NOT_ENOUGH_INFORMATION, NOT_ENOUGH_INFORMATION, model=model)
    allowed = {hit.passage.id for hit in retrieval.hits}
    cited: list[str] = []
    for match in _CITATION.finditer(raw):
        if match.group(1) in allowed and match.group(1) not in cited:
            cited.append(match.group(1))
    if not cited:
        return Answer(Outcome.UNGROUNDED, UNGROUNDED, model=model)
    # Drop citations of passages that were not provided (invented ids).
    cleaned = _CITATION.sub(lambda m: m.group(0) if m.group(1) in allowed else "", raw)
    return Answer(Outcome.ANSWERED, sanitize_text(cleaned), tuple(cited), model=model)


class ChatStream(Protocol):
    """Streamed model output: iterable chunks plus an abort() that is safe from any thread."""

    def __iter__(self) -> Iterator[dict[str, Any]]: ...

    def abort(self) -> None: ...


class ChatBackend(Protocol):
    def open_chat(
        self, model: str, messages: list[dict[str, str]], options: dict[str, Any], timeout: float
    ) -> ChatStream: ...


class OllamaChat:
    def __init__(self, client: OllamaClient) -> None:
        self.client = client

    def open_chat(
        self, model: str, messages: list[dict[str, str]], options: dict[str, Any], timeout: float
    ) -> NDJSONStream:
        body = {"model": model, "messages": messages, "stream": True, "options": options}
        return self.client.open_stream("/api/chat", body, timeout=timeout)


@dataclass(frozen=True, slots=True)
class GenerationOptions:
    timeout_s: float = 120.0
    max_tokens: int = 400


@dataclass
class Generation:
    """A running generation: iterate it for sanitized text deltas, then read ``answer``."""

    backend: ChatBackend
    model: ModelInfo
    messages: list[dict[str, str]]
    retrieval: RetrievalResult
    options: GenerationOptions = field(default_factory=GenerationOptions)
    on_complete: Callable[[Answer], None] | None = None
    answer: Answer | None = None
    _cancel: threading.Event = field(default_factory=threading.Event)
    _stream: ChatStream | None = None
    _timed_out: bool = False
    _raw: list[str] = field(default_factory=list)

    def cancel(self) -> None:
        self._cancel.set()
        if self._stream is not None:
            self._stream.abort()

    def _on_timeout(self) -> None:
        self._timed_out = True
        self.cancel()

    def _tokens(self, started: float) -> Iterator[str]:
        """Raw model tokens until done, cancel or deadline. Raises OllamaError."""
        model_options = {
            "temperature": TEMPERATURE,
            "seed": SEED,
            "num_predict": self.options.max_tokens,
        }
        self._stream = self.backend.open_chat(
            self.model.name, self.messages, model_options, self.options.timeout_s
        )
        if self._cancel.is_set():
            self._stream.abort()
        for item in self._stream:
            if self._cancel.is_set() or time.monotonic() - started > self.options.timeout_s:
                return
            yield str((item.get("message") or {}).get("content", ""))
            if item.get("done"):
                return

    def _interrupted(self, started: float) -> Answer | None:
        if self._timed_out or time.monotonic() - started > self.options.timeout_s:
            return Answer(
                Outcome.TIMEOUT,
                f"The model did not finish within {self.options.timeout_s:.0f} seconds. "
                "Try a smaller model.",
                model=self.model.name,
            )
        if self._cancel.is_set():
            return Answer(Outcome.CANCELLED, "Stopped.", model=self.model.name)
        return None

    def __iter__(self) -> Iterator[str]:
        sanitizer = StreamSanitizer()
        watchdog = threading.Timer(self.options.timeout_s, self._on_timeout)
        watchdog.daemon = True
        watchdog.start()
        started = time.monotonic()
        try:
            for token in self._tokens(started):
                self._raw.append(token)
                if delta := sanitizer.feed(token):
                    yield delta
        except OllamaUnavailableError:
            self.answer = Answer(Outcome.OLLAMA_UNAVAILABLE, OLLAMA_MISSING, model=self.model.name)
            return
        except OllamaError as exc:
            if not self._cancel.is_set():
                self.answer = Answer(
                    Outcome.ERROR, f"The model failed: {exc}", model=self.model.name
                )
                return
        finally:
            watchdog.cancel()
            if self._stream is not None:
                self._stream.abort()
        self.answer = self._interrupted(started)
        if self.answer is not None:
            return
        if tail := sanitizer.flush():
            yield tail
        self.answer = finalize("".join(self._raw), self.retrieval, self.model.name)
        if self.on_complete is not None:
            self.on_complete(self.answer)

    def run(self) -> Answer:
        for _ in self:
            pass
        if self.answer is None:  # pragma: no cover - __iter__ always sets it
            msg = "generation finished without an answer"
            raise RuntimeError(msg)
        return self.answer


def prepare(  # noqa: PLR0913  # justification: keyword-only inputs of one request; grouping them would only rename them
    backend: ChatBackend,
    model: ModelInfo,
    question: str,
    retrieval: RetrievalResult,
    *,
    finding: Finding | None = None,
    memory: Memory | None = None,
    options: GenerationOptions | None = None,
    on_complete: Callable[[Answer], None] | None = None,
) -> Generation | Answer:
    """Return an immediate Answer (refusal, memory guard) or a Generation to stream."""
    if not retrieval.answerable:
        return Answer(Outcome.NOT_ENOUGH_INFORMATION, NOT_ENOUGH_INFORMATION)
    try:
        ensure_memory(model, memory)
    except InsufficientMemoryError as exc:
        return Answer(Outcome.INSUFFICIENT_MEMORY, str(exc), model=model.name)
    messages = build_messages(question, retrieval, finding)
    return Generation(
        backend, model, messages, retrieval, options or GenerationOptions(), on_complete=on_complete
    )
