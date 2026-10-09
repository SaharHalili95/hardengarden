"""sshd_config parsing semantics and HG-SSH-001..003 decision logic."""

from __future__ import annotations

from pathlib import Path

import pytest

from hardengarden.checks.ssh import check_empty_passwords, check_password_auth, check_root_login
from hardengarden.checks.sshd_config import parse_sshd_config, parse_sshd_t
from hardengarden.core.models import Reason, Status
from hardengarden.core.runner import Command, CommandResult
from hgtest import FakeRunner, ctx, make_view, ok

CFG = "/etc/ssh/sshd_config"


def test_first_value_wins_across_includes(tmp_path: Path) -> None:
    view = make_view(
        tmp_path,
        {
            CFG: "Include /etc/ssh/sshd_config.d/*.conf\nPermitRootLogin yes\n",
            "/etc/ssh/sshd_config.d/10-a.conf": "PermitRootLogin no\n",
            "/etc/ssh/sshd_config.d/20-b.conf": "PermitRootLogin yes\n",
        },
    )
    directive = parse_sshd_config(view).global_value("permitrootlogin")
    assert directive is not None
    assert directive.value == "no"
    assert directive.source.endswith("10-a.conf:1")


def test_relative_include_and_lexical_order(tmp_path: Path) -> None:
    view = make_view(
        tmp_path,
        {
            CFG: "Include conf.d/*.conf\n",
            "/etc/ssh/conf.d/b.conf": "PasswordAuthentication yes\n",
            "/etc/ssh/conf.d/a.conf": "PasswordAuthentication no\n",
            "/etc/ssh/conf.d/.hidden.conf": "PasswordAuthentication yes\n",
        },
    )
    assert check_password_auth(ctx(view)).status is Status.PASS


def test_case_insensitive_keywords_equals_syntax_and_comments(tmp_path: Path) -> None:
    view = make_view(
        tmp_path, {CFG: "# PermitRootLogin yes\n   PERMITROOTLOGIN = No   # trailing\n"}
    )
    assert check_root_login(ctx(view)).status is Status.PASS


def test_quoted_values_and_tabs(tmp_path: Path) -> None:
    view = make_view(tmp_path, {CFG: 'PermitEmptyPasswords\t"yes"\n'})
    assert check_empty_passwords(ctx(view)).status is Status.FAIL


def test_include_loop_is_reported_not_followed(tmp_path: Path) -> None:
    view = make_view(
        tmp_path,
        {CFG: "Include a.conf\nPermitRootLogin no\n", "/etc/ssh/a.conf": "Include b.conf\n",
         "/etc/ssh/b.conf": "Include a.conf\n"},
    )  # fmt: skip
    config = parse_sshd_config(view)
    assert any("include loop" in note for note in config.notes)
    outcome = check_root_login(ctx(view))
    assert outcome.status is Status.PASS
    assert any("include loop" in e for e in outcome.evidence)


def test_include_depth_is_bounded(tmp_path: Path) -> None:
    files = {CFG: "Include d0.conf\n"}
    for i in range(20):
        files[f"/etc/ssh/d{i}.conf"] = f"Include d{i + 1}.conf\n"
    config = parse_sshd_config(make_view(tmp_path, files))
    assert any("depth limit" in note for note in config.notes)


def test_malformed_lines_are_noted(tmp_path: Path) -> None:
    view = make_view(
        tmp_path, {CFG: "PermitRootLogin\n%%%garbage\nInclude\nMatch\nPermitRootLogin no\n"}
    )
    config = parse_sshd_config(view)
    assert len(config.notes) == 4
    assert check_root_login(ctx(view)).status is Status.PASS


def test_match_block_override_warns(tmp_path: Path) -> None:
    view = make_view(
        tmp_path,
        {
            CFG: "PasswordAuthentication no\n"
            "Match Address 10.0.0.0/8\n  PasswordAuthentication yes\n"
        },
    )
    outcome = check_password_auth(ctx(view))
    assert outcome.status is Status.WARN
    assert any("conditional override: Match address 10.0.0.0/8" in e for e in outcome.evidence)


def test_match_block_does_not_change_global_value(tmp_path: Path) -> None:
    view = make_view(tmp_path, {CFG: "Match User x\n  PermitRootLogin no\n"})
    outcome = check_root_login(ctx(view))
    assert outcome.status is Status.WARN  # default prohibit-password, Match is not global
    assert any("not set" in e for e in outcome.evidence)


def test_stronger_match_override_is_not_reported(tmp_path: Path) -> None:
    view = make_view(tmp_path, {CFG: "PermitRootLogin no\nMatch User x\n  PermitRootLogin no\n"})
    assert check_root_login(ctx(view)).evidence == [f"PermitRootLogin no ({CFG}:1)"]


def test_match_in_included_file_ends_with_that_file(tmp_path: Path) -> None:
    view = make_view(
        tmp_path,
        {CFG: "Include m.conf\nPasswordAuthentication no\n",
         "/etc/ssh/m.conf": "Match User x\n  PermitRootLogin yes\n"},
    )  # fmt: skip
    config = parse_sshd_config(view)
    global_value = config.global_value("passwordauthentication")
    assert global_value is not None
    assert global_value.value == "no"


@pytest.mark.parametrize(
    ("value", "status"),
    [("no", Status.PASS), ("yes", Status.FAIL), ("prohibit-password", Status.WARN),
     ("without-password", Status.WARN), ("forced-commands-only", Status.WARN),
     ("bogus", Status.WARN)],
)  # fmt: skip
def test_root_login_values(tmp_path: Path, value: str, status: Status) -> None:
    view = make_view(tmp_path, {CFG: f"PermitRootLogin {value}\n"})
    assert check_root_login(ctx(view)).status is status


def test_defaults_apply_when_unset(tmp_path: Path) -> None:
    view = make_view(tmp_path, {CFG: "UsePAM yes\n"})
    assert check_root_login(ctx(view)).status is Status.WARN
    assert check_password_auth(ctx(view)).status is Status.FAIL
    assert check_empty_passwords(ctx(view)).status is Status.PASS


def test_not_installed_is_not_applicable(tmp_path: Path) -> None:
    outcome = check_root_login(ctx(make_view(tmp_path, {"/etc/hostname": "x\n"})))
    assert outcome.status is Status.NOT_APPLICABLE
    assert outcome.reason == Reason.NOT_INSTALLED


def test_binary_without_config_uses_defaults(tmp_path: Path) -> None:
    view = make_view(tmp_path, {"/usr/sbin/sshd": ""})
    assert check_password_auth(ctx(view)).status is Status.FAIL


def test_unreadable_include_is_skipped_for_privileges(tmp_path: Path) -> None:
    view = make_view(
        tmp_path,
        {CFG: "Include x.conf\n", "/etc/ssh/x.conf": "PermitRootLogin yes\n"},
        {"/etc/ssh/x.conf": {"unreadable": True}},
    )
    outcome = check_root_login(ctx(view, is_root=False))
    assert outcome.status is Status.SKIPPED
    assert outcome.reason == Reason.INSUFFICIENT_PRIVILEGES
    assert check_root_login(ctx(view, is_root=True)).reason == Reason.UNAVAILABLE


def test_sshd_t_is_authoritative_on_live_host_as_root(tmp_path: Path) -> None:
    view = make_view(tmp_path, {CFG: "PermitRootLogin yes\n"}, host_root=True)
    runner = FakeRunner({Command.SSHD_EFFECTIVE_CONFIG: ok("port 22\npermitrootlogin no\n")})
    outcome = check_root_login(ctx(view, runner, is_root=True))
    assert outcome.status is Status.PASS
    assert "from sshd -T" in outcome.evidence[0]
    assert runner.calls == [Command.SSHD_EFFECTIVE_CONFIG]


def test_sshd_t_not_used_without_root_or_off_host(tmp_path: Path) -> None:
    runner = FakeRunner({Command.SSHD_EFFECTIVE_CONFIG: ok("permitrootlogin no\n")})
    live = make_view(tmp_path, {CFG: "PermitRootLogin yes\n"}, host_root=True)
    assert check_root_login(ctx(live, runner, is_root=False)).status is Status.FAIL
    fixture = make_view(tmp_path, {CFG: "PermitRootLogin yes\n"})
    assert check_root_login(ctx(fixture, runner, is_root=True)).status is Status.FAIL
    assert runner.calls == []


def test_sshd_t_failure_falls_back_to_files(tmp_path: Path) -> None:
    view = make_view(tmp_path, {CFG: "PermitRootLogin yes\n"}, host_root=True)
    failed = CommandResult(returncode=255, stdout="", stderr="no hostkeys", timed_out=False)
    runner = FakeRunner({Command.SSHD_EFFECTIVE_CONFIG: failed})
    assert check_root_login(ctx(view, runner)).status is Status.FAIL


def test_parse_sshd_t_first_value_wins() -> None:
    assert parse_sshd_t("PermitRootLogin no\npermitrootlogin yes\n\nbad\n") == {
        "permitrootlogin": "no"
    }
