"""CommandRunner (R4): allowlist only, absolute trusted binaries, no shell, hard timeout."""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path
from typing import Any

import pytest

from hardengarden.core.runner import (
    ALLOWLIST,
    MAX_TIMEOUT_S,
    Command,
    CommandNotAllowedError,
    CommandSpec,
    NullRunner,
    SubprocessRunner,
)

ECHO = "/bin/echo" if Path("/bin/echo").exists() else "/usr/bin/echo"
SLEEP = "/bin/sleep" if Path("/bin/sleep").exists() else "/usr/bin/sleep"


def test_allowlist_uses_absolute_paths_and_fixed_args() -> None:
    for spec in ALLOWLIST.values():
        assert all(Path(c).is_absolute() for c in spec.candidates)
        assert isinstance(spec.args, tuple)


def test_rejects_commands_that_are_not_allowlisted() -> None:
    runner = SubprocessRunner(specs={})
    with pytest.raises(CommandNotAllowedError):
        runner.run(Command.UFW_STATUS)


def test_rejects_arbitrary_strings() -> None:
    runner = SubprocessRunner()
    with pytest.raises(CommandNotAllowedError):
        runner.run("rm -rf /")  # type: ignore[arg-type]  # justification: proves untyped callers are refused


def test_relative_binary_paths_are_refused() -> None:
    with pytest.raises(CommandNotAllowedError):
        SubprocessRunner(specs={Command.UFW_STATUS: CommandSpec(("echo",), ())})


def test_timeout_bounds() -> None:
    with pytest.raises(ValueError, match="timeout"):
        SubprocessRunner(timeout_s=MAX_TIMEOUT_S + 1)
    with pytest.raises(ValueError, match="timeout"):
        SubprocessRunner(timeout_s=0)


def test_timeout_is_enforced() -> None:
    runner = SubprocessRunner(
        timeout_s=0.3, specs={Command.UFW_STATUS: CommandSpec((SLEEP,), ("5",))}
    )
    result = runner.run(Command.UFW_STATUS)
    assert result is not None
    assert result.timed_out
    assert not result.ok


def test_never_uses_a_shell() -> None:
    runner = SubprocessRunner(
        specs={Command.UFW_STATUS: CommandSpec((ECHO,), ("$(id)", "`id`", ";", "|"))}
    )
    result = runner.run(Command.UFW_STATUS)
    assert result is not None
    assert result.stdout.strip() == "$(id) `id` ; |"


def test_shell_false_and_safe_env_are_passed(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def fake_run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        seen["argv"], seen["kwargs"] = argv, kwargs
        return subprocess.CompletedProcess(argv, 0, b"Status: active\n", b"")

    monkeypatch.setattr(subprocess, "run", fake_run)
    runner = SubprocessRunner(specs={Command.UFW_STATUS: CommandSpec((ECHO,), ("status",))})
    result = runner.run(Command.UFW_STATUS)
    assert result is not None
    assert result.ok
    assert seen["argv"] == [ECHO, "status"]
    assert seen["kwargs"]["shell"] is False
    assert seen["kwargs"]["stdin"] == subprocess.DEVNULL
    assert seen["kwargs"]["timeout"] <= MAX_TIMEOUT_S
    assert set(seen["kwargs"]["env"]) == {"PATH", "LC_ALL", "LANG"}


def test_untrusted_binaries_are_not_used(tmp_path: Path) -> None:
    fake = tmp_path / "ufw"
    fake.write_text("#!/bin/sh\necho pwned\n")
    fake.chmod(0o777)  # world-writable: never trusted, whoever owns it
    runner = SubprocessRunner(specs={Command.UFW_STATUS: CommandSpec((str(fake),), ())})
    assert runner.resolve(Command.UFW_STATUS) is None
    assert runner.run(Command.UFW_STATUS) is None


def test_non_root_owned_binary_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = tmp_path / "nft"
    fake.write_text("#!/bin/sh\n")
    fake.chmod(0o755)
    real_stat = Path.stat

    def not_root(self: Path, **kwargs: Any) -> os.stat_result:
        st = real_stat(self, **kwargs)
        if self == fake:
            return os.stat_result(
                (st.st_mode, st.st_ino, st.st_dev, st.st_nlink, 1000, 1000, *st[6:10])
            )
        return st

    monkeypatch.setattr(Path, "stat", not_root)
    runner = SubprocessRunner(specs={Command.NFT_RULESET: CommandSpec((str(fake),), ())})
    assert runner.resolve(Command.NFT_RULESET) is None


def test_missing_binary_returns_none() -> None:
    runner = SubprocessRunner(specs={Command.NFT_RULESET: CommandSpec(("/nonexistent/nft",), ())})
    assert runner.run(Command.NFT_RULESET) is None


def test_relaxed_ownership_mode_for_tests_only() -> None:
    runner = SubprocessRunner(
        specs={Command.NFT_RULESET: CommandSpec((ECHO,), ("x",))}, require_root_owned=False
    )
    assert runner.resolve(Command.NFT_RULESET) == ECHO


def test_os_error_during_spawn_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_a: Any, **_k: Any) -> None:
        raise OSError("exec format error")

    monkeypatch.setattr(subprocess, "run", boom)
    runner = SubprocessRunner(specs={Command.UFW_STATUS: CommandSpec((ECHO,), ())})
    assert runner.run(Command.UFW_STATUS) is None


def test_output_is_capped(monkeypatch: pytest.MonkeyPatch) -> None:
    def big(argv: list[str], **_k: Any) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(argv, 0, b"a" * (2 * 1024 * 1024), b"")

    monkeypatch.setattr(subprocess, "run", big)
    runner = SubprocessRunner(specs={Command.UFW_STATUS: CommandSpec((ECHO,), ())})
    result = runner.run(Command.UFW_STATUS)
    assert result is not None
    assert len(result.stdout) == 1024 * 1024


def test_null_runner_never_runs() -> None:
    assert NullRunner().run(Command.SSHD_EFFECTIVE_CONFIG) is None


def test_binaries_are_regular_executables() -> None:
    mode = Path(ECHO).stat().st_mode
    assert stat.S_ISREG(mode)
