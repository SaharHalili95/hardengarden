#!/usr/bin/env python3
"""Fails unless every version string in the repository agrees (and matches a release tag).

    check_versions.py [--tag vX.Y.Z]

Sources: the Python package, the desktop UI, the Rust shell and the Tauri bundle config.
Standard library only.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def versions() -> dict[str, str]:
    init = (ROOT / "backend/hardengarden/__init__.py").read_text(encoding="utf-8")
    match = re.search(r'^__version__ = "([^"]+)"$', init, re.MULTILINE)
    if match is None:
        sys.exit("backend/hardengarden/__init__.py has no __version__")
    cargo = tomllib.loads((ROOT / "desktop/src-tauri/Cargo.toml").read_text(encoding="utf-8"))
    return {
        "backend/hardengarden/__init__.py": match.group(1),
        "desktop/package.json": json.loads((ROOT / "desktop/package.json").read_text())["version"],
        "desktop/src-tauri/Cargo.toml": cargo["package"]["version"],
        "desktop/src-tauri/tauri.conf.json": json.loads(
            (ROOT / "desktop/src-tauri/tauri.conf.json").read_text()
        )["version"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Check that all version strings agree.")
    parser.add_argument("--tag", help="release tag that must match, e.g. v0.1.0")
    args = parser.parse_args()
    found = versions()
    for source, version in found.items():
        print(f"{version:>12}  {source}")
    if len(set(found.values())) != 1:
        sys.exit("error: version strings disagree")
    version = next(iter(found.values()))
    if args.tag is not None and args.tag != f"v{version}":
        sys.exit(f"error: tag {args.tag} does not match version {version}")
    print(f"ok: {version}")


if __name__ == "__main__":
    main()
