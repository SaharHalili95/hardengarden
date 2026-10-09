# Permissions of /etc/shadow
<!-- hg:kb checks=HG-FS-001 -->

## What it is
`/etc/shadow` stores the password hashes and password-ageing data for local accounts, one line per account with nine colon-separated fields. On Ubuntu and Debian the file is normally owned by `root`, group `shadow`, with mode `0640`: root can read and write, members of the `shadow` group (used by a few authentication helpers) can read, and nobody else has any access.

HardenGarden reports FAIL if the owner is not root, the group is neither `root` nor `shadow`, the group can write, others have any permission, special bits are set, or the path is not a regular file.

## Why it matters
The shadow file must not be readable by regular users if passwords are to stay secret. Anyone who can read it can copy the hashes and attack them offline, at full speed, without any login rate limit or lockout. Anyone who can write it can set a known password for any account, including root.

## How attackers abuse it
- A readable shadow file lets a low-privileged user copy the hashes and crack weak passwords on their own hardware.
- A writable shadow file allows replacing root's hash and logging in as root.
- Backups or copies of the file with loose permissions leak the same information.

## How to verify
- `stat /etc/shadow` shows owner, group and mode (no root needed).
- Expected: owner `root`, group `shadow` (or `root`), mode `0640` or stricter, a regular file and not a symlink.
- Also look for stray copies such as `/etc/shadow-` (the backup kept by the shadow tools) and make sure they are equally restricted.

## How to fix
Restore the owner to `root:shadow` and the mode to `0640`. Then find out how the permissions changed: a misbehaving script, a manual edit or an attacker. If the file was readable by others for any length of time, treat the hashes as exposed and change the passwords of the affected accounts.

The HardenGarden remediation template for HG-FS-001 records the old values, then sets owner and mode.

## References
- https://man7.org/linux/man-pages/man5/shadow.5.html
- https://man7.org/linux/man-pages/man1/chmod.1.html
