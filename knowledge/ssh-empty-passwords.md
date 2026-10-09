# SSH empty passwords
<!-- hg:kb checks=HG-SSH-003 -->

## What it is
`PermitEmptyPasswords` decides whether the OpenSSH server lets an account whose password is empty log in with password authentication. The OpenSSH default is `no`. It only has an effect while password authentication is allowed.

HardenGarden reports PASS for `no` and FAIL for `yes`.

## Why it matters
An empty password is no secret at all. If the setting is `yes` and any account has an empty password field, anyone who can reach the SSH port can log in as that account by pressing Enter. Accounts with empty passwords are more common than expected: test users, accounts created by scripts, and accounts copied from old systems.

## How attackers abuse it
- Scanners routinely try logins with an empty password for common account names.
- One account with an empty password gives an attacker an interactive shell, which is the starting point for local privilege escalation.

## How to verify
- Effective value (needs root): `sshd -T` and look for `permitemptypasswords`.
- Without root: read `/etc/ssh/sshd_config` and every included file; the first value read wins.
- Separately, look for accounts whose password field in `/etc/shadow` is empty (needs root). An empty field there means no password is required.

## How to fix
Set `PermitEmptyPasswords no` (or remove the line, since `no` is the default), make sure no drop-in or `Match` block sets it to `yes`, validate with `sshd -t` and reload sshd. Also give every account with an empty password field either a real password or a locked password.

The HardenGarden remediation template for HG-SSH-003 applies the setting in a backed-up, validated way.

## References
- https://man.openbsd.org/sshd_config
- https://man7.org/linux/man-pages/man5/shadow.5.html
