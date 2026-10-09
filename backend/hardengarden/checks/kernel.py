"""Kernel hardening: HG-KRN-001 (ASLR)."""

from __future__ import annotations

from hardengarden.core.check import Check, CheckContext, Outcome
from hardengarden.core.models import ANY_LINUX, Category, CheckMeta, Reason, Severity
from hardengarden.core.systemview import SystemViewError

ASLR_PATH = "/proc/sys/kernel/randomize_va_space"


def check_aslr(ctx: CheckContext) -> Outcome:
    try:
        value = ctx.view.read_text(ASLR_PATH).strip()
    except SystemViewError:
        return Outcome.error(Reason.UNAVAILABLE, f"{ASLR_PATH} is not readable")
    evidence = f"kernel.randomize_va_space = {value}"
    if value == "2":
        return Outcome.passed(evidence)
    if value == "1":
        return Outcome.warn(evidence, "only stack/mmap/VDSO are randomized; heap (brk) is not")
    if value == "0":
        return Outcome.failed(evidence, "address space layout randomization is disabled")
    return Outcome.error(Reason.UNAVAILABLE, f"unexpected value in {ASLR_PATH}: {value[:20]!r}")


CHECKS = (
    Check(
        CheckMeta(
            id="HG-KRN-001",
            title="ASLR enabled",
            category=Category.KERNEL,
            severity=Severity.MEDIUM,
            rationale="Address space layout randomization makes memory-corruption exploits "
            "unreliable, because attackers cannot predict where code and data live.",
            requires_root=False,
            platforms=(ANY_LINUX,),
            kb_doc="knowledge/aslr.md",
            remediation_template="hg-krn-001.sh",
        ),
        check_aslr,
    ),
)
