"""Tests for the release helper scripts (run from backend/: uv run pytest ../packaging/tests)."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType

PACKAGING = Path(__file__).resolve().parent.parent


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, PACKAGING / f"{name}.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


release_notes = _load("release_notes")


def test_commits_are_grouped_by_conventional_type() -> None:
    grouped = release_notes.group(
        [
            "feat(desktop): garden screen",
            "fix: redaction of NOPASSWD lines",
            "feat!: new result format",
            "docs: threat model",
            "Merge-like subject without a type",
            "style: unknown type",
        ]
    )
    assert grouped["Features"] == ["**desktop:** garden screen", "**Breaking:** new result format"]
    assert grouped["Fixes"] == ["redaction of NOPASSWD lines"]
    assert grouped["Documentation"] == ["threat model"]
    assert grouped["Other"] == ["Merge-like subject without a type", "unknown type"]


def test_notes_state_the_glibc_baseline_disclaimer_and_verification() -> None:
    notes = release_notes.render("v0.1.0", {"Fixes": ["a fix"]}, "2.35")
    assert notes.startswith("# HardenGarden v0.1.0")
    assert "glibc 2.35" in notes
    assert "not a certified compliance scanner" in notes
    assert "## Fixes\n\n- a fix" in notes
    assert "release.yml@refs/tags/v0.1.0" in notes
    assert notes.index("## Fixes") < notes.index("## Verify this release")


def _check_versions(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # our own script, fixed arguments
        [sys.executable, str(PACKAGING / "check_versions.py"), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def test_all_version_strings_agree() -> None:
    result = _check_versions()
    assert result.returncode == 0, result.stdout + result.stderr
    version = result.stdout.strip().splitlines()[-1].removeprefix("ok: ")
    assert _check_versions("--tag", f"v{version}").returncode == 0


def test_a_tag_that_does_not_match_the_version_fails() -> None:
    result = _check_versions("--tag", "v999.0.0")
    assert result.returncode != 0
    assert "does not match" in result.stderr
