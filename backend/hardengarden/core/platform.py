"""Platform detection from ``/etc/os-release`` inside the scan root."""

from __future__ import annotations

import os
import shlex

from hardengarden.core.models import Platform
from hardengarden.core.systemview import SystemView, SystemViewError

_UNKNOWN = "unknown"


def parse_os_release(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        try:
            parts = shlex.split(value, comments=False, posix=True)
        except ValueError:
            continue
        values[key.strip()] = parts[0] if parts else ""
    return values


def detect_platform(view: SystemView, *, is_root: bool | None = None) -> Platform:
    """Detect the distribution. ``is_root`` defaults to the current effective UID."""
    data: dict[str, str] = {}
    for candidate in ("/etc/os-release", "/usr/lib/os-release"):
        try:
            data = parse_os_release(view.read_text(candidate))
            break
        except SystemViewError:
            continue
    return Platform(
        distro_id=(data.get("ID") or _UNKNOWN).lower(),
        version_id=data.get("VERSION_ID") or _UNKNOWN,
        pretty_name=data.get("PRETTY_NAME") or "Unknown Linux",
        is_root=os.geteuid() == 0 if is_root is None else is_root,
    )
