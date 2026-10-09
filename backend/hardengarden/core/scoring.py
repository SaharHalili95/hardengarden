"""Garden Health score (docs/REQUIREMENTS.md section 5.2). Deterministic, exact, LLM-free (R11)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from fractions import Fraction

from hardengarden.core.models import (
    CheckResult,
    Coverage,
    Reason,
    ScoreSummary,
    Severity,
    Status,
)

WEIGHTS: Mapping[Severity, int] = {
    Severity.CRITICAL: 10,
    Severity.HIGH: 6,
    Severity.MEDIUM: 3,
    Severity.LOW: 1,
    Severity.INFO: 0,
}

_EVALUATED = frozenset({Status.PASS, Status.FAIL, Status.WARN})


def _round_half_up(value: Fraction) -> int:
    return int((value * 2 + 1) // 2)


def _percent(part: int, whole: int) -> int | None:
    if whole == 0:
        return None
    return _round_half_up(Fraction(100 * part, whole))


def compute_score(
    results: Sequence[CheckResult], severities: Mapping[str, Severity]
) -> ScoreSummary:
    """Score = 100 * (1 - (sum FAIL + 0.5 * sum WARN) / sum applicable), clamped, half-up.

    Only PASS/FAIL/WARN results are applicable. SKIPPED, ERROR and NOT_APPLICABLE are
    excluded and reported as coverage. An empty denominator yields ``None``, never 100.
    """
    denominator = 0
    penalty = Fraction(0)
    for result in results:
        if result.status not in _EVALUATED:
            continue
        weight = WEIGHTS[severities[result.check_id]]
        denominator += weight
        if result.status is Status.FAIL:
            penalty += weight
        elif result.status is Status.WARN:
            penalty += Fraction(weight, 2)

    score: int | None = None
    if denominator > 0:
        raw = 100 * (1 - penalty / denominator)
        score = _round_half_up(min(Fraction(100), max(Fraction(0), raw)))

    evaluated = sum(1 for r in results if r.status in _EVALUATED)
    skipped = sum(1 for r in results if r.status is Status.SKIPPED)
    errors = sum(1 for r in results if r.status is Status.ERROR)
    not_applicable = sum(1 for r in results if r.status is Status.NOT_APPLICABLE)
    for_privileges = sum(
        1
        for r in results
        if r.status is Status.SKIPPED and r.reason == Reason.INSUFFICIENT_PRIVILEGES
    )
    coverage = Coverage(
        total=len(results),
        evaluated=evaluated,
        skipped=skipped,
        errors=errors,
        not_applicable=not_applicable,
        skipped_for_privileges=for_privileges,
        percent=_percent(evaluated, evaluated + skipped + errors),
    )
    return ScoreSummary(score=score, coverage=coverage)
