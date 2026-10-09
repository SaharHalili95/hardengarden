#!/usr/bin/env bash
set -euo pipefail

APPLY="${HG_APPLY:-0}"
say() { printf '[hardengarden] %s\n' "$*"; }
die() { printf '[hardengarden] ERROR: %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "run as root (for example: sudo HG_APPLY=1 bash $0)"

if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -q '^Status: active'; then
    say "ufw is already active. Nothing to do."
    exit 0
fi

# Collect the SSH ports so enabling the firewall can never cut off remote access.
ssh_ports=""
if command -v sshd >/dev/null 2>&1; then
    ssh_ports="$(sshd -T 2>/dev/null | awk '$1 == "port" { print $2 }' | sort -un | tr '\n' ' ')"
fi
if [ -z "$ssh_ports" ] && [ -f /etc/ssh/sshd_config ]; then
    ssh_ports="22"
fi

if [ "$APPLY" != "1" ]; then
    command -v ufw >/dev/null 2>&1 || say "DRY RUN: would install the ufw package with apt-get."
    for port in $ssh_ports; do say "DRY RUN: would allow incoming TCP port $port (SSH) before enabling."; done
    say "DRY RUN: would enable ufw (default: deny incoming, allow outgoing) and make it start at boot."
    say "Other services that must stay reachable need their own 'ufw allow' rules: review first."
    say "Nothing was changed. Re-run with HG_APPLY=1 to apply."
    exit 0
fi

if ! command -v ufw >/dev/null 2>&1; then
    say "Installing ufw"
    apt-get update
    DEBIAN_FRONTEND=noninteractive apt-get install -y ufw
fi
for port in $ssh_ports; do
    ufw allow "$port/tcp" comment 'SSH (added by HardenGarden)'
    say "Allowed incoming TCP port $port (SSH)"
done
ufw default deny incoming
ufw default allow outgoing
ufw --force enable
say "ufw enabled. Current rules:"
ufw status verbose
say "Done. Test a new SSH login before closing this session."
