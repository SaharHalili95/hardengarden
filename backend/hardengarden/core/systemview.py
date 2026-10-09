"""Read-only, root-confined access to the scanned filesystem (R1, R6).

Every file access made by a check goes through :class:`SystemView`. It guarantees:

* **Read-only.** Files are opened with ``O_RDONLY``; nothing in this module writes.
* **Confinement.** Paths are resolved component by component *inside* ``root``.
  Absolute symlink targets are re-rooted (chroot semantics); a ``..`` that would climb
  above ``root`` raises :class:`PathEscapeError`. The final component is opened with
  ``O_NOFOLLOW`` and the opened descriptor is re-checked against ``root``.
* **Bounded.** Reads are capped (default 1 MiB, R6); directory walks are capped too.
"""

from __future__ import annotations

import fnmatch
import os
import stat
from collections import deque
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path, PurePosixPath

DEFAULT_MAX_BYTES = 1024 * 1024
MAX_SYMLINK_HOPS = 40
_OPEN_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK | os.O_NOCTTY


class SystemViewError(Exception):
    """Base class for every error raised by :class:`SystemView`."""


class NotFoundError(SystemViewError):
    pass


class AccessDeniedError(SystemViewError):
    pass


class PathEscapeError(SystemViewError):
    pass


class SymlinkLoopError(SystemViewError):
    pass


class FileTooLargeError(SystemViewError):
    pass


class NotRegularFileError(SystemViewError):
    pass


class FileKind(StrEnum):
    FILE = "file"
    DIR = "dir"
    SYMLINK = "symlink"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class FileInfo:
    path: str
    kind: FileKind
    mode: int  # permission bits only (st_mode & 0o7777)
    uid: int
    gid: int
    size: int


@dataclass(frozen=True, slots=True)
class WalkResult:
    entries: tuple[FileInfo, ...]
    unreadable_dirs: tuple[str, ...]
    truncated: bool


def _kind(st_mode: int) -> FileKind:
    if stat.S_ISLNK(st_mode):
        return FileKind.SYMLINK
    if stat.S_ISDIR(st_mode):
        return FileKind.DIR
    if stat.S_ISREG(st_mode):
        return FileKind.FILE
    return FileKind.OTHER


def _normalize(vpath: str) -> PurePosixPath:
    path = PurePosixPath(vpath)
    if not path.is_absolute():
        msg = f"SystemView paths must be absolute: {vpath!r}"
        raise ValueError(msg)
    return path


class SystemView:
    """Read-only view of a filesystem tree rooted at ``root`` (default ``/``)."""

    def __init__(self, root: str | Path = "/", *, max_bytes: int = DEFAULT_MAX_BYTES) -> None:
        if max_bytes <= 0 or max_bytes > DEFAULT_MAX_BYTES:
            msg = f"max_bytes must be in 1..{DEFAULT_MAX_BYTES}"
            raise ValueError(msg)
        resolved = Path(os.path.realpath(root))
        if not resolved.is_dir():
            msg = f"scan root is not a directory: {root}"
            raise NotFoundError(msg)
        self._root = resolved
        self._max_bytes = max_bytes

    @property
    def root(self) -> Path:
        return self._root

    @property
    def is_host_root(self) -> bool:
        return self._root == Path("/")

    # ------------------------------------------------------------------ resolution
    def _resolve(self, vpath: str, *, follow_final: bool) -> Path:
        """Map a virtual absolute path to a host path inside ``root``."""
        todo: deque[str] = deque(_normalize(vpath).parts[1:])
        resolved: list[str] = []
        hops = 0
        while todo:
            name = todo.popleft()
            if name in {"", "."}:
                continue
            if name == "..":
                if not resolved:
                    msg = f"path escapes the scan root: {vpath!r}"
                    raise PathEscapeError(msg)
                resolved.pop()
                continue
            candidate = self._root.joinpath(*resolved, name)
            is_last = not todo
            try:
                st = os.lstat(candidate)
            except FileNotFoundError:
                return self._root.joinpath(*resolved, name, *todo)
            except PermissionError as exc:
                raise AccessDeniedError(vpath) from exc
            if stat.S_ISLNK(st.st_mode) and (follow_final or not is_last):
                hops += 1
                if hops > MAX_SYMLINK_HOPS:
                    raise SymlinkLoopError(vpath)
                target = PurePosixPath(candidate.readlink())
                parts = list(target.parts)
                if target.is_absolute():
                    resolved = []
                    parts = parts[1:]
                todo.extendleft(reversed(parts))
                continue
            resolved.append(name)
        return self._root.joinpath(*resolved)

    def _assert_inside(self, fd: int) -> None:
        if self.is_host_root:
            return
        real = Path(f"/proc/self/fd/{fd}").readlink()
        if real != self._root and self._root not in real.parents:
            msg = "opened file is outside the scan root"
            raise PathEscapeError(msg)

    # ------------------------------------------------------------------ reads
    def read_bytes(self, vpath: str) -> bytes:
        real = self._resolve(vpath, follow_final=True)
        try:
            fd = os.open(real, _OPEN_FLAGS)
        except FileNotFoundError as exc:
            raise NotFoundError(vpath) from exc
        except PermissionError as exc:
            raise AccessDeniedError(vpath) from exc
        except OSError as exc:  # ELOOP from O_NOFOLLOW, ENXIO from sockets, ...
            raise NotRegularFileError(vpath) from exc
        try:
            self._assert_inside(fd)
            st = os.fstat(fd)
            if not stat.S_ISREG(st.st_mode):
                raise NotRegularFileError(vpath)
            if st.st_size > self._max_bytes:
                raise FileTooLargeError(vpath)
            chunks: list[bytes] = []
            remaining = self._max_bytes + 1
            while remaining > 0:
                chunk = os.read(fd, min(remaining, 65536))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            data = b"".join(chunks)
            if len(data) > self._max_bytes:
                raise FileTooLargeError(vpath)
            return data
        finally:
            os.close(fd)

    def read_text(self, vpath: str) -> str:
        return self.read_bytes(vpath).decode("utf-8", errors="replace")

    # ------------------------------------------------------------------ metadata
    def stat(self, vpath: str) -> FileInfo:
        """``lstat`` semantics: a symlink at the final component is reported, not followed."""
        real = self._resolve(vpath, follow_final=False)
        try:
            st = os.lstat(real)
        except FileNotFoundError as exc:
            raise NotFoundError(vpath) from exc
        except PermissionError as exc:
            raise AccessDeniedError(vpath) from exc
        return FileInfo(
            path=str(_normalize(vpath)),
            kind=_kind(st.st_mode),
            mode=stat.S_IMODE(st.st_mode),
            uid=st.st_uid,
            gid=st.st_gid,
            size=st.st_size,
        )

    def exists(self, vpath: str) -> bool:
        try:
            self.stat(vpath)
        except NotFoundError:
            return False
        return True

    def is_file(self, vpath: str) -> bool:
        try:
            real = self._resolve(vpath, follow_final=True)
            return stat.S_ISREG(real.stat().st_mode)
        except (OSError, SystemViewError):
            return False

    def list_dir(self, vpath: str) -> list[str]:
        real = self._resolve(vpath, follow_final=True)
        try:
            with os.scandir(real) as it:
                return sorted(entry.name for entry in it)
        except FileNotFoundError as exc:
            raise NotFoundError(vpath) from exc
        except PermissionError as exc:
            raise AccessDeniedError(vpath) from exc
        except NotADirectoryError as exc:
            raise NotRegularFileError(vpath) from exc

    def glob(self, pattern: str) -> list[str]:
        """Expand a shell glob (``*``, ``?``, ``[...]``) inside the root. Sorted, no dotfiles."""
        parts = _normalize(pattern).parts[1:]
        current = ["/"]
        for part in parts:
            nxt: list[str] = []
            for base in current:
                if any(ch in part for ch in "*?["):
                    try:
                        names = self.list_dir(base)
                    except SystemViewError:
                        continue
                    nxt.extend(
                        str(PurePosixPath(base) / n)
                        for n in names
                        if fnmatch.fnmatchcase(n, part) and not n.startswith(".")
                    )
                else:
                    candidate = str(PurePosixPath(base) / part)
                    if self.exists(candidate):
                        nxt.append(candidate)
            current = nxt
        return sorted(current)

    def walk(self, vpath: str, *, max_entries: int = 50_000, max_depth: int = 16) -> WalkResult:
        """Breadth-first walk that never follows symlinks."""
        entries: list[FileInfo] = []
        unreadable: list[str] = []
        queue: deque[tuple[str, int]] = deque([(str(_normalize(vpath)), 0)])
        truncated = False
        while queue:
            directory, depth = queue.popleft()
            try:
                names = self.list_dir(directory)
            except AccessDeniedError:
                unreadable.append(directory)
                continue
            except SystemViewError:
                continue
            for name in names:
                if len(entries) >= max_entries:
                    truncated = True
                    queue.clear()
                    break
                child = str(PurePosixPath(directory) / name)
                try:
                    info = self.stat(child)
                except SystemViewError:
                    continue
                entries.append(info)
                if info.kind is FileKind.DIR and depth + 1 < max_depth:
                    queue.append((child, depth + 1))
        return WalkResult(tuple(entries), tuple(unreadable), truncated)
