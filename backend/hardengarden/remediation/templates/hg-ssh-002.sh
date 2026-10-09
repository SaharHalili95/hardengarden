#!/usr/bin/env bash
set -euo pipefail

KEY="PasswordAuthentication"
VALUE="no"
SSH_DIR=/etc/ssh
MAIN="$SSH_DIR/sshd_config"
DROPIN_DIR="$SSH_DIR/sshd_config.d"
DROPIN="$DROPIN_DIR/00-hardengarden.conf"
STAMP="$(date +%Y%m%d%H%M%S)"
APPLY="${HG_APPLY:-0}"

say() { printf '[hardengarden] %s\n' "$*"; }
die() { printf '[hardengarden] ERROR: %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "run as root (for example: sudo HG_APPLY=1 bash $0)"
[ -f "$MAIN" ] || die "$MAIN not found; is the OpenSSH server installed?"
SSHD="$(command -v sshd || echo /usr/sbin/sshd)"
[ -x "$SSHD" ] || die "sshd binary not found"

effective() { "$SSHD" -T 2>/dev/null | awk -v k="$(printf '%s' "$KEY" | tr '[:upper:]' '[:lower:]')" '$1 == k { print $2; exit }'; }

# sshd needs its runtime privilege-separation directory to validate configuration.
if [ "$APPLY" = "1" ] && [ ! -d /run/sshd ]; then mkdir -m 0755 /run/sshd; fi

current="$(effective || true)"
if [ "$current" = "$VALUE" ]; then
    say "$KEY is already '$VALUE'. Nothing to do."
    exit 0
fi
say "$KEY is currently '${current:-unknown}'; target is '$VALUE'."

# Lock-out guard: refuse unless the invoking user has an SSH key to log in with.
target_user="${SUDO_USER:-root}"
home_dir="$(getent passwd "$target_user" | cut -d: -f6)"
if [ "${HG_FORCE:-0}" != "1" ] && ! [ -s "$home_dir/.ssh/authorized_keys" ]; then
    die "user '$target_user' has no $home_dir/.ssh/authorized_keys. Add a key and test it first, or set HG_FORCE=1"
fi
uses_dropins=0
if grep -Eiq '^[[:space:]]*Include[[:space:]]+(/etc/ssh/)?sshd_config\.d/\*\.conf' "$MAIN"; then
    uses_dropins=1
fi

if [ "$APPLY" != "1" ]; then
    if [ "$uses_dropins" -eq 1 ]; then
        say "DRY RUN: would set '$KEY $VALUE' in $DROPIN (read before other drop-ins)."
    else
        say "DRY RUN: would comment out existing $KEY lines in $MAIN and add '$KEY $VALUE' at the top."
    fi
    say "DRY RUN: would validate with 'sshd -t' and reload the SSH service."
    say "Nothing was changed. Re-run with HG_APPLY=1 to apply."
    exit 0
fi

backup() { if [ -e "$1" ]; then cp -a "$1" "$1.hardengarden-bak.$STAMP"; say "Backed up $1 to $1.hardengarden-bak.$STAMP"; fi; }
restore() {
    for f in "$MAIN" "$DROPIN"; do
        if [ -e "$f.hardengarden-bak.$STAMP" ]; then cp -a "$f.hardengarden-bak.$STAMP" "$f"; fi
    done
    if [ "$created_dropin" -eq 1 ]; then rm -f "$DROPIN"; fi
}

created_dropin=0
if [ "$uses_dropins" -eq 1 ]; then
    mkdir -p "$DROPIN_DIR"
    if [ -e "$DROPIN" ]; then backup "$DROPIN"; else created_dropin=1; : > "$DROPIN"; chmod 0644 "$DROPIN"; fi
    tmp="$(mktemp)"
    grep -Eiv "^[[:space:]]*$KEY([[:space:]]|=)" "$DROPIN" > "$tmp" || true
    { printf '# Managed by HardenGarden. Values here win because this file is read first.\n'; grep -v '^# Managed by HardenGarden' "$tmp" || true; printf '%s %s\n' "$KEY" "$VALUE"; } > "$DROPIN"
    rm -f "$tmp"
    say "Set '$KEY $VALUE' in $DROPIN"
else
    backup "$MAIN"
    sed -i -E "s/^([[:space:]]*$KEY([[:space:]]|=).*)$/# \1  # disabled by HardenGarden/I" "$MAIN"
    sed -i "1i $KEY $VALUE" "$MAIN"
    say "Added '$KEY $VALUE' at the top of $MAIN and commented out older lines"
fi

if ! "$SSHD" -t; then
    restore
    die "sshd -t rejected the new configuration; all changes were rolled back"
fi
now="$(effective || true)"
if [ "$now" != "$VALUE" ]; then
    restore
    die "the effective value is '$now', not '$VALUE' (another file may override it); rolled back"
fi
say "Validated: sshd -T now reports $KEY $VALUE"

if command -v systemctl >/dev/null 2>&1 && systemctl is-active --quiet ssh 2>/dev/null; then
    systemctl reload ssh && say "Reloaded ssh.service (existing sessions stay open)."
elif command -v systemctl >/dev/null 2>&1 && systemctl is-active --quiet sshd 2>/dev/null; then
    systemctl reload sshd && say "Reloaded sshd.service (existing sessions stay open)."
else
    say "SSH service is not running under systemd; the new setting applies when sshd next starts."
fi
say "Done. Keep your current session open and test a new login before logging out."
