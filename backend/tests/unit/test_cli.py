"""CLI behaviour and the generated docs/CHECKS.md (Phase 1)."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from hardengarden import __version__
from hardengarden.checks import ALL_CHECKS
from hardengarden.cli import app, render_checks_markdown
from hgtest import FIXTURES

runner = CliRunner()
REPO = Path(__file__).resolve().parents[3]


def test_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.stdout.strip() == f"hardengarden {__version__}"


def test_scan_json_against_fixture_root() -> None:
    root = FIXTURES / "misconfigured" / "root"
    result = runner.invoke(app, ["scan", "--json", "--root", str(root)])
    assert result.exit_code == 0
    report = json.loads(result.stdout)
    assert report["scanned_root"] == str(root.resolve())
    assert len(report["results"]) == len(ALL_CHECKS)
    by_id = {r["check_id"]: r["status"] for r in report["results"]}
    assert by_id["HG-SSH-001"] == "FAIL"
    assert by_id["HG-KRN-001"] == "FAIL"


def test_scan_text_output_and_unsupported_notice() -> None:
    root = FIXTURES / "edge_cases" / "root"
    result = runner.invoke(app, ["scan", "--root", str(root)])
    assert result.exit_code == 0
    assert "UNSUPPORTED" in result.stdout
    assert "Notice: unsupported platform" in result.stdout
    assert "Garden Health:" in result.stdout
    assert "HG-UPD-001" in result.stdout


def test_scan_missing_root_exits_2(tmp_path: Path) -> None:
    result = runner.invoke(app, ["scan", "--root", str(tmp_path / "nope")])
    assert result.exit_code == 2


def test_scan_root_must_be_a_directory(tmp_path: Path) -> None:
    file = tmp_path / "f"
    file.write_text("")
    assert runner.invoke(app, ["scan", "--root", str(file)]).exit_code == 2


def test_checks_listing() -> None:
    result = runner.invoke(app, ["checks"])
    assert result.exit_code == 0
    assert len(result.stdout.strip().splitlines()) == len(ALL_CHECKS)


def test_checks_markdown_matches_committed_docs() -> None:
    committed = (REPO / "docs" / "CHECKS.md").read_text()
    assert committed == render_checks_markdown(ALL_CHECKS), (
        "docs/CHECKS.md is stale: run `uv run hardengarden checks --markdown > ../docs/CHECKS.md`"
    )
    result = runner.invoke(app, ["checks", "--markdown"])
    assert result.stdout == committed


def test_no_args_shows_help() -> None:
    result = runner.invoke(app, [])
    assert "scan" in result.stdout
