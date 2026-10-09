"""R1 guarantee: a full scan performs zero write or modify operations.

Uses CPython audit hooks (PEP 578), which fire for every file open, chmod/chown, rename,
unlink, mkdir, process spawn and so on, no matter which library performs them. The hook
records events only while a scan runs.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest

from hardengarden.checks import ALL_CHECKS
from hardengarden.core.engine import run_scan
from hardengarden.core.runner import ALLOWLIST, SubprocessRunner
from hardengarden.core.systemview import SystemView
from hgtest import SCENARIOS, FakeRunner, load_scenario, platform

_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
_MODIFY_EVENTS = {
    "os.remove", "os.unlink", "os.rename", "os.replace", "os.rmdir", "os.mkdir", "os.makedirs",
    "os.chmod", "os.lchmod", "os.chown", "os.lchown", "os.chflags", "os.lchflags", "os.link",
    "os.symlink", "os.truncate", "os.utime", "os.setxattr", "os.removexattr", "os.mkfifo",
    "os.mknod", "shutil.rmtree", "shutil.move", "shutil.copyfile", "shutil.copytree",
    "os.kill", "os.killpg", "socket.connect", "socket.bind", "socket.sendto",
}  # fmt: skip
_SPAWN_EVENTS = {
    "subprocess.Popen",
    "os.system",
    "os.exec",
    "os.posix_spawn",
    "os.spawn",
    "os.fork",
}

_recording = False
_events: list[tuple[str, tuple[Any, ...]]] = []


def _hook(event: str, args: tuple[Any, ...]) -> None:
    if _recording and (event == "open" or event in _MODIFY_EVENTS or event in _SPAWN_EVENTS):
        _events.append((event, args))


sys.addaudithook(_hook)


@contextmanager
def recording() -> Iterator[list[tuple[str, tuple[Any, ...]]]]:
    global _recording  # noqa: PLW0603  # justification: audit hooks cannot be removed; a flag gates them
    _events.clear()
    _recording = True
    try:
        yield _events
    finally:
        _recording = False


def _is_write(event: str, args: tuple[Any, ...]) -> bool:
    if event in _MODIFY_EVENTS:
        return True
    if event == "open":
        path, mode, flags = args
        if path == os.devnull:  # subprocess opens /dev/null O_RDWR for stdin=DEVNULL
            return False
        if isinstance(mode, str) and any(ch in mode for ch in "wax+"):
            return True
        return isinstance(flags, int) and bool(flags & _WRITE_FLAGS)
    return False


def _allowlisted_spawn(args: tuple[Any, ...]) -> bool:
    binaries = {c for spec in ALLOWLIST.values() for c in spec.candidates}
    executable = str(args[0])
    return executable in binaries


@pytest.fixture(autouse=True)
def _warm_up() -> None:
    # Import every lazily imported module before recording, so bytecode caching is not counted.
    run_scan(load_scenario("hardened"), ALL_CHECKS, runner=FakeRunner())


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_fixture_scan_never_writes(scenario: str) -> None:
    view = load_scenario(scenario, host_root=True)
    with recording() as events:
        run_scan(view, ALL_CHECKS, runner=FakeRunner(), platform=platform(is_root=True))
    writes = [e for e in events if _is_write(*e)]
    spawns = [e for e in events if e[0] in _SPAWN_EVENTS]
    assert writes == []
    assert spawns == []
    assert any(e[0] == "open" for e in events), "the hook must observe the scan's reads"


def test_live_host_scan_never_writes_and_spawns_only_allowlisted_binaries() -> None:
    view = SystemView("/")
    with recording() as events:
        run_scan(view, ALL_CHECKS, runner=SubprocessRunner())
    writes = [e for e in events if _is_write(*e)]
    bad_spawns = [e for e in events if e[0] == "subprocess.Popen" and not _allowlisted_spawn(e[1])]
    assert writes == []
    assert bad_spawns == []


def test_detector_catches_writes(tmp_path: Any) -> None:
    target = tmp_path / "x"
    with recording() as events:
        target.write_text("data")
        os.chmod(target, 0o600)  # noqa: PTH101  # justification: exercising the os-level audit event
    assert any(_is_write(*e) for e in events)
    assert any(e[0] == "os.chmod" for e in events)
