"""Parsers for ``/etc/passwd`` and ``/etc/group`` shared by several checks."""

from __future__ import annotations

from dataclasses import dataclass

from hardengarden.core.systemview import SystemView, SystemViewError

PASSWD_FIELDS = 7
GROUP_FIELDS = 4


@dataclass(frozen=True, slots=True)
class PasswdEntry:
    name: str
    uid: int
    gid: int
    line: int


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
        entries.append(PasswdEntry(fields[0], uid, gid, number))
    return ParsedPasswd(tuple(entries), tuple(malformed))


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
