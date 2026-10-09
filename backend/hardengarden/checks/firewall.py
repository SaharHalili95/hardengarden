"""Host firewall check: HG-FW-001."""

from __future__ import annotations

import re

from hardengarden.core.check import Check, CheckContext, Outcome
from hardengarden.core.models import ANY_LINUX, Category, CheckMeta, Severity
from hardengarden.core.runner import Command
from hardengarden.core.systemview import SystemViewError

UFW_CONF = "/etc/ufw/ufw.conf"
NFT_CONF = "/etc/nftables.conf"
NFT_SERVICE_LINKS = (
    "/etc/systemd/system/sysinit.target.wants/nftables.service",
    "/etc/systemd/system/multi-user.target.wants/nftables.service",
)
_INPUT_HOOK = re.compile(r"\bhook\s+input\b")
_UFW_ENABLED = re.compile(r"^\s*ENABLED\s*=\s*\"?yes\"?\s*$", re.I | re.M)


def _live(ctx: CheckContext) -> Outcome | None:
    ufw = ctx.runner.run(Command.UFW_STATUS)
    if ufw is not None and ufw.ok and re.search(r"^Status:\s*active\b", ufw.stdout, re.M):
        return Outcome.passed("ufw status: active")
    nft = ctx.runner.run(Command.NFT_RULESET)
    if nft is not None and nft.ok:
        hooks = len(_INPUT_HOOK.findall(nft.stdout))
        if hooks:
            return Outcome.passed(f"nftables ruleset loaded with {hooks} input-hook chain(s)")
    if ufw is None and nft is None:
        return None  # no tooling at all; fall back to configuration files
    evidence = []
    if ufw is not None:
        evidence.append("ufw installed but not active")
    if nft is not None:
        evidence.append("no nftables chain hooked on input")
    return Outcome.failed(*evidence)


def _from_config(ctx: CheckContext) -> Outcome:
    note = "from configuration files; runtime state not verified"
    try:
        if _UFW_ENABLED.search(ctx.view.read_text(UFW_CONF)):
            return Outcome.passed(f"ufw enabled in {UFW_CONF} ({note})")
    except SystemViewError:
        pass
    try:
        rules = ctx.view.read_text(NFT_CONF)
    except SystemViewError:
        rules = ""
    service_enabled = any(ctx.view.exists(link) for link in NFT_SERVICE_LINKS)
    if _INPUT_HOOK.search(rules) and service_enabled:
        return Outcome.passed(
            f"nftables.service enabled with input-hook rules in {NFT_CONF} ({note})"
        )
    evidence = ["no enabled ufw configuration"]
    if _INPUT_HOOK.search(rules):
        evidence.append(f"{NFT_CONF} has input rules but nftables.service is not enabled")
    else:
        evidence.append("no nftables input rules configured")
    return Outcome.failed(*evidence)


def check_firewall(ctx: CheckContext) -> Outcome:
    if ctx.live_host:
        live = _live(ctx)
        if live is not None:
            return live
    return _from_config(ctx)


CHECKS = (
    Check(
        CheckMeta(
            id="HG-FW-001",
            title="Host firewall active",
            category=Category.FIREWALL,
            severity=Severity.HIGH,
            rationale="Without a host firewall every listening service is reachable from the "
            "network, including ones that were only meant for local use.",
            requires_root=True,
            platforms=(ANY_LINUX,),
            kb_doc="knowledge/host-firewall.md",
            remediation_template="hg-fw-001.sh",
        ),
        check_firewall,
    ),
)
