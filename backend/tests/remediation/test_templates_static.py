"""Static checks for remediation templates: shellcheck, safety contract, snapshots (R12)."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from hardengarden import __version__
from hardengarden.checks import ALL_CHECKS
from hardengarden.core.models import CheckMeta
from hardengarden.remediation import TemplateNotFoundError, render, template_source

SNAPSHOTS = Path(__file__).parent / "snapshots"
TEMPLATE_DIR = Path(__file__).resolve().parents[2] / "hardengarden" / "remediation" / "templates"
WITH_TEMPLATE = [c.meta for c in ALL_CHECKS if c.meta.remediation_template]
# Checks that can FAIL need a template; HG-NET-001 is inventory only (WARN), guidance only.
FAILABLE = {c.meta.id for c in ALL_CHECKS} - {"HG-NET-001"}


def test_every_failable_check_has_exactly_one_template() -> None:
    assert {m.id for m in WITH_TEMPLATE} == FAILABLE
    files = sorted(p.name for p in TEMPLATE_DIR.glob("*.sh"))
    assert files == sorted(m.remediation_template or "" for m in WITH_TEMPLATE)
    for meta in WITH_TEMPLATE:
        assert meta.remediation_template == f"{meta.id.lower()}.sh"


def test_check_without_template_renders_nothing() -> None:
    net = next(c.meta for c in ALL_CHECKS if c.meta.id == "HG-NET-001")
    assert render(net) is None


@pytest.mark.parametrize("meta", WITH_TEMPLATE, ids=lambda m: m.id)
def test_safety_contract(meta: CheckMeta) -> None:
    script = render(meta)
    assert script is not None
    assert script.startswith("#!/usr/bin/env bash\n")
    assert "set -euo pipefail" in script
    assert 'APPLY="${HG_APPLY:-0}"' in script, "dry run must be the default"
    assert '[ "$(id -u)" -eq 0 ]' in script
    assert "REVIEW BEFORE RUNNING" in script
    assert "DRY RUN" in script
    assert not re.search(r"\brm\s+-[a-z]*r", script), "no recursive deletes"
    assert not re.search(r"(curl|wget)\b", script), "no downloads"
    assert "eval " not in script


@pytest.mark.parametrize("meta", WITH_TEMPLATE, ids=lambda m: m.id)
def test_shellcheck_passes(meta: CheckMeta, tmp_path: Path) -> None:
    shellcheck = shutil.which("shellcheck")
    assert shellcheck is not None, "shellcheck must be installed to run the test suite"
    script = render(meta)
    assert script is not None
    target = tmp_path / "fix.sh"
    target.write_text(script)
    argv = [shellcheck, "-x", str(target)]
    result = subprocess.run(argv, capture_output=True, text=True, check=False)  # noqa: S603  # justification: fixed argv

    assert result.returncode == 0, result.stdout


@pytest.mark.parametrize("meta", WITH_TEMPLATE, ids=lambda m: m.id)
def test_rendered_template_matches_snapshot(meta: CheckMeta) -> None:
    script = render(meta)
    assert script is not None
    normalized = script.replace(__version__, "<version>")
    snapshot = SNAPSHOTS / f"{meta.id}.sh.snap"
    if os.environ.get("HG_UPDATE_SNAPSHOTS") == "1":
        SNAPSHOTS.mkdir(exist_ok=True)
        snapshot.write_text(normalized)
    assert snapshot.read_text() == normalized, (
        "template changed: review it, then HG_UPDATE_SNAPSHOTS=1"
    )


@pytest.mark.parametrize("name", ["../etc/passwd", "x.py", "missing.sh"])
def test_template_lookup_rejects_bad_names(name: str) -> None:
    with pytest.raises(TemplateNotFoundError):
        template_source(name)
