"""Parsers for ``/etc/passwd`` and ``/etc/group`` shared by several checks."""

from __future__ import annotations

from dataclasses import dataclass

from hardengarden.core.systemview import SystemView, SystemViewError

PASSWD_FIELDS = 7
GROUP_FIELDS = 4
SHADOW_MIN_FIELDS = 8


@dataclass(frozen=True, slots=True)
class PasswdEntry:
    name: str
    uid: int
    gid: int
    line: int
    shell: str = ""


@dataclass(frozen=True, slots=True)
class ParsedPasswd:
    entries: tuple[PasswdEntry, ...]
    malformed_lines: tuple[int, ...]


def parse_passwd(text: str) -> ParsedPasswd:
    entries: list[PasswdEntry] = []
    malformed: list[int] = []
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.split(":")
        if len(fields) != PASSWD_FIELDS or not fields[0]:
            malformed.append(number)
            continue
        try:
            uid, gid = int(fields[2]), int(fields[3])
        except ValueError:
            malformed.append(number)
            continue
        entries.append(PasswdEntry(fields[0], uid, gid, number, fields[6]))
    return ParsedPasswd(tuple(entries), tuple(malformed))


@dataclass(frozen=True, slots=True)
class ShadowState:
    locked: bool  # password field starts with "!" or "*" (no password login possible)
    expired: bool  # account expiry date is set and in the past


def shadow_states(text: str, today_days: int) -> dict[str, ShadowState]:
    """Lock/expiry state per account. The password hash itself is never kept or returned."""
    states: dict[str, ShadowState] = {}
    for raw in text.splitlines():
        fields = raw.split(":")
        if len(fields) < SHADOW_MIN_FIELDS or not fields[0]:
            continue
        expire = fields[7].strip()
        expired = expire.isdigit() and int(expire) <= today_days
        states[fields[0]] = ShadowState(fields[1].startswith(("!", "*")), expired)
    return states


def group_ids(text: str) -> dict[str, int]:
    """Map group name -> gid (first definition wins, malformed lines ignored)."""
    result: dict[str, int] = {}
    for raw in text.splitlines():
        fields = raw.strip().split(":")
        if len(fields) != GROUP_FIELDS or not fields[0]:
            continue
        try:
            result.setdefault(fields[0], int(fields[2]))
        except ValueError:
            continue
    return result


def lookup_group_ids(view: SystemView) -> dict[str, int]:
    try:
        return group_ids(view.read_text("/etc/group"))
    except SystemViewError:
        return {}
