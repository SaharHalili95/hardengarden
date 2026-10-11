# Accounts with UID 0 other than root
<!-- hg:kb checks=HG-ACC-001 -->

## What it is
The kernel grants superuser privileges based on the numeric user ID, not on the name. UID 0 is the superuser. The account conventionally called `root` has UID 0, and on a normal system it is the only one. Any other entry in `/etc/passwd` with UID 0 is root under another name.

HardenGarden parses `/etc/passwd` (readable without root) and reports FAIL for every account other than `root` with UID 0. Malformed lines are skipped and counted.

## Why it matters
An extra UID 0 account has all of root's power but is easy to miss: it does not look like root in an account list, it may have its own password, and it may not be covered by policies that only mention the name `root` (for example SSH's `PermitRootLogin`).

## How attackers abuse it
- After gaining root once, attackers add an innocent-looking account such as `toor`, `backup` or `support` with UID 0 to keep access later.
- Because policies and monitoring often key on the name `root`, logins through the extra account may go unnoticed.

## How to verify
- List all accounts with UID 0 by reading the third field of `/etc/passwd`; only `root` should appear.
- For any extra account, check when it was added, whether it has a password in `/etc/shadow`, its shell, and any SSH keys in its home directory.

## How to fix
Treat an unexpected UID 0 account as a possible sign of compromise:
1. Do not simply delete it first. Record its details for investigation.
2. Lock it (lock the password and set an expiry date) so it can no longer be used.
3. Investigate how and when it was created and look for other persistence (SSH keys, cron jobs, services).
4. If it is a legitimate but badly designed admin account, replace it with a normal account plus sudo, then remove it.

The HardenGarden remediation template for HG-ACC-001 lists the accounts and, only when you explicitly ask, locks them. It never deletes accounts or changes UIDs.

## References
- https://manpages.debian.org/bookworm/passwd/passwd.5.en.html
- https://manpages.debian.org/bookworm/passwd/usermod.8.en.html
