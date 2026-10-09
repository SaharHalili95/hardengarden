"""Automatic security updates: HG-UPD-001 (Debian/Ubuntu, unattended-upgrades)."""

from __future__ import annotations

import re

from hardengarden.core.check import Check, CheckContext, Outcome
from hardengarden.core.models import SUPPORTED_PLATFORMS, Category, CheckMeta, Severity
from hardengarden.core.systemview import SystemViewError

PACKAGE_MARKERS = (
    "/var/lib/dpkg/info/unattended-upgrades.list",
    "/var/lib/dpkg/info/unattended-upgrades.md5sums",
)
APT_PARTS = "/etc/apt/apt.conf.d"
APT_MAIN = "/etc/apt/apt.conf"
UNATTENDED = "apt::periodic::unattended-upgrade"
UPDATE_LISTS = "apt::periodic::update-package-lists"

_PART_NAME = re.compile(r"^[A-Za-z0-9_.-]+$")
_TOKEN = re.compile(r'"[^"]*"|[{};]|[^\s{};"]+')
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_LINE_COMMENT = re.compile(r"(^|\s)(//|#).*$", re.M)


def parse_apt_conf(text: str) -> dict[str, str]:
    """Parse apt.conf(5) syntax, flat (``A::B "v";``) or nested (``A { B "v"; };``).

    Keys are lower-cased and joined with ``::``. Later assignments win (apt semantics).
    """
    cleaned = _LINE_COMMENT.sub("", _BLOCK_COMMENT.sub("", text))
    tokens = _TOKEN.findall(cleaned)
    values: dict[str, str] = {}
    scope: list[str] = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        nxt = tokens[i + 1] if i + 1 < len(tokens) else ""
        if tok == "}":
            if scope:
                scope.pop()
            i += 1
        elif tok in {";", "{"}:
            i += 1
        elif nxt == "{":
            scope.append(tok.lower())
            i += 2
        elif nxt.startswith('"'):
            values["::".join([*scope, tok.lower()])] = nxt.strip('"')
            i += 2
        else:
            i += 1
    return values


def _enabled(value: str | None) -> bool:
    if value is None:
        return False
    if value.strip().lower() == "always":
        return True
    try:
        return int(value) > 0
    except ValueError:
        return value.strip().lower() in {"true", "yes"}


def effective_apt_config(ctx: CheckContext) -> tuple[dict[str, str], list[str]]:
    merged: dict[str, str] = {}
    sources: list[str] = []
    try:
        names = ctx.view.list_dir(APT_PARTS)
    except SystemViewError:
        names = []
    paths = [
        f"{APT_PARTS}/{n}"
        for n in names
        if _PART_NAME.match(n) and ("." not in n or n.endswith(".conf"))
    ]
    for path in [*paths, APT_MAIN]:
        try:
            parsed = parse_apt_conf(ctx.view.read_text(path))
        except SystemViewError:
            continue
        for key in (UNATTENDED, UPDATE_LISTS):
            if key in parsed:
                sources.append(f'{path}: {key} "{parsed[key]}"')
        merged.update(parsed)
    return merged, sources


def check_unattended_upgrades(ctx: CheckContext) -> Outcome:
    if not any(ctx.view.exists(marker) for marker in PACKAGE_MARKERS):
        return Outcome.failed("package unattended-upgrades is not installed")
    config, sources = effective_apt_config(ctx)
    upgrades = _enabled(config.get(UNATTENDED))
    lists = _enabled(config.get(UPDATE_LISTS))
    evidence = sources or ["no APT::Periodic settings found"]
    if upgrades and lists:
        return Outcome.passed("unattended-upgrades installed and enabled", *evidence)
    if upgrades:
        return Outcome.warn(
            "unattended upgrades enabled but package lists are not refreshed automatically",
            *evidence,
        )
    return Outcome.failed("APT::Periodic::Unattended-Upgrade is not enabled", *evidence)


CHECKS = (
    Check(
        CheckMeta(
            id="HG-UPD-001",
            title="Automatic security updates enabled",
            category=Category.UPDATES,
            severity=Severity.MEDIUM,
            rationale="Most real-world compromises use known, already-patched flaws. Applying "
            "security updates automatically closes that window without relying on memory.",
            requires_root=False,
            platforms=tuple(sorted(SUPPORTED_PLATFORMS)),
            kb_doc="knowledge/automatic-updates.md",
            remediation_template="hg-upd-001.sh",
        ),
        check_unattended_upgrades,
    ),
)
