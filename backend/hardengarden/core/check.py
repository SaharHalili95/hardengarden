"""Check plumbing: the context a check receives and the outcome it returns."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from hardengarden.core.models import CheckMeta, Reason, Status
from hardengarden.core.runner import Runner
from hardengarden.core.systemview import SystemView


@dataclass(frozen=True, slots=True)
class CheckContext:
    view: SystemView
    runner: Runner
    is_root: bool

    @property
    def live_host(self) -> bool:
        """True when scanning the real ``/``; only then may commands describe the target."""
        return self.view.is_host_root


@dataclass(frozen=True, slots=True)
class Outcome:
    status: Status
    evidence: list[str] = field(default_factory=list)
    reason: str | None = None

    @classmethod
    def passed(cls, *evidence: str) -> Outcome:
        return cls(Status.PASS, list(evidence))

    @classmethod
    def failed(cls, *evidence: str) -> Outcome:
        return cls(Status.FAIL, list(evidence))

    @classmethod
    def warn(cls, *evidence: str) -> Outcome:
        return cls(Status.WARN, list(evidence))

    @classmethod
    def skipped(cls, reason: Reason, *evidence: str) -> Outcome:
        return cls(Status.SKIPPED, list(evidence), reason.value)

    @classmethod
    def not_applicable(cls, reason: Reason, *evidence: str) -> Outcome:
        return cls(Status.NOT_APPLICABLE, list(evidence), reason.value)

    @classmethod
    def error(cls, reason: Reason, *evidence: str) -> Outcome:
        return cls(Status.ERROR, list(evidence), reason.value)


CheckFunc = Callable[[CheckContext], Outcome]


@dataclass(frozen=True, slots=True)
class Check:
    meta: CheckMeta
    run: CheckFunc
