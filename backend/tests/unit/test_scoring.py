"""Garden Health score: table-driven, exhaustive edge cases (section 5.2)."""

from __future__ import annotations

import itertools

import pytest

from hardengarden.core.models import CheckResult, Reason, Severity, Status
from hardengarden.core.scoring import WEIGHTS, compute_score

C, H, M, L, INF = Severity.CRITICAL, Severity.HIGH, Severity.MEDIUM, Severity.LOW, Severity.INFO
P, F, W, E, S, NA = (
    Status.PASS,
    Status.FAIL,
    Status.WARN,
    Status.ERROR,
    Status.SKIPPED,
    Status.NOT_APPLICABLE,
)


def _run(rows: list[tuple[Severity, Status]]) -> tuple[int | None, int | None]:
    results = [
        CheckResult(check_id=f"HG-TST-{i:03d}", status=st, duration_ms=0)
        for i, (_, st) in enumerate(rows)
    ]
    severities = {f"HG-TST-{i:03d}": sev for i, (sev, _) in enumerate(rows)}
    summary = compute_score(results, severities)
    return summary.score, summary.coverage.percent


@pytest.mark.parametrize(
    ("rows", "score", "coverage"),
    [
        ([], None, None),  # nothing at all
        ([(C, S), (H, E), (M, NA)], None, 0),  # all skipped / errored / n.a. -> no score, never 100
        ([(INF, P), (INF, F)], None, 100),  # only INFO -> denominator 0 -> no score
        ([(C, P), (H, P), (M, P), (L, P)], 100, 100),  # all pass
        ([(C, F), (H, F), (M, F), (L, F)], 0, 100),  # all fail
        ([(C, W), (H, W)], 50, 100),  # all warn
        ([(C, F), (C, P)], 50, 100),
        ([(H, F), (C, P)], 63, 100),  # 100*(1-6/16) = 62.5 -> half-up 63
        ([(L, W), (C, P), (C, P), (C, P), (C, P), (C, P), (C, P), (C, P), (C, P), (C, P), (C, P)],
         100, 100),  # 100*(1-0.5/101) = 99.50 -> 100 (half-up)
        ([(M, W), (H, P)], 83, 100),  # 100*(1-1.5/9) = 83.33
        ([(C, F), (H, S)], 0, 50),  # skipped excluded from denominator
        ([(C, P), (H, E), (M, NA)], 100, 50),  # N/A excluded from coverage base
        ([(INF, F), (C, P)], 100, 100),  # INFO never moves the score
    ],
)  # fmt: skip
def test_score_table(
    rows: list[tuple[Severity, Status]], score: int | None, coverage: int | None
) -> None:
    assert _run(rows) == (score, coverage)


def test_weights_match_spec() -> None:
    assert dict(WEIGHTS) == {C: 10, H: 6, M: 3, L: 1, INF: 0}


def test_score_always_in_range_for_every_combination() -> None:
    severities = [C, H, M, L, INF]
    statuses = [P, F, W, E, S, NA]
    for combo in itertools.product(statuses, repeat=3):
        for sevs in itertools.product(severities, repeat=3):
            score, _ = _run(list(zip(sevs, combo, strict=True)))
            assert score is None or 0 <= score <= 100


def test_privilege_skips_are_counted_separately() -> None:
    results = [
        CheckResult(
            check_id="HG-TST-001", status=S, reason=Reason.INSUFFICIENT_PRIVILEGES, duration_ms=0
        ),
        CheckResult(check_id="HG-TST-002", status=S, reason=Reason.UNAVAILABLE, duration_ms=0),
        CheckResult(check_id="HG-TST-003", status=P, duration_ms=0),
    ]
    summary = compute_score(results, {r.check_id: H for r in results})
    assert summary.coverage.skipped == 2
    assert summary.coverage.skipped_for_privileges == 1
    assert summary.coverage.percent == 33
    assert summary.score == 100
