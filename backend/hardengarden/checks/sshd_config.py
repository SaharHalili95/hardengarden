"""Parser for OpenSSH server configuration (docs/REQUIREMENTS.md section 5.3).

Semantics implemented, following sshd_config(5):

* Keywords are case-insensitive; arguments may follow whitespace or ``=``; ``#`` starts a
  comment line; arguments may be double-quoted.
* For each keyword the **first** obtained value wins.
* ``Include`` takes one or more paths or globs; relative paths are relative to
  ``/etc/ssh``; matches are processed in lexical order, at the point of the directive.
  Recursion is bounded and include loops are detected and reported, never followed.
* ``Match`` starts a conditional block that lasts until the next ``Match`` or the end of
  the file that opened it. Directives inside a block are recorded as conditional
  overrides, which take precedence for matching connections.
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from hardengarden.core.systemview import (
    AccessDeniedError,
    NotFoundError,
    SystemView,
    SystemViewError,
)

MAIN_CONFIG = "/etc/ssh/sshd_config"
SSH_DIR = "/etc/ssh"
MAX_INCLUDE_DEPTH = 16


@dataclass(frozen=True, slots=True)
class Directive:
    keyword: str  # lower-case
    value: str  # lower-case first argument
    source: str  # "file:line"
    match: str | None  # Match condition, None for global context


@dataclass(slots=True)
class SshdConfig:
    directives: list[Directive] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    unreadable: list[str] = field(default_factory=list)

    def global_value(self, keyword: str) -> Directive | None:
        key = keyword.lower()
        return next((d for d in self.directives if d.keyword == key and d.match is None), None)

    def overrides(self, keyword: str) -> list[Directive]:
        key = keyword.lower()
        return [d for d in self.directives if d.keyword == key and d.match is not None]


_LINE = re.compile(r"^([A-Za-z][A-Za-z0-9]*)(?:\s*=\s*|\s+|$)(.*)$")


def _split(line: str) -> tuple[str, list[str]] | None:
    """Split a config line into (lower-case keyword, args). ``None`` for blanks/comments."""
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None
    found = _LINE.match(stripped)
    if found is None:
        return ("", [])
    keyword, rest = found.group(1), found.group(2)
    try:
        args = shlex.split(rest, comments=True, posix=True)
    except ValueError:
        args = rest.split()
    return keyword.lower(), args


class _Parser:
    def __init__(self, view: SystemView) -> None:
        self.view = view
        self.config = SshdConfig()
        self.stack: list[str] = []

    def parse_file(self, path: str, match: str | None, depth: int) -> None:
        if path in self.stack:
            self.config.notes.append(f"include loop detected at {path} (ignored)")
            return
        if depth > MAX_INCLUDE_DEPTH:
            self.config.notes.append(f"include depth limit reached at {path} (ignored)")
            return
        text = self.view.read_text(path)  # errors for the main file propagate
        self.stack.append(path)
        try:
            self._parse_lines(path, text, match, depth)
        finally:
            self.stack.pop()

    def _parse_lines(self, path: str, text: str, match: str | None, depth: int) -> None:
        current_match = match
        for number, raw in enumerate(text.splitlines(), start=1):
            parsed = _split(raw)
            if parsed is None:
                continue
            keyword, args = parsed
            where = f"{path}:{number}"
            if not keyword:
                self.config.notes.append(f"malformed line ignored ({where})")
                continue
            if keyword == "match":
                condition = " ".join(args).lower()
                if not args:
                    self.config.notes.append(f"malformed Match line ignored ({where})")
                    continue
                current_match = condition
                continue
            if keyword == "include":
                if not args:
                    self.config.notes.append(f"malformed Include line ignored ({where})")
                    continue
                for pattern in args:
                    self._include(pattern, current_match, depth, where)
                continue
            if not args:
                self.config.notes.append(f"directive without value ignored ({where})")
                continue
            self.config.directives.append(
                Directive(keyword=keyword, value=args[0].lower(), source=where, match=current_match)
            )

    def _include(self, pattern: str, match: str | None, depth: int, where: str) -> None:
        absolute = pattern if pattern.startswith("/") else str(PurePosixPath(SSH_DIR) / pattern)
        for included in self.view.glob(absolute):
            if not self.view.is_file(included):
                continue
            try:
                self.parse_file(included, match, depth + 1)
            except AccessDeniedError:
                self.config.unreadable.append(included)
            except NotFoundError:
                continue
            except SystemViewError:
                self.config.notes.append(f"could not read included file {included} ({where})")


def parse_sshd_config(view: SystemView, path: str = MAIN_CONFIG) -> SshdConfig:
    """Parse ``path`` and its includes. Errors reading ``path`` itself propagate."""
    parser = _Parser(view)
    parser.parse_file(path, None, 0)
    return parser.config


def parse_sshd_t(output: str) -> dict[str, str]:
    """Parse ``sshd -T`` output (``keyword value`` per line, already lower-case keywords)."""
    values: dict[str, str] = {}
    for line in output.splitlines():
        keyword, _, value = line.strip().partition(" ")
        if keyword and value and keyword not in values:
            values[keyword.lower()] = value.strip().lower()
    return values
