"""Account checks: HG-ACC-001 (extra UID 0) and HG-ACC-002 (NOPASSWD sudo rules)."""

from __future__ import annotations

import re
from pathlib import PurePosixPath

from hardengarden.checks.etcfiles import parse_passwd
from hardengarden.core.check import Check, CheckContext, Outcome
from hardengarden.core.models import ANY_LINUX, Category, CheckMeta, Reason, Severity
from hardengarden.core.systemview import (
    AccessDeniedError,
    NotFoundError,
    SystemView,
    SystemViewError,
)

SUDOERS = "/etc/sudoers"
MAX_SUDOERS_DEPTH = 8
_NOPASSWD = re.compile(r"\bNOPASSWD\s*:")
_NO_AUTH = re.compile(r"^\s*Defaults\b.*!\s*authenticate\b")
_INCLUDE = re.compile(r"^[#@](include|includedir)\s+(\S+)\s*$")
_VALID_INCLUDEDIR_NAME = re.compile(r"^[^.~]*[^~]$")  # sudo skips names with '.' or ending in '~'


def check_uid_zero(ctx: CheckContext) -> Outcome:
    try:
        parsed = parse_passwd(ctx.view.read_text("/etc/passwd"))
    except NotFoundError:
        return Outcome.error(Reason.FILE_MISSING, "/etc/passwd does not exist")
    extra = [e for e in parsed.entries if e.uid == 0 and e.name != "root"]
    notes = (
        [f"{len(parsed.malformed_lines)} malformed line(s) ignored"]
        if parsed.malformed_lines
        else []
    )
    if extra:
        return Outcome.failed(
            *(f"account '{e.name}' has UID 0 (/etc/passwd:{e.line})" for e in extra), *notes
        )
    return Outcome.passed("root is the only account with UID 0", *notes)


def _logical_lines(text: str) -> list[tuple[int, str]]:
    """Join backslash continuations; keep the starting line number."""
    lines: list[tuple[int, str]] = []
    buffer = ""
    start = 0
    for number, raw in enumerate(text.splitlines(), start=1):
        if not buffer:
            start = number
        if raw.endswith("\\"):
            buffer += raw[:-1] + " "
            continue
        lines.append((start, buffer + raw))
        buffer = ""
    if buffer:
        lines.append((start, buffer))
    return lines


class _SudoersScan:
    def __init__(self, view: SystemView) -> None:
        self.view = view
        self.findings: list[str] = []
        self.unreadable: list[str] = []
        self.stack: list[str] = []
        self.notes: list[str] = []

    def scan(self, path: str, depth: int = 0) -> None:
        if path in self.stack or depth > MAX_SUDOERS_DEPTH:
            self.notes.append(f"include loop or depth limit at {path} (ignored)")
            return
        text = self.view.read_text(path)
        self.stack.append(path)
        try:
            for number, line in _logical_lines(text):
                self._line(path, number, line.strip(), depth)
        finally:
            self.stack.pop()

    def _line(self, path: str, number: int, line: str, depth: int) -> None:
        include = _INCLUDE.match(line)
        if include:
            kind, target = include.groups()
            base = PurePosixPath(path).parent
            target_path = target if target.startswith("/") else str(base / target)
            if kind == "includedir":
                self._include_dir(target_path, depth)
            else:
                self._include_file(target_path, depth)
            return
        if not line or line.startswith("#"):
            return
        if _NOPASSWD.search(line) or _NO_AUTH.search(line):
            self.findings.append(f"{path}:{number}: {line}")

    def _include_file(self, path: str, depth: int) -> None:
        try:
            self.scan(path, depth + 1)
        except AccessDeniedError:
            self.unreadable.append(path)
        except SystemViewError:
            return

    def _include_dir(self, directory: str, depth: int) -> None:
        try:
            names = self.view.list_dir(directory)
        except AccessDeniedError:
            self.unreadable.append(directory)
            return
        except SystemViewError:
            return
        for name in names:
            if _VALID_INCLUDEDIR_NAME.match(name):
                child = str(PurePosixPath(directory) / name)
                if self.view.is_file(child):
                    self._include_file(child, depth)


def check_sudo_nopasswd(ctx: CheckContext) -> Outcome:
    if not ctx.view.exists(SUDOERS):
        return Outcome.not_applicable(Reason.NOT_INSTALLED, "sudo is not installed")
    scan = _SudoersScan(ctx.view)
    scan.scan(SUDOERS)  # AccessDeniedError on the main file propagates (-> SKIPPED)
    if scan.unreadable:
        reason = Reason.UNAVAILABLE if ctx.is_root else Reason.INSUFFICIENT_PRIVILEGES
        return Outcome.skipped(reason, *(f"cannot read {p}" for p in scan.unreadable))
    if scan.findings:
        return Outcome.failed(
            f"{len(scan.findings)} sudo rule(s) without password authentication",
            *scan.findings,
            *scan.notes,
        )
    return Outcome.passed("no NOPASSWD or !authenticate rules found", *scan.notes)


CHECKS = (
    Check(
        CheckMeta(
            id="HG-ACC-001",
            title="Accounts with UID 0 other than root",
            category=Category.ACCOUNTS,
            severity=Severity.CRITICAL,
            rationale="Any account with UID 0 is root, whatever its name. An extra one is a "
            "classic backdoor and is easy to miss in an account list.",
            requires_root=False,
            platforms=(ANY_LINUX,),
            kb_doc="knowledge/uid-zero-accounts.md",
            remediation_template="hg-acc-001.sh",
        ),
        check_uid_zero,
    ),
    Check(
        CheckMeta(
            id="HG-ACC-002",
            title="NOPASSWD entries in sudoers",
            category=Category.ACCOUNTS,
            severity=Severity.MEDIUM,
            rationale="Passwordless sudo turns any compromise of that user's session into "
            "full root access, with no second factor of the user's password.",
            requires_root=True,
            platforms=(ANY_LINUX,),
            kb_doc="knowledge/sudo-nopasswd.md",
            remediation_template="hg-acc-002.sh",
        ),
        check_sudo_nopasswd,
    ),
)
