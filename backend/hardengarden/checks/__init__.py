"""The check registry. Order here is the order of every report."""

from hardengarden.checks import accounts, filesystem, firewall, kernel, network, ssh, updates
from hardengarden.core.check import Check

ALL_CHECKS: tuple[Check, ...] = (
    *ssh.CHECKS,
    *firewall.CHECKS,
    *network.CHECKS,
    *filesystem.CHECKS,
    *accounts.CHECKS,
    *updates.CHECKS,
    *kernel.CHECKS,
)

__all__ = ["ALL_CHECKS"]
