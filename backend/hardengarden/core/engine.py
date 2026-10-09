"""Runs checks, isolates failures and builds the :class:`ScanReport`."""

from __future__ import annotations

import time
from collections.abc import Sequence

from hardengarden import __version__
from hardengarden.core.check import Check, CheckContext, Outcome
from hardengarden.core.models import (
    ANY_LINUX,
    CheckResult,
    Platform,
    Reason,
    ScanReport,
    Severity,
    Status,
)
from hardengarden.core.platform import detect_platform
from hardengarden.core.redaction import clean_evidence
from hardengarden.core.runner import NullRunner, Runner, SubprocessRunner
from hardengarden.core.scoring import compute_score
from hardengarden.core.systemview import AccessDeniedError, SystemView

PRIVILEGE_HINT = "Run with sudo for full coverage"


def default_runner(view: SystemView) -> Runner:
    """Commands describe the live host, so they only run when scanning ``/``."""
    return SubprocessRunner() if view.is_host_root else NullRunner()


def _applicable(check: Check, platform: Platform) -> bool:
    return ANY_LINUX in check.meta.platforms or platform.key in check.meta.platforms


def run_check(check: Check, ctx: CheckContext, platform: Platform) -> CheckResult:
    """Run one check. Never raises: a crash becomes an ERROR result with a safe message."""
    started = time.perf_counter_ns()
    outcome: Outcome
    if not _applicable(check, platform):
        outcome = Outcome.not_applicable(
            Reason.UNSUPPORTED_PLATFORM, f"not applicable on {platform.pretty_name}"
        )
    elif check.meta.requires_root and ctx.live_host and not ctx.is_root:
        outcome = Outcome.skipped(Reason.INSUFFICIENT_PRIVILEGES, "this check needs root")
    else:
        try:
            outcome = check.run(ctx)
        except AccessDeniedError:
            reason = Reason.UNAVAILABLE if ctx.is_root else Reason.INSUFFICIENT_PRIVILEGES
            outcome = Outcome.skipped(reason, "a required file is not readable")
        except Exception as exc:  # noqa: BLE001  # justification: one crashing check must never abort the scan (section 5.1)
            outcome = Outcome.error(Reason.CHECK_CRASHED, f"internal error ({type(exc).__name__})")
    elapsed_ms = (time.perf_counter_ns() - started) // 1_000_000
    return CheckResult(
        check_id=check.meta.id,
        status=outcome.status,
        evidence=clean_evidence(outcome.evidence),
        reason=outcome.reason,
        duration_ms=elapsed_ms,
    )


def run_scan(
    view: SystemView,
    checks: Sequence[Check],
    *,
    runner: Runner | None = None,
    platform: Platform | None = None,
) -> ScanReport:
    platform = platform or detect_platform(view)
    ctx = CheckContext(view=view, runner=runner or default_runner(view), is_root=platform.is_root)
    results = [run_check(check, ctx, platform) for check in checks]
    severities: dict[str, Severity] = {c.meta.id: c.meta.severity for c in checks}
    summary = compute_score(results, severities)
    hint = None
    if summary.coverage.skipped_for_privileges:
        count = summary.coverage.skipped_for_privileges
        hint = f"{PRIVILEGE_HINT} ({count} check(s) skipped: insufficient privileges)"
    return ScanReport(
        tool_version=__version__,
        scanned_root=str(view.root),
        platform=platform,
        platform_supported=platform.supported,
        results=results,
        summary=summary,
        privilege_hint=hint,
    )


def status_counts(report: ScanReport) -> dict[Status, int]:
    counts = dict.fromkeys(Status, 0)
    for result in report.results:
        counts[result.status] += 1
    return counts
