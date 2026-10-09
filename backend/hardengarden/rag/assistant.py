"""High-level AI features: status (R36), consent-gated model download (R37), cached
explanations (R30a) and grounded chat. Everything here is optional: if Ollama is absent the
caller gets a clear, actionable status instead of an exception (R16).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from hardengarden.core.check import Check
from hardengarden.core.models import CheckResult
from hardengarden.core.paths import cache_dir, private_dir
from hardengarden.core.settings import Settings
from hardengarden.rag.generate import (
    NOT_ENOUGH_INFORMATION,
    OLLAMA_MISSING,
    Answer,
    ChatBackend,
    Finding,
    Generation,
    GenerationOptions,
    OllamaChat,
    Outcome,
    prepare,
)
from hardengarden.rag.models import (
    CATALOG,
    Hardware,
    InsufficientMemoryError,
    ModelInfo,
    Tier,
    detect_hardware,
    model_for,
    select_tier,
)
from hardengarden.rag.ollama import NDJSONStream, OllamaClient, OllamaError
from hardengarden.rag.service import KnowledgeService


class AIState(StrEnum):
    READY = "ready"
    REDUCED_QUALITY = "reduced_quality"
    NOT_ENOUGH_MEMORY = "not_enough_memory"
    MODEL_NOT_DOWNLOADED = "model_not_downloaded"
    OLLAMA_NOT_INSTALLED = "ollama_not_installed"
    DISABLED = "disabled"


@dataclass(frozen=True, slots=True)
class AIStatus:
    state: AIState
    tier: Tier
    model: ModelInfo | None
    hardware: Hardware
    installed_models: tuple[str, ...]
    message: str
    tier_overridden: bool

    def to_dict(self) -> dict[str, Any]:
        memory = self.hardware.memory
        return {
            "state": self.state.value,
            "tier": self.tier.value,
            "model": self.model.name if self.model else None,
            "model_download_bytes": self.model.download_bytes if self.model else None,
            "model_required_free_bytes": self.model.required_free_bytes if self.model else None,
            "reduced_quality": bool(self.model and self.model.reduced_quality),
            "memory_total_bytes": memory.total_bytes if memory else None,
            "memory_available_bytes": memory.available_bytes if memory else None,
            "cpu_cores": self.hardware.cpu_cores,
            "gpu": self.hardware.gpu,
            "installed_models": list(self.installed_models),
            "message": self.message,
            "tier_overridden": self.tier_overridden,
        }


def _installed(name: str, installed: tuple[str, ...]) -> bool:
    return name in installed or f"{name}:latest" in installed


def compute_status(
    settings: Settings, client: OllamaClient, hardware: Hardware | None = None
) -> AIStatus:
    try:
        client.version()
        installed = tuple(client.installed_models())
        gpu = any(int(m.get("size_vram", 0) or 0) > 0 for m in client.running()) or None
    except OllamaError:
        hw = hardware or detect_hardware()
        return AIStatus(AIState.OLLAMA_NOT_INSTALLED, Tier.DISABLED, None, hw, (), OLLAMA_MISSING,
                        tier_overridden=bool(settings.chat_model))  # fmt: skip
    hw = hardware or detect_hardware(gpu=gpu)
    total = hw.memory.total_bytes if hw.memory else None
    tier = select_tier(total, ollama_available=True)
    model = model_for(tier, settings.chat_model)
    overridden = settings.chat_model is not None
    if model is None:
        return AIStatus(
            AIState.DISABLED, tier, None, hw, installed,
            "This computer has less than 4 GB of RAM, so AI explanations are disabled. "
            "Scanning, scores and remediation scripts work normally.", overridden,
        )  # fmt: skip
    if not _installed(model.name, installed):
        size = model.download_bytes / 1e9
        return AIStatus(
            AIState.MODEL_NOT_DOWNLOADED, tier, model, hw, installed,
            f"Download {model.name} (about {size:.1f} GB) from Settings to enable explanations.",
            overridden,
        )  # fmt: skip
    if hw.memory is not None and hw.memory.available_bytes < model.required_free_bytes:
        message = str(InsufficientMemoryError(model, hw.memory.available_bytes))
        return AIStatus(AIState.NOT_ENOUGH_MEMORY, tier, model, hw, installed, message, overridden)
    if model.reduced_quality:
        message = f"Using the small model {model.name}: answers may be less precise."
        return AIStatus(AIState.REDUCED_QUALITY, tier, model, hw, installed, message, overridden)
    return AIStatus(AIState.READY, tier, model, hw, installed, f"Ready ({model.name}).", overridden)


class ConsentRequiredError(Exception):
    """R37: models are never downloaded without an explicit user action."""


class UnknownModelError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class PullProgress:
    status: str
    completed: int | None
    total: int | None


class ModelPull:
    """A consented download. Iterate for progress; call ``cancel()`` from any thread."""

    def __init__(self, stream: NDJSONStream) -> None:
        self._stream = stream
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True
        self._stream.abort()

    @property
    def cancelled(self) -> bool:
        """True only after an explicit cancel(), not after a normal finish."""
        return self._cancelled

    def __iter__(self) -> Iterator[PullProgress]:
        for item in self._stream:
            completed, total = item.get("completed"), item.get("total")
            yield PullProgress(
                status=str(item.get("status", "")),
                completed=int(completed) if isinstance(completed, int) else None,
                total=int(total) if isinstance(total, int) else None,
            )


def start_pull(client: OllamaClient, model_name: str, *, consent: bool) -> ModelPull:
    if not consent:
        msg = "downloading a model requires explicit consent"
        raise ConsentRequiredError(msg)
    if model_name not in CATALOG:
        msg = f"unknown model {model_name!r}; choose one of {sorted(CATALOG)}"
        raise UnknownModelError(msg)
    return ModelPull(
        client.open_stream("/api/pull", {"model": model_name, "stream": True}, timeout=600)
    )


class ExplanationCache:
    """R30a: answers keyed by (check_id, KB version, model, evidence hash)."""

    def __init__(self, directory: Path | None = None) -> None:
        self.directory = directory or cache_dir() / "explanations"

    @staticmethod
    def key(check_id: str, kb_version: str, model: str, evidence: list[str]) -> str:
        evidence_hash = hashlib.sha256("\n".join(evidence).encode()).hexdigest()
        material = json.dumps([check_id, kb_version, model, evidence_hash])
        return hashlib.sha256(material.encode()).hexdigest()

    def get(self, key: str) -> Answer | None:
        try:
            data = json.loads((self.directory / f"{key}.json").read_text(encoding="utf-8"))
            return Answer(
                outcome=Outcome(data["outcome"]),
                text=str(data["text"]),
                citations=tuple(str(c) for c in data["citations"]),
                model=data.get("model"),
                cached=True,
            )
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def put(self, key: str, answer: Answer) -> None:
        if answer.outcome is not Outcome.ANSWERED:
            return
        directory = private_dir(self.directory)
        target = directory / f"{key}.json"
        tmp = target.with_suffix(".tmp")
        tmp.write_text(json.dumps(answer.to_dict()), encoding="utf-8")
        tmp.chmod(0o600)
        tmp.replace(target)


class Assistant:
    def __init__(  # noqa: PLR0913  # justification: keyword-only dependency injection for tests
        self,
        settings: Settings,
        knowledge: KnowledgeService,
        *,
        client: OllamaClient | None = None,
        backend: ChatBackend | None = None,
        cache: ExplanationCache | None = None,
        hardware: Hardware | None = None,
    ) -> None:
        self.settings = settings
        self.knowledge = knowledge
        self.client = client or OllamaClient(
            settings.ollama_url, timeout_s=settings.generation_timeout_s
        )
        self.backend = backend or OllamaChat(self.client)
        self.cache = cache or ExplanationCache()
        self.hardware = hardware

    def _options(self) -> GenerationOptions:
        return GenerationOptions(self.settings.generation_timeout_s, self.settings.max_tokens)

    def status(self) -> AIStatus:
        return compute_status(self.settings, self.client, self.hardware)

    def _model(self, status: AIStatus) -> ModelInfo | Answer:
        if status.state in {AIState.READY, AIState.REDUCED_QUALITY} and status.model is not None:
            return status.model
        outcome = {
            AIState.NOT_ENOUGH_MEMORY: Outcome.INSUFFICIENT_MEMORY,
            AIState.OLLAMA_NOT_INSTALLED: Outcome.OLLAMA_UNAVAILABLE,
        }.get(status.state, Outcome.OLLAMA_UNAVAILABLE)
        return Answer(outcome, status.message)

    def explain(
        self, check: Check, result: CheckResult, *, use_cache: bool = True
    ) -> Generation | Answer:
        meta = check.meta
        question = f"Explain the finding {meta.id} ({meta.title}) and what to do about it."
        retrieval = self.knowledge.retriever().for_source(Path(meta.kb_doc).stem, question)
        status = self.status()
        model = self._model(status)
        if isinstance(model, Answer):
            return model
        key = ExplanationCache.key(
            meta.id, self.knowledge.kb.version, model.name, list(result.evidence)
        )
        if use_cache and (hit := self.cache.get(key)) is not None:
            return hit
        finding = Finding(
            meta.id, meta.title, result.status.value, meta.severity.value, result.evidence
        )
        return prepare(
            self.backend, model, question, retrieval,
            finding=finding, memory=status.hardware.memory, options=self._options(),
            on_complete=lambda answer: self.cache.put(key, answer),
        )  # fmt: skip

    def chat(self, question: str) -> Generation | Answer:
        retrieval = self.knowledge.retriever().search(question)
        if not retrieval.answerable:  # refuse before even looking at the model (R13)
            return Answer(Outcome.NOT_ENOUGH_INFORMATION, NOT_ENOUGH_INFORMATION)
        status = self.status()
        model = self._model(status)
        if isinstance(model, Answer):
            return model
        return prepare(
            self.backend, model, question, retrieval, memory=status.hardware.memory,
            options=self._options(),
        )  # fmt: skip
