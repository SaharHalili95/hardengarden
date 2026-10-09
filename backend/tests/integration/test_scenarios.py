"""Every check against every fixture scenario: PASS, FAIL and edge cases (Phase 1)."""

from __future__ import annotations

import pytest

from hardengarden.checks import ALL_CHECKS
from hardengarden.core.engine import PRIVILEGE_HINT, run_scan
from hardengarden.core.models import Status
from hgtest import SCENARIOS, FakeRunner, load_scenario, platform

P, F, W, E, S, NA = (
    Status.PASS,
    Status.FAIL,
    Status.WARN,
    Status.ERROR,
    Status.SKIPPED,
    Status.NOT_APPLICABLE,
)

EXPECTED: dict[str, dict[str, Status]] = {
    "hardened": {
        "HG-SSH-001": P, "HG-SSH-002": P, "HG-SSH-003": P, "HG-FW-001": P, "HG-NET-001": P,
        "HG-FS-001": P, "HG-FS-002": P, "HG-FS-003": P, "HG-ACC-001": P, "HG-ACC-002": P,
        "HG-UPD-001": P, "HG-KRN-001": P,
    },
    "default_ubuntu_2404": {
        "HG-SSH-001": W, "HG-SSH-002": F, "HG-SSH-003": P, "HG-FW-001": F, "HG-NET-001": P,
        "HG-FS-001": P, "HG-FS-002": P, "HG-FS-003": P, "HG-ACC-001": P, "HG-ACC-002": P,
        "HG-UPD-001": P, "HG-KRN-001": P,
    },
    "misconfigured": {
        "HG-SSH-001": F, "HG-SSH-002": F, "HG-SSH-003": F, "HG-FW-001": F, "HG-NET-001": W,
        "HG-FS-001": F, "HG-FS-002": F, "HG-FS-003": F, "HG-ACC-001": F, "HG-ACC-002": F,
        "HG-UPD-001": F, "HG-KRN-001": F,
    },
    "edge_cases": {
        "HG-SSH-001": P, "HG-SSH-002": W, "HG-SSH-003": P, "HG-FW-001": F, "HG-NET-001": E,
        "HG-FS-001": E, "HG-FS-002": P, "HG-FS-003": P, "HG-ACC-001": P, "HG-ACC-002": S,
        "HG-UPD-001": NA, "HG-KRN-001": W,
    },
}  # fmt: skip

EXPECTED_SCORE = {"hardened": 100, "default_ubuntu_2404": 78, "misconfigured": 2, "edge_cases": 79}


def _scan(name: str) -> dict[str, Status]:
    report = run_scan(load_scenario(name), ALL_CHECKS, runner=FakeRunner())
    return {r.check_id: r.status for r in report.results}


def test_every_check_has_pass_fail_and_edge_coverage() -> None:
    for check in ALL_CHECKS:
        seen = {EXPECTED[s][check.meta.id] for s in SCENARIOS}
        assert Status.PASS in seen, check.meta.id
        assert seen & {Status.FAIL, Status.WARN}, check.meta.id
        edge = EXPECTED["edge_cases"][check.meta.id]
        assert edge is not None


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_scenario_statuses(scenario: str) -> None:
    assert _scan(scenario) == EXPECTED[scenario]


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_scenario_scores(scenario: str) -> None:
    report = run_scan(load_scenario(scenario), ALL_CHECKS, runner=FakeRunner())
    assert report.summary.score == EXPECTED_SCORE[scenario]


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_scan_is_deterministic(scenario: str) -> None:
    first = run_scan(load_scenario(scenario), ALL_CHECKS, runner=FakeRunner())
    second = run_scan(load_scenario(scenario), ALL_CHECKS, runner=FakeRunner())
    strip = [(r.check_id, r.status, r.evidence, r.reason) for r in first.results]
    assert strip == [(r.check_id, r.status, r.evidence, r.reason) for r in second.results]
    assert first.summary == second.summary


def test_edge_cases_report_platform_and_coverage() -> None:
    report = run_scan(load_scenario("edge_cases"), ALL_CHECKS, runner=FakeRunner())
    assert not report.platform_supported
    assert report.platform.distro_id == "arch"
    cov = report.summary.coverage
    assert (cov.evaluated, cov.skipped, cov.errors, cov.not_applicable) == (8, 1, 2, 1)
    assert cov.percent == 73


def test_privilege_hint_when_not_root() -> None:
    view = load_scenario("edge_cases")
    report = run_scan(view, ALL_CHECKS, runner=FakeRunner(), platform=platform(is_root=False))
    assert report.privilege_hint is not None
    assert report.privilege_hint.startswith(PRIVILEGE_HINT)
    assert report.summary.coverage.skipped_for_privileges == 1


def test_live_host_without_root_skips_root_checks() -> None:
    view = load_scenario("hardened", host_root=True)
    report = run_scan(view, ALL_CHECKS, runner=FakeRunner(), platform=platform(is_root=False))
    skipped = {r.check_id for r in report.results if r.status is Status.SKIPPED}
    assert skipped == {"HG-FW-001", "HG-ACC-002"}
    assert report.summary.coverage.percent == 83
    assert report.privilege_hint is not None


def test_misconfigured_evidence_is_specific() -> None:
    report = run_scan(load_scenario("misconfigured"), ALL_CHECKS, runner=FakeRunner())
    evidence = {r.check_id: " | ".join(r.evidence) for r in report.results}
    assert "PermitRootLogin yes" in evidence["HG-SSH-001"]
    assert "toor" in evidence["HG-ACC-001"]
    assert "/etc/cron.d/backup" in evidence["HG-FS-003"]
    assert "/etc/app" in evidence["HG-FS-003"]
    assert "tcp 0.0.0.0:80" in evidence["HG-NET-001"]
    assert "tcp [::]:6379" in evidence["HG-NET-001"]
    assert "8080" not in evidence["HG-NET-001"]  # bound to ::1
    assert "NOPASSWD" in evidence["HG-ACC-002"]
