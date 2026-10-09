# Passwordless sudo (NOPASSWD)
<!-- hg:kb checks=HG-ACC-002 -->

## What it is
sudo normally asks users to authenticate before running a command with elevated rights. Two things switch that off: the `NOPASSWD:` tag on a rule in `/etc/sudoers` or a file it includes, and the `authenticate` flag turned off with `Defaults !authenticate`. Sudoers files can pull in others with `@include` and `@includedir` (or the older `#include` and `#includedir` forms); files in an included directory are skipped if their name contains a `.` or ends with `~`.

HardenGarden reads `/etc/sudoers` and everything it includes, the same way sudo does, and reports FAIL for each passwordless rule. The sudoers files are readable only by root, so the check is skipped without root.

## Why it matters
With passwordless sudo, anything that can run code as that user can run code as root. The user's password is the barrier that stops a compromised browser, a malicious package installed in the user's home directory, or a stolen SSH key from becoming full root access.

## How attackers abuse it
- After getting a shell as a user (stolen key, vulnerable web app running as that user), an attacker checks `sudo -l`; a NOPASSWD rule means immediate root.
- Rules that allow passwordless sudo for "harmless" programs are often escapable, because many programs can start a shell or write arbitrary files.
- Cloud images often add a NOPASSWD rule for the default user; it is easy to forget once real users are created.

## How to verify
- As root, read `/etc/sudoers` and every file under `/etc/sudoers.d/` (and any other included file) and look for `NOPASSWD:` and `!authenticate`.
- `sudo -l` shows the rules that apply to the current user.

## How to fix
Remove the `NOPASSWD:` tag (or the `!authenticate` default) from rules that do not truly need it, and give the affected users a password. Always edit sudoers with `visudo` (or `visudo -f FILE` for an included file) so syntax errors are caught; a broken sudoers file can lock everyone out of sudo. Keep a root shell open until you have tested `sudo` in a new session. If automation genuinely needs passwordless access, limit it to a dedicated account and exact command lines.

The HardenGarden remediation template for HG-ACC-002 shows each rule and, only when you explicitly ask, comments it out and validates the result with `visudo -c`.

## References
- https://www.sudo.ws/docs/man/sudoers.man/
