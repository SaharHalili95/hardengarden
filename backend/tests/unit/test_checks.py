"""Unit tests for the non-SSH checks: edge cases beyond the scenario matrix."""

from __future__ import annotations

from pathlib import Path

import pytest

from hardengarden.checks.accounts import check_sudo_nopasswd, check_uid_zero
from hardengarden.checks.filesystem import (
    check_passwd_group,
    check_shadow,
    check_world_writable_etc,
)
from hardengarden.checks.firewall import check_firewall
from hardengarden.checks.kernel import check_aslr
from hardengarden.checks.network import Listener, parse_proc_net
from hardengarden.checks.updates import check_unattended_upgrades, parse_apt_conf
from hardengarden.core.models import Reason, Status
from hardengarden.core.runner import Command, CommandResult
from hgtest import FakeRunner, ctx, make_view, ok

# ------------------------------------------------------------------ firewall


def test_firewall_live_ufw_active(tmp_path: Path) -> None:
    view = make_view(tmp_path, {"/etc/x": ""}, host_root=True)
    runner = FakeRunner({Command.UFW_STATUS: ok("Status: active\n\nTo Action From\n")})
    assert check_firewall(ctx(view, runner)).status is Status.PASS


def test_firewall_live_nft_ruleset(tmp_path: Path) -> None:
    view = make_view(tmp_path, {"/etc/x": ""}, host_root=True)
    ruleset = (
        "table inet filter {\n chain input {\n"
        "  type filter hook input priority 0; policy drop;\n }\n}\n"
    )
    runner = FakeRunner(
        {Command.UFW_STATUS: ok("Status: inactive\n"), Command.NFT_RULESET: ok(ruleset)}
    )
    outcome = check_firewall(ctx(view, runner))
    assert outcome.status is Status.PASS
    assert "1 input-hook chain" in outcome.evidence[0]


def test_firewall_live_inactive(tmp_path: Path) -> None:
    view = make_view(tmp_path, {"/etc/x": ""}, host_root=True)
    runner = FakeRunner({Command.UFW_STATUS: ok("Status: inactive\n"), Command.NFT_RULESET: ok("")})
    outcome = check_firewall(ctx(view, runner))
    assert outcome.status is Status.FAIL
    assert outcome.evidence == ["ufw installed but not active", "no nftables chain hooked on input"]


def test_firewall_live_without_tools_falls_back_to_config(tmp_path: Path) -> None:
    view = make_view(tmp_path, {"/etc/ufw/ufw.conf": 'ENABLED="yes"\n'}, host_root=True)
    outcome = check_firewall(ctx(view, FakeRunner()))
    assert outcome.status is Status.PASS
    assert "runtime state not verified" in outcome.evidence[0]


def test_firewall_nft_config_needs_enabled_service(tmp_path: Path) -> None:
    rules = "table inet f { chain input { type filter hook input priority 0; } }\n"
    view = make_view(tmp_path, {"/etc/nftables.conf": rules})
    outcome = check_firewall(ctx(view))
    assert outcome.status is Status.FAIL
    assert "not enabled" in outcome.evidence[1]
    link = "/etc/systemd/system/sysinit.target.wants/nftables.service"
    enabled = make_view(tmp_path, {"/etc/nftables.conf": rules, link: ""})
    assert check_firewall(ctx(enabled)).status is Status.PASS


# ------------------------------------------------------------------ network

TCP_HDR = "  sl  local_address rem_address   st\n"


def test_parse_proc_net_ipv4_and_states() -> None:
    text = TCP_HDR + (
        "0: 00000000:0050 00000000:0000 0A\n"  # 0.0.0.0:80 LISTEN
        "1: 0100007F:1F90 00000000:0000 0A\n"  # 127.0.0.1:8080 loopback
        "2: 0F02000A:0016 0A02000A:C350 01\n"  # established, ignored
        "3: garbage\n"
        "4: ZZZZ:0016 00000000:0000 0A\n"
    )
    assert parse_proc_net("tcp", text) == [Listener("tcp", "0.0.0.0", 80)]


def test_parse_proc_net_ipv6_and_mapped_loopback() -> None:
    any6 = "0" * 32
    mapped_lo = "0000000000000000FFFF00000100007F"
    text = TCP_HDR + f"0: {any6}:01BB {any6}:0000 0A\n1: {mapped_lo}:0019 {any6}:0000 0A\n"
    assert parse_proc_net("tcp", text) == [Listener("tcp", "::", 443)]
    assert str(Listener("tcp", "::", 443)) == "tcp [::]:443"


def test_parse_proc_net_udp_only_unconnected() -> None:
    text = TCP_HDR + "0: 00000000:0044 00000000:0000 07\n1: 00000000:1234 0A00000A:0035 01\n"
    assert parse_proc_net("udp", text) == [Listener("udp", "0.0.0.0", 68)]


# ------------------------------------------------------------------ filesystem


@pytest.mark.parametrize(
    ("meta", "status"),
    [
        ({"mode": "0640", "gid": 42}, Status.PASS),
        ({"mode": "0000"}, Status.PASS),
        ({"mode": "0644", "gid": 42}, Status.FAIL),
        ({"mode": "0660", "gid": 42}, Status.FAIL),
        ({"mode": "0640", "uid": 1000, "gid": 42}, Status.FAIL),
        ({"mode": "0640", "gid": 1000}, Status.FAIL),
        ({"mode": "4640", "gid": 42}, Status.FAIL),
    ],
)
def test_shadow_permissions(tmp_path: Path, meta: dict[str, object], status: Status) -> None:
    view = make_view(
        tmp_path,
        {"/etc/shadow": "", "/etc/group": "root:x:0:\nshadow:x:42:\n"},
        {"/etc/shadow": meta},
    )
    assert check_shadow(ctx(view)).status is status


def test_shadow_symlink_fails(tmp_path: Path) -> None:
    view = make_view(tmp_path, {"/etc/real": "", "/etc/group": "root:x:0:\n"})
    (view.root / "etc" / "shadow").symlink_to("real")
    outcome = check_shadow(ctx(view))
    assert outcome.status is Status.FAIL
    assert any("symlink" in e for e in outcome.evidence)


def test_passwd_group_missing_is_error(tmp_path: Path) -> None:
    outcome = check_passwd_group(ctx(make_view(tmp_path, {"/etc/passwd": ""})))
    assert outcome.status is Status.ERROR
    assert outcome.reason == Reason.FILE_MISSING


def test_passwd_group_owner_and_special_bits(tmp_path: Path) -> None:
    files = {"/etc/passwd": "", "/etc/group": ""}
    view = make_view(tmp_path, files, {"/etc/group": {"mode": "2644", "gid": 5}})
    outcome = check_passwd_group(ctx(view))
    assert outcome.status is Status.FAIL
    assert "/etc/group is not owned by root:root" in outcome.evidence
    assert "/etc/group has setuid/setgid/sticky bits" in outcome.evidence


def test_world_writable_notes_unreadable_dirs(tmp_path: Path) -> None:
    view = make_view(
        tmp_path,
        {"/etc/ssl/private/key": "", "/etc/ok": ""},
        {"/etc/ssl/private": {"unreadable": True}},
    )
    outcome = check_world_writable_etc(ctx(view, is_root=False))
    assert outcome.status is Status.PASS
    assert "could not be read without root" in outcome.evidence[1]


def test_world_writable_ignores_symlinks(tmp_path: Path) -> None:
    view = make_view(tmp_path, {"/etc/target": ""})
    (view.root / "etc" / "alternatives").symlink_to("target")
    assert check_world_writable_etc(ctx(view)).status is Status.PASS


# ------------------------------------------------------------------ accounts


def test_uid_zero_missing_passwd(tmp_path: Path) -> None:
    assert check_uid_zero(ctx(make_view(tmp_path, {"/etc/x": ""}))).status is Status.ERROR


SUDOERS = "root ALL=(ALL:ALL) ALL\n"


@pytest.mark.parametrize(
    ("extra", "status"),
    [
        ("", Status.PASS),
        ("alice ALL=(ALL) NOPASSWD: ALL\n", Status.FAIL),
        ("alice ALL=(ALL) NOPASSWD:/usr/bin/apt\n", Status.FAIL),
        ("Defaults:alice !authenticate\n", Status.FAIL),
        ("# alice ALL=(ALL) NOPASSWD: ALL\n", Status.PASS),
        ("Cmnd_Alias X = /bin/ls, \\\n   /bin/cat NOPASSWD: ALL\n", Status.FAIL),
    ],
)
def test_sudoers_rules(tmp_path: Path, extra: str, status: Status) -> None:
    view = make_view(tmp_path, {"/etc/sudoers": SUDOERS + extra})
    assert check_sudo_nopasswd(ctx(view)).status is status


def test_sudoers_includes(tmp_path: Path) -> None:
    view = make_view(
        tmp_path,
        {
            "/etc/sudoers": SUDOERS + "#includedir /etc/sudoers.d\n@include extra\n",
            "/etc/sudoers.d/ok": "bob ALL=(ALL) ALL\n",
            "/etc/sudoers.d/skip.conf": "eve ALL=(ALL) NOPASSWD: ALL\n",
            "/etc/sudoers.d/skip~": "eve ALL=(ALL) NOPASSWD: ALL\n",
            "/etc/extra": "carol ALL=(ALL) NOPASSWD: ALL\n",
        },
    )
    outcome = check_sudo_nopasswd(ctx(view))
    assert outcome.status is Status.FAIL
    assert any("/etc/extra:1" in e for e in outcome.evidence)
    assert not any("eve" in e for e in outcome.evidence)


def test_sudoers_include_loop(tmp_path: Path) -> None:
    view = make_view(tmp_path, {"/etc/sudoers": SUDOERS + "@include /etc/sudoers\n"})
    outcome = check_sudo_nopasswd(ctx(view))
    assert outcome.status is Status.PASS
    assert any("loop" in e for e in outcome.evidence)


def test_sudo_not_installed(tmp_path: Path) -> None:
    outcome = check_sudo_nopasswd(ctx(make_view(tmp_path, {"/etc/x": ""})))
    assert outcome.status is Status.NOT_APPLICABLE


def test_sudoers_unreadable_dir(tmp_path: Path) -> None:
    view = make_view(
        tmp_path,
        {"/etc/sudoers": SUDOERS + "@includedir /etc/sudoers.d\n", "/etc/sudoers.d/a": ""},
        {"/etc/sudoers.d": {"unreadable": True}},
    )
    outcome = check_sudo_nopasswd(ctx(view, is_root=False))
    assert outcome.status is Status.SKIPPED
    assert outcome.reason == Reason.INSUFFICIENT_PRIVILEGES


# ------------------------------------------------------------------ updates


def test_parse_apt_conf_flat_nested_and_comments() -> None:
    text = """
    // comment
    # also a comment
    /* block
       comment */
    APT::Periodic::Update-Package-Lists "1";
    APT { Periodic { Unattended-Upgrade "0"; }; };
    Acquire::http::Proxy "http://proxy:3128";
    Unattended-Upgrade::Allowed-Origins { "a"; "b"; };
    """
    parsed = parse_apt_conf(text)
    assert parsed["apt::periodic::update-package-lists"] == "1"
    assert parsed["apt::periodic::unattended-upgrade"] == "0"
    assert parsed["acquire::http::proxy"] == "http://proxy:3128"


DPKG = "/var/lib/dpkg/info/unattended-upgrades.list"


@pytest.mark.parametrize(
    ("files", "status"),
    [
        ({}, Status.FAIL),
        ({DPKG: ""}, Status.FAIL),
        ({DPKG: "", "/etc/apt/apt.conf.d/20auto-upgrades":
          'APT::Periodic::Unattended-Upgrade "1";'}, Status.WARN),
        ({DPKG: "", "/etc/apt/apt.conf.d/20auto-upgrades":
          'APT::Periodic::Unattended-Upgrade "always";\nAPT::Periodic::Update-Package-Lists "1";'},
         Status.PASS),
        ({DPKG: "", "/etc/apt/apt.conf.d/20auto-upgrades":
          'APT::Periodic::Unattended-Upgrade "1";\nAPT::Periodic::Update-Package-Lists "1";',
          "/etc/apt/apt.conf.d/99-off": 'APT::Periodic::Unattended-Upgrade "0";'},
         Status.FAIL),  # later file wins
        ({DPKG: "", "/etc/apt/apt.conf.d/20auto-upgrades":
          'APT::Periodic::Unattended-Upgrade "1";\nAPT::Periodic::Update-Package-Lists "1";',
          "/etc/apt/apt.conf.d/99-off.disabled": 'APT::Periodic::Unattended-Upgrade "0";'},
         Status.PASS),  # ignored file name
        ({DPKG: "", "/etc/apt/apt.conf": 'APT::Periodic::Unattended-Upgrade "yes";\n'
          'APT::Periodic::Update-Package-Lists "abc";'}, Status.WARN),
    ],
)  # fmt: skip
def test_unattended_upgrades(tmp_path: Path, files: dict[str, str], status: Status) -> None:
    view = make_view(tmp_path, {"/etc/hostname": "x", **files})
    assert check_unattended_upgrades(ctx(view)).status is status


# ------------------------------------------------------------------ kernel


@pytest.mark.parametrize(
    ("value", "status"),
    [("2", Status.PASS), ("1", Status.WARN), ("0", Status.FAIL), ("7", Status.ERROR)],
)
def test_aslr_values(tmp_path: Path, value: str, status: Status) -> None:
    view = make_view(tmp_path, {"/proc/sys/kernel/randomize_va_space": value + "\n"})
    assert check_aslr(ctx(view)).status is status


def test_aslr_missing(tmp_path: Path) -> None:
    outcome = check_aslr(ctx(make_view(tmp_path, {"/etc/x": ""})))
    assert outcome.status is Status.ERROR
    assert outcome.reason == Reason.UNAVAILABLE


def test_timed_out_command_is_not_ok() -> None:
    assert not CommandResult(returncode=None, stdout="", stderr="", timed_out=True).ok
