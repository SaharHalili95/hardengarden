"""CLI behaviour and the generated docs/CHECKS.md (Phase 1)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from fake_ollama import fake_ollama
from hardengarden import __version__
from hardengarden.checks import ALL_CHECKS
from hardengarden.cli import app, render_checks_markdown
from hardengarden.core.settings import Settings, save_settings
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


def test_kb_commands_work_without_ollama(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    save_settings(Settings(ollama_url="http://127.0.0.1:9"), tmp_path / "hardengarden")
    ingest = runner.invoke(app, ["kb", "ingest"])
    assert ingest.exit_code == 0
    assert "Keyword search still works" in ingest.stdout
    found = runner.invoke(app, ["kb", "search", "What permissions should /etc/shadow have?"])
    assert found.exit_code == 0
    assert found.stdout.startswith("answerable")
    assert "shadow-permissions#" in found.stdout
    refused = runner.invoke(app, ["kb", "search", "How do I bake sourdough bread?"])
    assert refused.stdout.startswith("not enough information")
    golden = Path(__file__).resolve().parents[1] / "rag_eval" / "golden.yaml"
    evaluated = runner.invoke(app, ["kb", "eval", str(golden), "--no-vectors"])
    assert evaluated.exit_code == 0
    assert "Recall@5: 1.0000" in evaluated.stdout


def test_explain_ask_and_ai_status_without_ollama(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "d"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "c"))
    save_settings(Settings(ollama_url="http://127.0.0.1:9"), tmp_path / "d" / "hardengarden")
    root = FIXTURES / "misconfigured" / "root"
    explained = runner.invoke(app, ["explain", "hg-ssh-001", "--root", str(root)])
    assert explained.exit_code == 1
    assert "HG-SSH-001 SSH root login disabled: FAIL" in explained.stdout
    assert "hardengarden remediation HG-SSH-001" in explained.stdout
    assert "AI explanations need Ollama" in explained.stdout
    refused = runner.invoke(app, ["ask", "How do I bake sourdough bread?"])
    assert refused.exit_code == 0
    assert "Not enough information" in refused.stdout
    status = runner.invoke(app, ["ai", "status"])
    assert status.exit_code == 0
    assert "State: ollama_not_installed" in status.stdout


def test_explain_streams_a_grounded_answer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "d"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "c"))
    with fake_ollama() as (url, _):
        save_settings(
            Settings(ollama_url=url, chat_model="qwen2.5:7b-instruct"),
            tmp_path / "d" / "hardengarden",
        )
        monkeypatch.setattr("hardengarden.rag.models.read_memory", lambda view=None: None)
        root = FIXTURES / "misconfigured" / "root"
        first = runner.invoke(app, ["explain", "HG-SSH-001", "--root", str(root)])
        assert first.exit_code == 0, first.stdout
        assert "Root login is risky" in first.stdout
        assert "Sources: ssh-root-login#why-it-matters" in first.stdout
        second = runner.invoke(app, ["explain", "HG-SSH-001", "--root", str(root)])
        assert "(cached answer)" in second.stdout


def test_explain_errors() -> None:
    assert runner.invoke(app, ["explain", "HG-NOPE-001"]).exit_code == 2
    assert runner.invoke(app, ["explain", "HG-SSH-001", "--root", "/nonexistent/x"]).exit_code == 2


def test_remediation_command() -> None:
    script = runner.invoke(app, ["remediation", "hg-krn-001"])
    assert script.exit_code == 0
    assert script.stdout.startswith("#!/usr/bin/env bash")
    assert "REVIEW BEFORE RUNNING" in script.stdout
    assert runner.invoke(app, ["remediation", "HG-NET-001"]).exit_code == 1
    assert runner.invoke(app, ["remediation", "HG-NOPE-001"]).exit_code == 2


def test_ai_pull_requires_confirmation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    with fake_ollama() as (url, script):
        save_settings(Settings(ollama_url=url), tmp_path / "hardengarden")
        declined = runner.invoke(app, ["ai", "pull", "qwen2.5:1.5b-instruct"], input="n\n")
        assert declined.exit_code == 1
        assert "about 1.0 GB" in declined.stdout
        assert script.pull_calls == 0
        accepted = runner.invoke(app, ["ai", "pull", "qwen2.5:1.5b-instruct", "--yes"])
        assert accepted.exit_code == 0
        assert "success" in accepted.stdout
        assert script.pull_calls == 1
    assert runner.invoke(app, ["ai", "pull", "evil/model", "--yes"]).exit_code == 2
