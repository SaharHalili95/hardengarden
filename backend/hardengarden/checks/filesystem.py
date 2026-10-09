"""Filesystem permission checks: HG-FS-001..003."""

from __future__ import annotations

from hardengarden.checks.etcfiles import lookup_group_ids
from hardengarden.core.check import Check, CheckContext, Outcome
from hardengarden.core.models import ANY_LINUX, Category, CheckMeta, Reason, Severity
from hardengarden.core.systemview import FileInfo, FileKind, NotFoundError

_SPECIAL_BITS = 0o7000


def _describe(info: FileInfo, groups: dict[str, int]) -> str:
    names = {gid: name for name, gid in groups.items()}
    group = names.get(info.gid, str(info.gid))
    return f"{info.path}: mode {info.mode:04o}, owner uid {info.uid}, group {group}"


def check_shadow(ctx: CheckContext) -> Outcome:
    path = "/etc/shadow"
    try:
        info = ctx.view.stat(path)
    except NotFoundError:
        return Outcome.error(Reason.FILE_MISSING, f"{path} does not exist")
    groups = lookup_group_ids(ctx.view)
    allowed_gids = {0} | ({groups["shadow"]} if "shadow" in groups else set())
    problems: list[str] = []
    if info.kind is not FileKind.FILE:
        problems.append(f"{path} is a {info.kind.value}, expected a regular file")
    if info.uid != 0:
        problems.append("owner is not root")
    if info.gid not in allowed_gids:
        problems.append("group is neither root nor shadow")
    if info.mode & 0o037:
        problems.append("group may write/execute or others have access (expect 0640 or stricter)")
    if info.mode & _SPECIAL_BITS:
        problems.append("setuid/setgid/sticky bit set")
    evidence = [_describe(info, groups)]
    if problems:
        return Outcome.failed(*evidence, *problems)
    return Outcome.passed(*evidence)


def check_passwd_group(ctx: CheckContext) -> Outcome:
    groups = lookup_group_ids(ctx.view)
    evidence: list[str] = []
    problems: list[str] = []
    for path in ("/etc/passwd", "/etc/group"):
        try:
            info = ctx.view.stat(path)
        except NotFoundError:
            return Outcome.error(Reason.FILE_MISSING, f"{path} does not exist")
        evidence.append(_describe(info, groups))
        if info.kind is not FileKind.FILE:
            problems.append(f"{path} is a {info.kind.value}, expected a regular file")
        if info.uid != 0 or info.gid != 0:
            problems.append(f"{path} is not owned by root:root")
        if info.mode & 0o022:
            problems.append(f"{path} is writable by group or others (expect 0644)")
        if info.mode & _SPECIAL_BITS:
            problems.append(f"{path} has setuid/setgid/sticky bits")
    if problems:
        return Outcome.failed(*problems, *evidence)
    return Outcome.passed(*evidence)


def check_world_writable_etc(ctx: CheckContext) -> Outcome:
    walk = ctx.view.walk("/etc")
    flagged = sorted(
        entry.path
        for entry in walk.entries
        if entry.kind in {FileKind.FILE, FileKind.DIR} and entry.mode & 0o002
    )
    notes: list[str] = []
    if walk.unreadable_dirs:
        notes.append(
            f"{len(walk.unreadable_dirs)} director(ies) under /etc could not be read"
            + ("" if ctx.is_root else " without root")
        )
    if walk.truncated:
        notes.append("walk stopped at the entry limit; results may be incomplete")
    if flagged:
        return Outcome.failed(f"{len(flagged)} world-writable item(s) under /etc", *flagged, *notes)
    return Outcome.passed(
        f"no world-writable files or directories in {len(walk.entries)} entries", *notes
    )


def _meta(check_id: str, title: str, severity: Severity, rationale: str, slug: str) -> CheckMeta:
    return CheckMeta(
        id=check_id,
        title=title,
        category=Category.FILESYSTEM,
        severity=severity,
        rationale=rationale,
        requires_root=False,
        platforms=(ANY_LINUX,),
        kb_doc=f"knowledge/{slug}.md",
        remediation_template=f"{check_id.lower()}.sh",
    )


CHECKS = (
    Check(
        _meta(
            "HG-FS-001",
            "/etc/shadow permissions and owner",
            Severity.CRITICAL,
            "/etc/shadow holds password hashes. If other users can read it, they can crack the "
            "hashes offline; if they can write it, they can set any password.",
            "shadow-permissions",
        ),
        check_shadow,
    ),
    Check(
        _meta(
            "HG-FS-002",
            "/etc/passwd and /etc/group permissions",
            Severity.HIGH,
            "These files define every account and group. If a non-root user can modify them, "
            "they can create a root-equivalent account or join privileged groups.",
            "passwd-group-permissions",
        ),
        check_passwd_group,
    ),
    Check(
        _meta(
            "HG-FS-003",
            "World-writable files under /etc",
            Severity.MEDIUM,
            "Files under /etc configure system services. A world-writable one lets any local "
            "user change how a privileged service behaves.",
            "world-writable-etc",
        ),
        check_world_writable_etc,
    ),
)
