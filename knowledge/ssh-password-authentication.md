# SSH password authentication
<!-- hg:kb checks=HG-SSH-002 -->

## What it is
`PasswordAuthentication` controls whether the OpenSSH server accepts passwords. When it is not set, the OpenSSH default is `yes`. The related setting `KbdInteractiveAuthentication` (formerly `ChallengeResponseAuthentication`) can also end up asking for a password through PAM, so both are worth looking at together.

HardenGarden reports PASS when password authentication is disabled and FAIL when it is enabled. A `Match` block that turns it back on for some users or addresses is reported as a WARN ("conditional override").

## Why it matters
A password is a short secret that a person chose, often reused and sometimes guessable. Anything reachable over the network that accepts passwords can be attacked from anywhere, at scale, for free. Public-key authentication replaces that with a long random secret that never crosses the network, which removes guessing attacks entirely.

## How attackers abuse it
- Automated scanners try common and leaked username/password pairs against every SSH server they find, continuously.
- Credential stuffing reuses passwords leaked from unrelated websites.
- A weak password on a single forgotten account is enough for a foothold, which is then used to escalate privileges locally.

## How to verify
- Effective value (needs root): `sshd -T` and look for `passwordauthentication` and `kbdinteractiveauthentication`.
- Without root: read `/etc/ssh/sshd_config` and its included files. Cloud images often set this in a drop-in such as `50-cloud-init.conf`; remember that the first value read wins.
- Check for `Match` blocks that set `PasswordAuthentication yes` for specific users or networks.

## How to fix
1. Make sure every person who needs access has a working SSH key. Generate one on their own machine (for example an Ed25519 key with `ssh-keygen`) and add the public key to `~/.ssh/authorized_keys` on the server. sshd ignores that file if it, `~/.ssh` or the home directory is writable by others.
2. Test a key-based login in a **new** session while keeping the current one open.
3. Set `PasswordAuthentication no` (and consider `KbdInteractiveAuthentication no`) so it is the first value sshd reads, validate with `sshd -t`, then reload sshd.

The HardenGarden remediation template for HG-SSH-002 refuses to apply the change if the invoking user has no authorized keys, to avoid locking you out.

## References
- https://man.openbsd.org/sshd_config
- https://man.openbsd.org/sshd
- https://man.openbsd.org/ssh-keygen
