"""The only place in HardenGarden that starts processes (R4).

Callers cannot pass arguments. They pick a :class:`Command` from a fixed enum; the argv
for each command is a constant below. Binaries are resolved from a fixed list of absolute
paths and must be root-owned and not group/world-writable. Processes run with
``shell=False``, an empty stdin, a minimal environment, a hard timeout (≤ 10 s) and a cap
on captured output.
"""

from __future__ import annotations

import os
import stat
import subprocess  # nosec B404  # justification: sole, allowlisted process launcher (R4)
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol

MAX_TIMEOUT_S = 10.0
MAX_OUTPUT_BYTES = 1024 * 1024
_SAFE_ENV = {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LC_ALL": "C", "LANG": "C"}


class Command(StrEnum):
    SSHD_EFFECTIVE_CONFIG = "sshd_effective_config"
    UFW_STATUS = "ufw_status"
    NFT_RULESET = "nft_ruleset"


@dataclass(frozen=True, slots=True)
class CommandSpec:
    candidates: tuple[str, ...]  # absolute paths, first match wins
    args: tuple[str, ...]  # fixed arguments, never user-controlled


ALLOWLIST: dict[Command, CommandSpec] = {
    Command.SSHD_EFFECTIVE_CONFIG: CommandSpec(("/usr/sbin/sshd", "/sbin/sshd"), ("-T",)),
    Command.UFW_STATUS: CommandSpec(("/usr/sbin/ufw", "/sbin/ufw"), ("status",)),
    Command.NFT_RULESET: CommandSpec(("/usr/sbin/nft", "/sbin/nft"), ("list", "ruleset")),
}


class CommandNotAllowedError(Exception):
    """Raised for anything that is not an allowlisted command."""


@dataclass(frozen=True, slots=True)
class CommandResult:
    returncode: int | None  # None when the process timed out
    stdout: str
    stderr: str
    timed_out: bool

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out


class Runner(Protocol):
    """What checks depend on. Returns ``None`` when the command is unavailable."""

    def run(self, command: Command) -> CommandResult | None: ...


class NullRunner:
    """Runner used when commands must not run (e.g. scanning a non-host ``--root``)."""

    def run(self, command: Command) -> CommandResult | None:
        _ = command
        return None


def _trusted_binary(path: str) -> bool:
    try:
        st = Path(path).stat()
    except OSError:
        return False
    if not stat.S_ISREG(st.st_mode) or not st.st_mode & stat.S_IXUSR:
        return False
    if st.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        return False
    return st.st_uid == 0


class SubprocessRunner:
    """Real runner for host scans. ``specs`` is injectable for tests only."""

    def __init__(
        self,
        *,
        timeout_s: float = MAX_TIMEOUT_S,
        specs: dict[Command, CommandSpec] | None = None,
        require_root_owned: bool = True,
    ) -> None:
        if not 0 < timeout_s <= MAX_TIMEOUT_S:
            msg = f"timeout must be in (0, {MAX_TIMEOUT_S}] seconds"
            raise ValueError(msg)
        self._timeout_s = timeout_s
        self._specs = dict(ALLOWLIST if specs is None else specs)
        self._require_root_owned = require_root_owned
        for spec in self._specs.values():
            if not spec.candidates or not all(Path(c).is_absolute() for c in spec.candidates):
                msg = "allowlisted binaries must be absolute paths"
                raise CommandNotAllowedError(msg)

    def resolve(self, command: Command) -> str | None:
        spec = self._specs.get(command)
        if spec is None:
            msg = f"command not allowlisted: {command!r}"
            raise CommandNotAllowedError(msg)
        for candidate in spec.candidates:
            if self._require_root_owned:
                if _trusted_binary(candidate):
                    return candidate
            elif Path(candidate).is_file() and os.access(candidate, os.X_OK):
                return candidate
        return None

    def run(self, command: Command) -> CommandResult | None:
        binary = self.resolve(command)  # raises CommandNotAllowedError if not allowlisted
        if binary is None:
            return None
        argv = [binary, *self._specs[command].args]
        try:
            proc = subprocess.run(  # noqa: S603  # nosec B603  # justification: fixed argv, shell=False
                argv,
                shell=False,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                timeout=self._timeout_s,
                env=_SAFE_ENV,
                check=False,
                close_fds=True,
            )
        except subprocess.TimeoutExpired:
            return CommandResult(returncode=None, stdout="", stderr="", timed_out=True)
        except OSError:
            return None
        return CommandResult(
            returncode=proc.returncode,
            stdout=proc.stdout[:MAX_OUTPUT_BYTES].decode("utf-8", errors="replace"),
            stderr=proc.stderr[:MAX_OUTPUT_BYTES].decode("utf-8", errors="replace"),
            timed_out=False,
        )
