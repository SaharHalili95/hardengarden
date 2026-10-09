"""SystemView behaviour beyond confinement: errors, glob, walk limits."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from hardengarden.core.systemview import (
    AccessDeniedError,
    FileKind,
    NotFoundError,
    NotRegularFileError,
    PathEscapeError,
    SystemView,
)


@pytest.fixture
def view(tmp_path: Path) -> SystemView:
    root = tmp_path / "root"
    for rel in ("etc/ssh/a.conf", "etc/ssh/b.conf", "etc/ssh/.hidden.conf", "etc/x/y/z.conf"):
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(rel)
    return SystemView(root)


def test_glob(view: SystemView) -> None:
    assert view.glob("/etc/ssh/*.conf") == ["/etc/ssh/a.conf", "/etc/ssh/b.conf"]
    assert view.glob("/etc/*/y/*.conf") == ["/etc/x/y/z.conf"]
    assert view.glob("/etc/ssh/[a]*") == ["/etc/ssh/a.conf"]
    assert view.glob("/etc/ssh/a.conf") == ["/etc/ssh/a.conf"]
    assert view.glob("/nope/*.conf") == []
    assert view.glob("/etc/ssh/missing.conf") == []


def test_walk_limits(view: SystemView) -> None:
    full = view.walk("/etc")
    assert not full.truncated
    assert {e.path for e in full.entries} >= {"/etc/ssh/a.conf", "/etc/x/y/z.conf"}
    capped = view.walk("/etc", max_entries=2)
    assert capped.truncated
    assert len(capped.entries) == 2
    shallow = view.walk("/etc", max_depth=1)
    assert "/etc/x/y" not in {e.path for e in shallow.entries}


def test_walk_of_missing_dir_is_empty(view: SystemView) -> None:
    assert view.walk("/missing").entries == ()


def test_list_dir_errors(view: SystemView) -> None:
    with pytest.raises(NotFoundError):
        view.list_dir("/missing")
    with pytest.raises(NotRegularFileError):
        view.list_dir("/etc/ssh/a.conf")


def test_permission_errors_are_mapped(view: SystemView, monkeypatch: pytest.MonkeyPatch) -> None:
    def deny(*_a: Any, **_k: Any) -> Any:
        raise PermissionError

    monkeypatch.setattr(os, "scandir", deny)
    with pytest.raises(AccessDeniedError):
        view.list_dir("/etc")
    assert view.walk("/etc").unreadable_dirs == ("/etc",)
    monkeypatch.setattr(os, "open", deny)
    with pytest.raises(AccessDeniedError):
        view.read_bytes("/etc/ssh/a.conf")


def test_lstat_permission_errors(view: SystemView, monkeypatch: pytest.MonkeyPatch) -> None:
    real_lstat = os.lstat

    def deny_ssh(path: Any, *args: Any, **kwargs: Any) -> os.stat_result:
        if str(path).endswith("/etc/ssh") or str(path).endswith("a.conf"):
            raise PermissionError
        return real_lstat(path, *args, **kwargs)

    monkeypatch.setattr(os, "lstat", deny_ssh)
    with pytest.raises(AccessDeniedError):
        view.read_text("/etc/ssh/a.conf")
    with pytest.raises(AccessDeniedError):
        view.stat("/etc/x/../ssh")


def test_stat_and_exists(view: SystemView) -> None:
    info = view.stat("/etc/ssh")
    assert info.kind is FileKind.DIR
    assert info.path == "/etc/ssh"
    assert view.exists("/etc/ssh/a.conf")
    assert not view.exists("/etc/ssh/zzz")
    with pytest.raises(NotFoundError):
        view.stat("/etc/ssh/zzz")
    assert view.is_file("/etc/ssh/a.conf")
    assert not view.is_file("/etc/ssh")
    assert not view.is_file("/../escape")


def test_read_missing_file(view: SystemView) -> None:
    with pytest.raises(NotFoundError):
        view.read_text("/etc/nothing")


def test_other_kinds_are_reported(view: SystemView) -> None:
    os.mkfifo(view.root / "etc" / "fifo")
    assert view.stat("/etc/fifo").kind is FileKind.OTHER


def test_opened_file_outside_root_is_refused(
    view: SystemView, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_readlink = Path.readlink

    def swapped(self: Path) -> Path:
        if str(self).startswith("/proc/self/fd/"):
            return Path("/elsewhere/file")
        return real_readlink(self)

    monkeypatch.setattr(Path, "readlink", swapped)
    with pytest.raises(PathEscapeError):
        view.read_text("/etc/ssh/a.conf")


def test_host_root_view() -> None:
    host = SystemView("/")
    assert host.is_host_root
    assert host.root == Path("/")
    assert host.read_text("/proc/self/stat")  # zero-size procfs file is read correctly
