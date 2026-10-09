"""Per-user application directories (never inside the scanned system's config)."""

from __future__ import annotations

import os
from pathlib import Path


def _base(env: str, fallback: str) -> Path:
    value = os.environ.get(env, "")
    base = Path(value) if value and Path(value).is_absolute() else Path.home() / fallback
    return base / "hardengarden"


def private_dir(path: Path) -> Path:
    """Create ``path`` (and parents) and make it accessible to the owner only (0700)."""
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.chmod(0o700)
    return path


def data_dir() -> Path:
    """Vector store, ingested man pages, settings: ``$XDG_DATA_HOME/hardengarden``."""
    return _base("XDG_DATA_HOME", ".local/share")


def cache_dir() -> Path:
    """LLM explanation cache: ``$XDG_CACHE_HOME/hardengarden``."""
    return _base("XDG_CACHE_HOME", ".cache")
