"""Listening-service inventory: HG-NET-001.

Reads ``/proc/net/{tcp,tcp6,udp,udp6}`` through :class:`SystemView` (no subprocess, no
root needed). Sockets bound to loopback are ignored. Anything else that is not in the
expected set is reported as WARN: it may be legitimate, but it deserves a look.
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass

from hardengarden.core.check import Check, CheckContext, Outcome
from hardengarden.core.models import ANY_LINUX, Category, CheckMeta, Reason, Severity
from hardengarden.core.systemview import SystemViewError

# Services that a typical server is expected to expose on the network.
EXPECTED: frozenset[tuple[str, int]] = frozenset(
    {
        ("tcp", 22),  # OpenSSH
        ("udp", 68),  # DHCPv4 client
        ("udp", 546),  # DHCPv6 client
    }
)
IPV4_BYTES = 4
IPV6_BYTES = 16
MIN_FIELDS = 4
_TCP_LISTEN = "0A"
_UDP_UNCONNECTED = "07"
_SOURCES = (
    ("tcp", "/proc/net/tcp"),
    ("tcp", "/proc/net/tcp6"),
    ("udp", "/proc/net/udp"),
    ("udp", "/proc/net/udp6"),
)


@dataclass(frozen=True, slots=True, order=True)
class Listener:
    proto: str
    address: str
    port: int

    def __str__(self) -> str:
        host = f"[{self.address}]" if ":" in self.address else self.address
        return f"{self.proto} {host}:{self.port}"


def _decode_address(hex_addr: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    raw = bytes.fromhex(hex_addr)
    if len(raw) == IPV4_BYTES:
        return ipaddress.IPv4Address(raw[::-1])
    if len(raw) == IPV6_BYTES:
        words = b"".join(raw[i : i + 4][::-1] for i in range(0, IPV6_BYTES, IPV4_BYTES))
        return ipaddress.IPv6Address(words)
    msg = f"unexpected address length: {hex_addr!r}"
    raise ValueError(msg)


def _is_loopback(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        return ip.ipv4_mapped.is_loopback
    return ip.is_loopback


def parse_proc_net(proto: str, text: str) -> list[Listener]:
    listeners: list[Listener] = []
    for line in text.splitlines()[1:]:
        fields = line.split()
        if len(fields) < MIN_FIELDS or ":" not in fields[1] or ":" not in fields[2]:
            continue
        local, remote, state = fields[1], fields[2], fields[3].upper()
        if proto == "tcp" and state != _TCP_LISTEN:
            continue
        if proto == "udp" and (state != _UDP_UNCONNECTED or not remote.endswith(":0000")):
            continue
        addr_hex, _, port_hex = local.partition(":")
        try:
            ip = _decode_address(addr_hex)
            port = int(port_hex, 16)
        except ValueError:
            continue
        if not _is_loopback(ip):
            listeners.append(Listener(proto, str(ip), port))
    return listeners


def check_listeners(ctx: CheckContext) -> Outcome:
    found: set[Listener] = set()
    readable = 0
    for proto, path in _SOURCES:
        try:
            text = ctx.view.read_text(path)
        except SystemViewError:
            continue
        readable += 1
        found.update(parse_proc_net(proto, text))
    if readable == 0:
        return Outcome.error(Reason.UNAVAILABLE, "/proc/net socket tables are not readable")
    unexpected = sorted(item for item in found if (item.proto, item.port) not in EXPECTED)
    expected = sorted(item for item in found if (item.proto, item.port) in EXPECTED)
    if unexpected:
        return Outcome.warn(
            f"{len(unexpected)} unexpected non-loopback listener(s)",
            *(str(item) for item in unexpected),
        )
    summary = ", ".join(str(item) for item in expected) or "none"
    return Outcome.passed(f"only expected non-loopback listeners: {summary}")


CHECKS = (
    Check(
        CheckMeta(
            id="HG-NET-001",
            title="Listening services on non-loopback interfaces",
            category=Category.NETWORK,
            severity=Severity.MEDIUM,
            rationale="Every service listening on a network interface is attack surface. "
            "Services that only local programs use should listen on loopback.",
            requires_root=False,
            platforms=(ANY_LINUX,),
            kb_doc="knowledge/listening-services.md",
            remediation_template=None,
        ),
        check_listeners,
    ),
)
