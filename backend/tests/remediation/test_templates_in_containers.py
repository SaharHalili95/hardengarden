"""Run every remediation template inside a disposable container (Phase 3).

For each template: the check FAILs first, a dry run changes nothing, applying makes the
re-scan PASS, a second run is a no-op, and sshd still validates and starts (no lock-out).
Templates are NEVER executed on the host. Run with: ``pytest -m container`` (needs Docker
and root, because the container filesystem is extracted with its real owners for scanning).
"""

from __future__ import annotations

import shutil
import subprocess
import tarfile
import tempfile
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

from hardengarden.checks import ALL_CHECKS
from hardengarden.core.engine import run_scan
from hardengarden.core.models import Status
from hardengarden.core.runner import NullRunner
from hardengarden.core.systemview import SystemView
from hardengarden.remediation import render

pytestmark = pytest.mark.container

HERE = Path(__file__).parent
IMAGE = "hardengarden-remediation-test:latest"
META = {c.meta.id: c.meta for c in ALL_CHECKS}
SCRIPT_IN_BOX = "/root/hardengarden-fix.sh"
SCAN_PATHS = ("etc", "var/lib/dpkg/info", "usr/lib/os-release")


DOCKER = shutil.which("docker") or "docker"


def docker(
    *args: str, stdin: bytes | None = None, check: bool = True
) -> subprocess.CompletedProcess[bytes]:
    argv = [DOCKER, *args]
    return subprocess.run(argv, input=stdin, capture_output=True, check=check, timeout=900)  # noqa: S603  # justification: test harness drives the docker CLI with fixed arguments


@pytest.fixture(scope="session")
def image() -> str:
    docker("build", "-t", IMAGE, str(HERE))
    return IMAGE


@dataclass
class Box:
    name: str

    def exec(
        self, *cmd: str, env: dict[str, str] | None = None, check: bool = False
    ) -> subprocess.CompletedProcess[bytes]:
        flags = [f"--env={k}={v}" for k, v in (env or {}).items()]
        return docker("exec", *flags, self.name, *cmd, check=check)

    def run_template(
        self, check_id: str, *, apply: bool, env: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[bytes]:
        script = render(META[check_id])
        assert script is not None
        docker(
            "exec",
            "-i",
            self.name,
            "sh",
            "-c",
            "cat > /root/hardengarden-fix.sh",
            stdin=script.encode(),
        )
        merged = {"HG_APPLY": "1" if apply else "0", **(env or {})}
        return self.exec("bash", SCRIPT_IN_BOX, env=merged)

    def status(self, check_id: str) -> Status:
        with tempfile.TemporaryDirectory() as tmp:
            dump = docker("exec", self.name, "tar", "-C", "/", "-cf", "-", *SCAN_PATHS)
            archive = Path(tmp) / "fs.tar"
            archive.write_bytes(dump.stdout)
            root = Path(tmp) / "root"
            root.mkdir()
            with tarfile.open(archive) as tar:
                # Our own disposable container: keep exact modes and owners (the "tar"
                # filter would strip the group/other write bits this test needs to see).
                tar.extractall(root, filter="fully_trusted")  # noqa: S202  # justification: archive comes from our own test container
            report = run_scan(SystemView(root), ALL_CHECKS, runner=NullRunner())
            return next(r.status for r in report.results if r.check_id == check_id)

    def sshd_still_works(self) -> None:
        assert self.exec("/usr/sbin/sshd", "-t").returncode == 0
        self.exec("pkill", "-x", "sshd")
        assert self.exec("/usr/sbin/sshd").returncode == 0
        tcp = self.exec("cat", "/proc/net/tcp", "/proc/net/tcp6").stdout.decode()
        assert any(":0016 " in line and line.split()[3] == "0A" for line in tcp.splitlines()[1:])


@pytest.fixture
def box(image: str) -> Iterator[Box]:
    name = f"hg-test-{uuid.uuid4().hex[:10]}"
    docker("run", "-d", "--name", name, "--cap-add=NET_ADMIN", "--cap-add=NET_RAW", image)
    try:
        yield Box(name)
    finally:
        docker("rm", "-f", name, check=False)


FILE_BASED = ["HG-SSH-001", "HG-SSH-002", "HG-SSH-003", "HG-FS-001", "HG-FS-002", "HG-FS-003",
              "HG-ACC-002", "HG-UPD-001", "HG-FW-001"]  # fmt: skip


@pytest.mark.parametrize("check_id", FILE_BASED)
def test_template_fixes_the_finding_without_lockout(box: Box, check_id: str) -> None:
    env = {"SUDO_USER": "alice"}
    assert box.status(check_id) is Status.FAIL

    dry = box.run_template(check_id, apply=False, env=env)
    assert dry.returncode == 0, dry.stderr.decode()
    assert b"DRY RUN" in dry.stdout
    assert box.status(check_id) is Status.FAIL, "a dry run must not change anything"

    applied = box.run_template(check_id, apply=True, env=env)
    assert applied.returncode == 0, applied.stdout.decode() + applied.stderr.decode()
    assert box.status(check_id) is Status.PASS

    again = box.run_template(check_id, apply=True, env=env)
    assert again.returncode == 0, again.stdout.decode() + again.stderr.decode()
    assert b"Nothing to do" in again.stdout or b"already" in again.stdout
    box.sshd_still_works()


def test_uid_zero_template_contains_without_deleting(box: Box) -> None:
    assert box.status("HG-ACC-001") is Status.FAIL
    applied = box.run_template("HG-ACC-001", apply=True)
    assert applied.returncode == 0, applied.stderr.decode()
    passwd = box.exec("getent", "passwd", "toor").stdout.decode()
    assert passwd.startswith("toor:x:0:"), "the account must not be deleted or renumbered"
    assert passwd.rstrip().endswith("nologin")
    assert box.exec("passwd", "-S", "toor").stdout.split()[1] == b"L"
    assert box.status("HG-ACC-001") is Status.WARN  # contained, still reported
    box.sshd_still_works()


def test_aslr_template_persists_the_setting(box: Box) -> None:
    dry = box.run_template("HG-KRN-001", apply=False)
    assert dry.returncode == 0
    assert box.exec("test", "-e", "/etc/sysctl.d/99-hardengarden-aslr.conf").returncode != 0
    applied = box.run_template("HG-KRN-001", apply=True)
    assert applied.returncode == 0, applied.stderr.decode()
    content = box.exec("cat", "/etc/sysctl.d/99-hardengarden-aslr.conf").stdout.decode()
    assert "kernel.randomize_va_space = 2" in content
    assert b"10-insecure.conf lowers this setting" in applied.stdout
    box.sshd_still_works()


def test_password_auth_template_refuses_without_keys(box: Box) -> None:
    box.exec("useradd", "-m", "bob", check=True)
    refused = box.run_template("HG-SSH-002", apply=True, env={"SUDO_USER": "bob"})
    assert refused.returncode != 0
    assert b"has no" in refused.stderr
    assert box.status("HG-SSH-002") is Status.FAIL


def test_root_login_template_refuses_inside_a_root_ssh_session(box: Box) -> None:
    refused = box.run_template(
        "HG-SSH-001", apply=True, env={"SSH_CONNECTION": "10.0.0.1 1 10.0.0.2 22"}
    )
    assert refused.returncode != 0
    assert box.status("HG-SSH-001") is Status.FAIL


def test_sudo_template_refuses_when_user_has_no_password(box: Box) -> None:
    box.exec("passwd", "-d", "alice", check=True)
    refused = box.run_template("HG-ACC-002", apply=True)
    assert refused.returncode != 0
    assert b"no usable password" in refused.stderr
    assert box.status("HG-ACC-002") is Status.FAIL


def test_invalid_sshd_config_is_rolled_back(box: Box) -> None:
    box.exec("sh", "-c", "echo 'ThisIsNotAKeyword yes' >> /etc/ssh/sshd_config", check=True)
    before = box.exec("cat", "/etc/ssh/sshd_config").stdout
    failed = box.run_template("HG-SSH-003", apply=True)
    assert failed.returncode != 0
    assert box.exec("cat", "/etc/ssh/sshd_config").stdout == before
    assert box.exec("test", "-e", "/etc/ssh/sshd_config.d/00-hardengarden.conf").returncode != 0
