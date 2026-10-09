#!/usr/bin/env bash
set -euo pipefail

APPLY="${HG_APPLY:-0}"
say() { printf '[hardengarden] %s\n' "$*"; }
die() { printf '[hardengarden] ERROR: %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "run as root (for example: sudo HG_APPLY=1 bash $0)"

mapfile -t accounts < <(awk -F: '$3 == "0" && $1 != "root" { print $1 }' /etc/passwd)
if [ "${#accounts[@]}" -eq 0 ]; then
    say "root is the only account with UID 0. Nothing to do."
    exit 0
fi

say "Accounts with UID 0 other than root (treat as a possible compromise):"
for account in "${accounts[@]}"; do
    say "  $(getent passwd "$account")"
done
say "This script never deletes accounts or changes UIDs. Investigate before removing anything."

if [ "$APPLY" != "1" ]; then
    say "DRY RUN: would lock the password, expire the account and set the shell to nologin."
    say "Nothing was changed. Re-run with HG_APPLY=1 to apply."
    exit 0
fi

nologin="$(command -v nologin || echo /usr/sbin/nologin)"
for account in "${accounts[@]}"; do
    usermod --lock --expiredate 1 --shell "$nologin" -- "$account"
    say "Locked and expired '$account' (shell set to $nologin)"
done
say "Done. Look for other persistence: SSH keys, cron jobs and services owned by these accounts."
