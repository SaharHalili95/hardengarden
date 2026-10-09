"""Shared test helpers: fixture filesystems with deterministic ownership, and a fake runner."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from hardengarden.core.check import CheckContext
from hardengarden.core.models import Platform
from hardengarden.core.runner import Command, CommandResult
from hardengarden.core.systemview import AccessDeniedError, FileInfo, FileKind, SystemView

FIXTURES = Path(__file__).parent / "fixtures" / "systems"
SCENARIOS = ("hardened", "default_ubuntu_2404", "misconfigured", "edge_cases")


class FixtureSystemView(SystemView):
    """A SystemView whose ownership, modes and readability come from ``meta.json``.

    Git cannot store owners or most mode bits, so fixtures declare them. Defaults are
    root:root, 0644 for files and 0755 for directories. Production code never sees this
    class; it only changes what ``stat`` reports and which paths are unreadable.
    """

    def __init__(
        self, root: Path, meta: dict[str, dict[str, Any]], *, host_root: bool = False
    ) -> None:
        super().__init__(root)
        self._meta = meta
        self._host_root = host_root

    @property
    def is_host_root(self) -> bool:
        return self._host_root

    def _unreadable(self, vpath: str) -> bool:
        return bool(self._meta.get(str(PurePosixPath(vpath)), {}).get("unreadable"))

    def stat(self, vpath: str) -> FileInfo:
        info = super().stat(vpath)
        override = self._meta.get(info.path, {})
        default_mode = {FileKind.DIR: 0o755, FileKind.SYMLINK: 0o777}.get(info.kind, 0o644)
        return FileInfo(
            path=info.path,
            kind=info.kind,
            mode=int(override["mode"], 8) if "mode" in override else default_mode,
            uid=int(override.get("uid", 0)),
            gid=int(override.get("gid", 0)),
            size=info.size,
        )

    def read_bytes(self, vpath: str) -> bytes:
        if self._unreadable(vpath):
            raise AccessDeniedError(vpath)
        return super().read_bytes(vpath)

    def list_dir(self, vpath: str) -> list[str]:
        if self._unreadable(vpath):
            raise AccessDeniedError(vpath)
        return super().list_dir(vpath)


def load_scenario(name: str, *, host_root: bool = False) -> FixtureSystemView:
    base = FIXTURES / name
    meta = json.loads((base / "meta.json").read_text())
    return FixtureSystemView(base / "root", meta, host_root=host_root)


def make_view(
    tmp_path: Path,
    files: dict[str, str],
    meta: dict[str, dict[str, Any]] | None = None,
    *,
    host_root: bool = False,
) -> FixtureSystemView:
    """Build an ad-hoc fixture tree under ``tmp_path``."""
    root = tmp_path / "root"
    root.mkdir(parents=True, exist_ok=True)
    for vpath, content in files.items():
        target = root / vpath.lstrip("/")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    return FixtureSystemView(root, meta or {}, host_root=host_root)


@dataclass
class FakeRunner:
    """Returns canned results per command and records every call."""

    responses: dict[Command, CommandResult | None] = field(default_factory=dict)
    calls: list[Command] = field(default_factory=list)

    def run(self, command: Command) -> CommandResult | None:
        self.calls.append(command)
        return self.responses.get(command)


def ok(stdout: str) -> CommandResult:
    return CommandResult(returncode=0, stdout=stdout, stderr="", timed_out=False)


def platform(distro: str = "ubuntu", version: str = "24.04", *, is_root: bool = True) -> Platform:
    return Platform(
        distro_id=distro, version_id=version, pretty_name=f"{distro} {version}", is_root=is_root
    )


def ctx(
    view: SystemView, runner: FakeRunner | None = None, *, is_root: bool = True
) -> CheckContext:
    return CheckContext(view=view, runner=runner or FakeRunner(), is_root=is_root)
