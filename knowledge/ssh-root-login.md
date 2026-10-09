# SSH root login
<!-- hg:kb checks=HG-SSH-001 -->

## What it is
`PermitRootLogin` is an OpenSSH server setting that decides whether the `root` account may log in over SSH, and with which authentication methods. It accepts `yes`, `prohibit-password` (its older spelling is `without-password`), `forced-commands-only` and `no`. If the setting is absent, OpenSSH uses `prohibit-password`: root may log in with a key, but not with a password.

HardenGarden reports PASS for `no`, WARN for the key-only variants and FAIL for `yes`.

## Why it matters
Root is the one account name that exists on every Linux machine, so it is the first name automated attacks try. A successful root login also skips the step where an administrator logs in as themselves and then elevates with sudo. That step matters: it leaves a record of which person used administrative rights, and it adds a second secret (the user's password) between a stolen key and full control.

Allowing root with keys only is far better than allowing passwords, but it still means a single leaked private key gives immediate, unattributed root access.

## How attackers abuse it
- Brute-force and password-spraying bots target `root` constantly on any internet-facing SSH port.
- A private key copied from a laptop, a backup or a CI system that is authorized for root grants instant full control, with no further barrier.
- Shared root keys make it impossible to tell afterwards which person, or which stolen key, was used.

## How to verify
- Effective value (needs root): run `sshd -T` and look for the `permitrootlogin` line. This reflects defaults, `Include` files and ordering.
- Without root: read `/etc/ssh/sshd_config` and every file it includes (on Ubuntu and Debian typically `/etc/ssh/sshd_config.d/*.conf`). Remember that for each keyword the **first** value OpenSSH reads wins, and that `Match` blocks can override the global value for some users or addresses.

## How to fix
Set `PermitRootLogin no` so that it is the first value sshd reads, for example in a drop-in file under `/etc/ssh/sshd_config.d/` whose name sorts first. Make sure at least one non-root administrator can log in and use sudo **before** reloading sshd. Validate the configuration with `sshd -t` before reloading, and keep an existing session open until a new login has been tested.

Use the HardenGarden remediation template for HG-SSH-001: it backs up files, validates the configuration and only applies changes when you explicitly ask it to.

## References
- https://man.openbsd.org/sshd_config
- https://man.openbsd.org/sshd
