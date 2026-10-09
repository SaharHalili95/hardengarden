"""Data contracts shared by the scanner, the API and the UI (docs/REQUIREMENTS.md section 5.1)."""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator

CHECK_ID_PATTERN = re.compile(r"^HG-[A-Z]{2,4}-\d{3}$")
MAX_EVIDENCE_ITEMS = 10
MAX_EVIDENCE_CHARS = 240


class Severity(StrEnum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFO = "INFO"


class Status(StrEnum):
    PASS = "PASS"  # noqa: S105  # nosec B105  # justification: enum value, not a password
    FAIL = "FAIL"
    WARN = "WARN"
    ERROR = "ERROR"
    SKIPPED = "SKIPPED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class Category(StrEnum):
    SSH = "ssh"
    FIREWALL = "firewall"
    NETWORK = "network"
    FILESYSTEM = "filesystem"
    ACCOUNTS = "accounts"
    UPDATES = "updates"
    KERNEL = "kernel"
    LOGGING = "logging"


class Reason(StrEnum):
    """Machine-readable reasons for SKIPPED / ERROR / NOT_APPLICABLE results."""

    INSUFFICIENT_PRIVILEGES = "insufficient_privileges"
    UNSUPPORTED_PLATFORM = "unsupported_platform"
    NOT_INSTALLED = "not_installed"
    FILE_MISSING = "file_missing"
    UNAVAILABLE = "unavailable"
    CHECK_CRASHED = "check_crashed"


SUPPORTED_PLATFORMS: frozenset[str] = frozenset({"ubuntu-22.04", "ubuntu-24.04", "debian-12"})
ANY_LINUX = "linux"


class CheckMeta(BaseModel):
    """Static description of a check. Stable forever once released."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    title: str
    category: Category
    severity: Severity
    rationale: str
    requires_root: bool
    platforms: tuple[str, ...]
    kb_doc: str
    remediation_template: str | None

    @field_validator("id")
    @classmethod
    def _valid_id(cls, value: str) -> str:
        if not CHECK_ID_PATTERN.fullmatch(value):
            msg = f"invalid check id: {value!r}"
            raise ValueError(msg)
        return value

    @field_validator("platforms")
    @classmethod
    def _valid_platforms(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        allowed = SUPPORTED_PLATFORMS | {ANY_LINUX}
        unknown = [p for p in value if p not in allowed]
        if not value or unknown:
            msg = f"platforms must be non-empty and within {sorted(allowed)}: {unknown}"
            raise ValueError(msg)
        return value


Evidence = Annotated[str, Field(max_length=MAX_EVIDENCE_CHARS)]


class CheckResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    check_id: str
    status: Status
    evidence: list[Evidence] = Field(default_factory=list, max_length=MAX_EVIDENCE_ITEMS)
    reason: str | None = None
    duration_ms: int = Field(ge=0)


class Platform(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    distro_id: str
    version_id: str
    pretty_name: str
    is_root: bool

    @property
    def key(self) -> str:
        return f"{self.distro_id}-{self.version_id}"

    @property
    def supported(self) -> bool:
        return self.key in SUPPORTED_PLATFORMS


class Coverage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    total: int
    evaluated: int
    skipped: int
    errors: int
    not_applicable: int
    skipped_for_privileges: int
    percent: int | None


class ScoreSummary(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    score: int | None
    coverage: Coverage


class ScanReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    tool_version: str
    scanned_root: str
    platform: Platform
    platform_supported: bool
    results: list[CheckResult]
    summary: ScoreSummary
    privilege_hint: str | None
