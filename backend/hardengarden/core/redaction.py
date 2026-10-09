"""Redaction for evidence and logs (R9). Applied before anything is stored or shown."""

from __future__ import annotations

import re

from hardengarden.core.models import MAX_EVIDENCE_CHARS, MAX_EVIDENCE_ITEMS

REDACTED = "[REDACTED]"

_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    # PEM private keys and certificates' private parts
    (
        re.compile(
            r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(-----END [A-Z ]*PRIVATE KEY-----|$)", re.S
        ),
        REDACTED,
    ),
    # crypt(3) hashes: $1$, $2b$, $5$, $6$, $y$, $gy$, $7$ ...
    (re.compile(r"\$(?:1|2[abxy]?|5|6|7|y|gy|sha1|md5)\$[^\s:]+"), REDACTED),
    # Authorization headers and bearer tokens
    (re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}"), r"\1 " + REDACTED),
    # key=value / key: value secrets
    (
        re.compile(
            r"(?i)(?<![A-Za-z/.])(password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key|private[_-]?key)"
            r"(\s*[=:]\s*)(\"[^\"]*\"|'[^']*'|\S+)"
        ),
        r"\1\2" + REDACTED,
    ),
    # OpenSSH public/private key material blobs
    (
        re.compile(r"\b(ssh-(?:rsa|ed25519|dss)|ecdsa-sha2-nistp\d+)\s+[A-Za-z0-9+/=]{40,}"),
        r"\1 " + REDACTED,
    ),
)


def redact(text: str) -> str:
    """Remove secrets from ``text``. Idempotent."""
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def clean_evidence(items: list[str]) -> list[str]:
    """Redact, flatten whitespace, truncate and cap evidence to the model limits."""
    cleaned: list[str] = []
    for item in items:
        flat = " ".join(redact(item).split())
        if len(flat) > MAX_EVIDENCE_CHARS:
            flat = flat[: MAX_EVIDENCE_CHARS - 1] + "…"
        if flat:
            cleaned.append(flat)
    if len(cleaned) > MAX_EVIDENCE_ITEMS:
        hidden = len(cleaned) - (MAX_EVIDENCE_ITEMS - 1)
        cleaned = [*cleaned[: MAX_EVIDENCE_ITEMS - 1], f"... and {hidden} more"]
    return cleaned
