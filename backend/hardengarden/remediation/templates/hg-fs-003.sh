#!/usr/bin/env bash
set -euo pipefail

APPLY="${HG_APPLY:-0}"
say() { printf '[hardengarden] %s\n' "$*"; }
die() { printf '[hardengarden] ERROR: %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "run as root (for example: sudo HG_APPLY=1 bash $0)"

mapfile -d '' items < <(find /etc -xdev \( -type f -o -type d \) -perm -0002 -print0)
if [ "${#items[@]}" -eq 0 ]; then
    say "No world-writable files or directories under /etc. Nothing to do."
    exit 0
fi

say "Found ${#items[@]} world-writable item(s) under /etc:"
for item in "${items[@]}"; do
    say "  $(stat -c '%A %U:%G' "$item")  $item"
done

if [ "$APPLY" != "1" ]; then
    say "DRY RUN: would remove only the write permission for others (chmod o-w) from each item."
    say "Nothing was changed. Re-run with HG_APPLY=1 to apply."
    exit 0
fi

for item in "${items[@]}"; do
    chmod o-w "$item"
    say "chmod o-w $item -> $(stat -c '%A' "$item")"
done
say "Done. Check who should own each file, and review its content for unexpected changes."
