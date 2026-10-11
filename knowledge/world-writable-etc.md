# World-writable files under /etc
<!-- hg:kb checks=HG-FS-003 -->

## What it is
A file or directory is world-writable when the "others" write bit is set (the last `w` in `ls -l` output, or `0002` in octal). Everything under `/etc` is system configuration read by services, many of them running as root. None of it should be writable by every local user.

HardenGarden walks `/etc` without following symbolic links (whose own mode bits are meaningless) and reports FAIL for every world-writable regular file or directory, listing up to nine of them.

## Why it matters
If any local user can change a file that a privileged service reads, that user can change what the service does. If any user can write a directory, they can add or replace files in it, even files they do not own, unless the sticky bit is set.

## How attackers abuse it
- A world-writable file in `/etc/cron.d` or a world-writable script referenced from it gives root code execution at the next scheduled run.
- World-writable service configuration lets an attacker point a root service at their own scripts or libraries.
- A world-writable directory such as `/etc/profile.d` lets an attacker add a script that runs in every administrator's login shell.

## How to verify
- `find /etc -xdev -perm -0002 -type f` and the same with `-type d` list world-writable files and directories. `-perm -0002` matches anything with the others-write bit set, whatever its other bits.
- Without root a few directories under `/etc` (for example private key directories) cannot be read; HardenGarden reports how many it could not inspect.

## How to fix
For each listed path, remove the others-write bit (`chmod o-w`), then check who is supposed to own and write it, and fix the owner if needed. Investigate how it became world-writable: an installer or script with a wrong `umask` or mode is a common cause. If a file was writable for some time, review its content for unexpected changes.

The HardenGarden remediation template for HG-FS-003 lists every world-writable entry under `/etc` and removes only the others-write bit.

## References
- https://manpages.debian.org/bookworm/coreutils/chmod.1.en.html
- https://manpages.debian.org/bookworm/findutils/find.1.en.html
