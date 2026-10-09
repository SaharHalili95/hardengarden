"""Engine isolation, platform detection, models and redaction."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from hardengarden.checks import ALL_CHECKS
from hardengarden.core.check import Check, CheckContext, Outcome
from hardengarden.core.engine import default_runner, run_check, run_scan, status_counts
from hardengarden.core.models import (
    ANY_LINUX,
    MAX_EVIDENCE_CHARS,
    MAX_EVIDENCE_ITEMS,
    Category,
    CheckMeta,
    Reason,
    Severity,
    Status,
)
from hardengarden.core.platform import detect_platform, parse_os_release
from hardengarden.core.redaction import REDACTED, clean_evidence, redact
from hardengarden.core.runner import NullRunner, SubprocessRunner
from hardengarden.core.systemview import AccessDeniedError, SystemView
from hgtest import FakeRunner, make_view, platform


def _meta(**overrides: object) -> CheckMeta:
    base: dict[str, object] = {
        "id": "HG-TST-001", "title": "t", "category": Category.KERNEL, "severity": Severity.LOW,
        "rationale": "r", "requires_root": False, "platforms": (ANY_LINUX,),
        "kb_doc": "knowledge/x.md",
        "remediation_template": None,
    }  # fmt: skip
    base.update(overrides)
    return CheckMeta.model_validate(base)


def _ctx(tmp_path: Path, *, is_root: bool = True) -> CheckContext:
    return CheckContext(
        view=make_view(tmp_path, {"/etc/x": ""}), runner=FakeRunner(), is_root=is_root
    )


def test_crashing_check_becomes_error_without_leaking_details(tmp_path: Path) -> None:
    def boom(_: CheckContext) -> Outcome:
        raise RuntimeError("/etc/shadow contents: secret")

    result = run_check(Check(_meta(), boom), _ctx(tmp_path), platform())
    assert result.status is Status.ERROR
    assert result.reason == Reason.CHECK_CRASHED
    assert result.evidence == ["internal error (RuntimeError)"]


def test_access_denied_becomes_skipped(tmp_path: Path) -> None:
    def denied(_: CheckContext) -> Outcome:
        raise AccessDeniedError("/etc/sudoers")

    as_user = run_check(
        Check(_meta(), denied), _ctx(tmp_path, is_root=False), platform(is_root=False)
    )
    assert (as_user.status, as_user.reason) == (Status.SKIPPED, Reason.INSUFFICIENT_PRIVILEGES)
    as_root = run_check(Check(_meta(), denied), _ctx(tmp_path), platform())
    assert (as_root.status, as_root.reason) == (Status.SKIPPED, Reason.UNAVAILABLE)


def test_platform_specific_check_is_not_applicable_elsewhere(tmp_path: Path) -> None:
    check = Check(_meta(platforms=("debian-12",)), lambda _: Outcome.passed())
    result = run_check(check, _ctx(tmp_path), platform("fedora", "40"))
    assert (result.status, result.reason) == (Status.NOT_APPLICABLE, Reason.UNSUPPORTED_PLATFORM)
    assert run_check(check, _ctx(tmp_path), platform("debian", "12")).status is Status.PASS


def test_evidence_is_redacted_and_capped(tmp_path: Path) -> None:
    items = [f"line {i} password=hunter{i}" for i in range(15)]
    check = Check(_meta(), lambda _: Outcome.failed(*items))
    result = run_check(check, _ctx(tmp_path), platform())
    assert len(result.evidence) == MAX_EVIDENCE_ITEMS
    assert "hunter" not in " ".join(result.evidence)
    assert result.evidence[-1] == "... and 6 more"


def test_status_counts_and_default_runner(tmp_path: Path) -> None:
    report = run_scan(make_view(tmp_path, {"/etc/x": ""}), ALL_CHECKS, runner=FakeRunner())
    counts = status_counts(report)
    assert sum(counts.values()) == len(ALL_CHECKS)
    assert isinstance(default_runner(SystemView("/")), SubprocessRunner)
    assert isinstance(default_runner(SystemView(tmp_path)), NullRunner)


def test_detect_platform(tmp_path: Path) -> None:
    view = make_view(
        tmp_path, {"/usr/lib/os-release": 'ID=Debian\nVERSION_ID="12"\nPRETTY_NAME="Debian 12"\n'}
    )
    detected = detect_platform(view, is_root=False)
    assert (detected.key, detected.supported, detected.is_root) == ("debian-12", True, False)
    unknown = detect_platform(make_view(tmp_path / "e", {"/etc/x": ""}), is_root=True)
    assert (unknown.key, unknown.supported) == ("unknown-unknown", False)


def test_parse_os_release_quoting() -> None:
    parsed = parse_os_release(
        '# c\nNAME="Ubuntu"\nBAD\nX=\'single\'\nBROKEN="unterminated\nEMPTY=\n'
    )
    assert parsed == {"NAME": "Ubuntu", "X": "single", "EMPTY": ""}


def test_meta_validation() -> None:
    with pytest.raises(ValidationError):
        _meta(id="BAD-ID")
    with pytest.raises(ValidationError):
        _meta(platforms=())
    with pytest.raises(ValidationError):
        _meta(platforms=("windows",))


def test_registry_ids_are_unique_and_twelve() -> None:
    ids = [c.meta.id for c in ALL_CHECKS]
    assert len(ids) == 12
    assert len(set(ids)) == 12


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("root:$6$salt$hash:19000:0", f"root:{REDACTED}:19000:0"),
        ("user:$y$j9T$abc$def:1", f"user:{REDACTED}:1"),
        ("-----BEGIN OPENSSH PRIVATE KEY-----\nabc\n-----END OPENSSH PRIVATE KEY-----", REDACTED),
        ("Authorization: Bearer abcdef0123456789", f"Authorization: Bearer {REDACTED}"),
        ("db_password = 'x y z'", f"db_password = {REDACTED}"),
        ("API_KEY: abc", f"API_KEY: {REDACTED}"),
        ("ssh-ed25519 " + "A" * 68 + " me@host", f"ssh-ed25519 {REDACTED} me@host"),
        ("/etc/passwd: mode 0644", "/etc/passwd: mode 0644"),
        ("PasswordAuthentication yes", "PasswordAuthentication yes"),
        ("alice ALL=(ALL) NOPASSWD: ALL", "alice ALL=(ALL) NOPASSWD: ALL"),
    ],
)
def test_redaction(raw: str, expected: str) -> None:
    assert redact(raw) == expected
    assert redact(redact(raw)) == redact(raw)


def test_clean_evidence_truncates_and_flattens() -> None:
    cleaned = clean_evidence(["a\n  b", "", "x" * 500])
    assert cleaned[0] == "a b"
    assert len(cleaned) == 2
    assert len(cleaned[1]) == MAX_EVIDENCE_CHARS
