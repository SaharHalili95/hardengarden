# Permissions of /etc/passwd and /etc/group
<!-- hg:kb checks=HG-FS-002 -->

## What it is
`/etc/passwd` lists every local account (name, UID, primary GID, comment, home directory and shell) and `/etc/group` lists groups and their members. Both must be **readable** by everyone, because ordinary programs such as `ls` need them to turn numeric IDs into names. Only root should be able to **write** them. The expected state is owner `root:root` and mode `0644`.

HardenGarden reports FAIL if either file is writable by group or others, is not owned by `root:root`, carries special permission bits, or is not a regular file.

## Why it matters
Whoever can write `/etc/passwd` decides who exists on the system and with which UID. Whoever can write `/etc/group` decides who belongs to privileged groups such as `sudo`. Either one is a direct route to root.

## How attackers abuse it
- Adding a new line with UID 0 creates a second root account (see HG-ACC-001).
- Changing an existing user's UID to 0, or changing root's shell or home, takes over or disrupts root.
- Adding a user to the `sudo` group in `/etc/group` grants administrative rights.

## How to verify
- `stat /etc/passwd /etc/group` shows owner, group and mode (no root needed).
- Expected for both: owner `root`, group `root`, mode `0644`, a regular file.

## How to fix
Set owner `root:root` and mode `0644` on both files. Then review both files for unexpected entries, since a period of write access may already have been used: look for unknown accounts, accounts with UID 0 and unexpected members of privileged groups.

The HardenGarden remediation template for HG-FS-002 records the old values, then sets owner and mode.

## References
- https://man7.org/linux/man-pages/man5/passwd.5.html
- https://man7.org/linux/man-pages/man1/chmod.1.html
