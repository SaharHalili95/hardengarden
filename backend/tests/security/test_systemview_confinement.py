"""R6: SystemView never reads outside its root and never reads unbounded data."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from hardengarden.core.systemview import (
    DEFAULT_MAX_BYTES,
    FileKind,
    FileTooLargeError,
    NotFoundError,
    NotRegularFileError,
    PathEscapeError,
    SymlinkLoopError,
    SystemView,
)


@pytest.fixture
def tree(tmp_path: Path) -> tuple[Path, Path]:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret").write_text("host secret")
    root = tmp_path / "root"
    (root / "etc").mkdir(parents=True)
    (root / "etc" / "secret").write_text("fixture secret")
    (root / "etc" / "hosts").write_text("127.0.0.1 localhost\n")
    return root, outside


def test_relative_symlink_escape_is_refused(tree: tuple[Path, Path]) -> None:
    root, _ = tree
    (root / "etc" / "evil").symlink_to("../../outside/secret")
    with pytest.raises(PathEscapeError):
        SystemView(root).read_text("/etc/evil")


def test_absolute_symlink_is_rerooted_not_followed_to_host(tree: tuple[Path, Path]) -> None:
    root, outside = tree
    (root / "etc" / "abs").symlink_to(outside / "secret")  # absolute host path
    with pytest.raises(NotFoundError):
        SystemView(root).read_text("/etc/abs")
    (root / "etc" / "abs2").symlink_to("/etc/secret")
    assert SystemView(root).read_text("/etc/abs2") == "fixture secret"


def test_dotdot_in_requested_path_cannot_escape(tree: tuple[Path, Path]) -> None:
    root, _ = tree
    with pytest.raises(PathEscapeError):
        SystemView(root).read_text("/../outside/secret")
    with pytest.raises(PathEscapeError):
        SystemView(root).read_text("/etc/../../outside/secret")


def test_symlinked_directory_escape_is_refused(tree: tuple[Path, Path]) -> None:
    root, _ = tree
    (root / "link").symlink_to("../outside")
    with pytest.raises(PathEscapeError):
        SystemView(root).read_text("/link/secret")
    with pytest.raises(PathEscapeError):
        SystemView(root).list_dir("/link")


def test_symlink_loop_is_detected(tree: tuple[Path, Path]) -> None:
    root, _ = tree
    (root / "a").symlink_to("/b")
    (root / "b").symlink_to("/a")
    with pytest.raises(SymlinkLoopError):
        SystemView(root).read_text("/a")


def test_relative_paths_are_rejected(tree: tuple[Path, Path]) -> None:
    root, _ = tree
    with pytest.raises(ValueError, match="absolute"):
        SystemView(root).read_text("etc/hosts")


def test_size_limit_is_enforced(tree: tuple[Path, Path]) -> None:
    root, _ = tree
    (root / "big").write_bytes(b"x" * (DEFAULT_MAX_BYTES + 1))
    (root / "exact").write_bytes(b"x" * DEFAULT_MAX_BYTES)
    view = SystemView(root)
    with pytest.raises(FileTooLargeError):
        view.read_bytes("/big")
    assert len(view.read_bytes("/exact")) == DEFAULT_MAX_BYTES


def test_size_limit_applies_to_files_reporting_zero_size(tree: tuple[Path, Path]) -> None:
    root, _ = tree
    (root / "small").write_bytes(b"x" * 20)
    view = SystemView(root, max_bytes=10)
    with pytest.raises(FileTooLargeError):
        view.read_bytes("/small")


def test_max_bytes_cannot_exceed_one_mebibyte(tree: tuple[Path, Path]) -> None:
    root, _ = tree
    with pytest.raises(ValueError, match="max_bytes"):
        SystemView(root, max_bytes=DEFAULT_MAX_BYTES + 1)


def test_fifo_and_directories_are_not_read(tree: tuple[Path, Path]) -> None:
    root, _ = tree
    os.mkfifo(root / "fifo")
    view = SystemView(root)
    with pytest.raises(NotRegularFileError):
        view.read_bytes("/fifo")  # O_NONBLOCK: must not hang
    with pytest.raises(NotRegularFileError):
        view.read_bytes("/etc")


def test_stat_reports_symlink_without_following(tree: tuple[Path, Path]) -> None:
    root, _ = tree
    (root / "etc" / "lnk").symlink_to("hosts")
    info = SystemView(root).stat("/etc/lnk")
    assert info.kind is FileKind.SYMLINK
    assert SystemView(root).read_text("/etc/lnk").startswith("127.0.0.1")


def test_root_must_be_a_directory(tmp_path: Path) -> None:
    with pytest.raises(NotFoundError):
        SystemView(tmp_path / "missing")
