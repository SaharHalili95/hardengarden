"""SSH server checks: HG-SSH-001..003."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from hardengarden.checks.sshd_config import MAIN_CONFIG, SshdConfig, parse_sshd_config, parse_sshd_t
from hardengarden.core.check import Check, CheckContext, Outcome
from hardengarden.core.models import ANY_LINUX, Category, CheckMeta, Reason, Severity, Status
from hardengarden.core.runner import Command

SSHD_BINARIES = ("/usr/sbin/sshd", "/sbin/sshd")
_RANK = {Status.PASS: 0, Status.WARN: 1, Status.FAIL: 2}

Judge = Callable[[str], Status]


@dataclass(frozen=True, slots=True)
class _Rule:
    keyword: str  # canonical spelling, e.g. "PermitRootLogin"
    default: str  # OpenSSH built-in default (lower-case)
    judge: Judge


def _judge_root_login(value: str) -> Status:
    if value == "no":
        return Status.PASS
    if value == "yes":
        return Status.FAIL
    # prohibit-password / without-password / forced-commands-only: key-based root login
    return Status.WARN


def _judge_yes_is_bad(value: str) -> Status:
    if value == "no":
        return Status.PASS
    if value == "yes":
        return Status.FAIL
    return Status.WARN


def _sshd_installed(ctx: CheckContext) -> bool:
    return ctx.view.exists(MAIN_CONFIG) or any(ctx.view.exists(b) for b in SSHD_BINARIES)


def _effective_from_sshd_t(ctx: CheckContext) -> dict[str, str] | None:
    """``sshd -T`` is authoritative but needs root and the live host."""
    if not (ctx.live_host and ctx.is_root):
        return None
    result = ctx.runner.run(Command.SSHD_EFFECTIVE_CONFIG)
    if result is None or not result.ok:
        return None
    return parse_sshd_t(result.stdout) or None


def _evaluate(ctx: CheckContext, rule: _Rule) -> Outcome:
    if not _sshd_installed(ctx):
        return Outcome.not_applicable(Reason.NOT_INSTALLED, "OpenSSH server is not installed")
    config = parse_sshd_config(ctx.view) if ctx.view.exists(MAIN_CONFIG) else SshdConfig()
    if config.unreadable:
        reason = Reason.UNAVAILABLE if ctx.is_root else Reason.INSUFFICIENT_PRIVILEGES
        return Outcome.skipped(reason, *(f"cannot read {p}" for p in config.unreadable))

    key = rule.keyword.lower()
    evidence: list[str] = []
    live = _effective_from_sshd_t(ctx)
    declared = config.global_value(key)
    if live is not None and key in live:
        value = live[key]
        evidence.append(f"{rule.keyword} {value} (effective, from sshd -T)")
    elif declared is not None:
        value = declared.value
        evidence.append(f"{rule.keyword} {value} ({declared.source})")
    else:
        value = rule.default
        evidence.append(f"{rule.keyword} not set; OpenSSH default is {value}")
    status = rule.judge(value)

    for override in config.overrides(key):
        override_status = rule.judge(override.value)
        if _RANK[override_status] > _RANK[status]:
            status = Status.WARN if status is Status.PASS else status
            evidence.append(
                f"conditional override: Match {override.match}: "
                f"{rule.keyword} {override.value} ({override.source})"
            )
    evidence.extend(config.notes)
    return Outcome(status, evidence)


def _meta(check_id: str, title: str, severity: Severity, rationale: str, slug: str) -> CheckMeta:
    return CheckMeta(
        id=check_id,
        title=title,
        category=Category.SSH,
        severity=severity,
        rationale=rationale,
        requires_root=False,
        platforms=(ANY_LINUX,),
        kb_doc=f"knowledge/{slug}.md",
        remediation_template=f"{check_id.lower()}.sh",
    )


_ROOT_LOGIN = _Rule("PermitRootLogin", "prohibit-password", _judge_root_login)
_PASSWORD_AUTH = _Rule("PasswordAuthentication", "yes", _judge_yes_is_bad)
_EMPTY_PASSWORDS = _Rule("PermitEmptyPasswords", "no", _judge_yes_is_bad)


def check_root_login(ctx: CheckContext) -> Outcome:
    return _evaluate(ctx, _ROOT_LOGIN)


def check_password_auth(ctx: CheckContext) -> Outcome:
    return _evaluate(ctx, _PASSWORD_AUTH)


def check_empty_passwords(ctx: CheckContext) -> Outcome:
    return _evaluate(ctx, _EMPTY_PASSWORDS)


CHECKS = (
    Check(
        _meta(
            "HG-SSH-001",
            "SSH root login disabled",
            Severity.HIGH,
            "Direct root login over SSH gives attackers a single, well-known account to target "
            "and removes the audit trail of which person used administrative rights.",
            "ssh-root-login",
        ),
        check_root_login,
    ),
    Check(
        _meta(
            "HG-SSH-002",
            "SSH password authentication disabled",
            Severity.HIGH,
            "Password logins can be guessed or brute-forced from the network. Key-based "
            "authentication removes that whole class of attack.",
            "ssh-password-authentication",
        ),
        check_password_auth,
    ),
    Check(
        _meta(
            "HG-SSH-003",
            "SSH empty passwords disallowed",
            Severity.CRITICAL,
            "If empty passwords are accepted, any account without a password can be entered "
            "remotely with no secret at all.",
            "ssh-empty-passwords",
        ),
        check_empty_passwords,
    ),
)
