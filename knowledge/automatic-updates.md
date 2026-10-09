# Automatic security updates
<!-- hg:kb checks=HG-UPD-001 -->

## What it is
On Ubuntu and Debian, the `unattended-upgrades` package installs available updates automatically, by default only from the security sources. Two APT settings, usually in `/etc/apt/apt.conf.d/20auto-upgrades`, switch it on:
- `APT::Periodic::Update-Package-Lists` refreshes the package lists,
- `APT::Periodic::Unattended-Upgrade` installs the upgrades.

Each value is an interval in days: `"1"` means daily and `"0"` disables it. Which sources are used and other behaviour live in `/etc/apt/apt.conf.d/50unattended-upgrades`. Ubuntu installs and enables this by default; minimal or customised images may not.

HardenGarden reports PASS when the package is installed and both settings are enabled, WARN when upgrades are enabled but package lists are not refreshed, and FAIL otherwise. APT reads the files in `/etc/apt/apt.conf.d/` in name order, and a later value wins.

## Why it matters
Most real-world compromises exploit vulnerabilities that already have a fix. The time between a fix being published and being installed is the window of exposure, and manual patching tends to stretch that window to weeks. Automatic security updates shrink it to about a day without relying on anyone remembering.

## How attackers abuse it
- Exploits for widely used software often appear within days of a security update; unpatched machines are then easy targets.
- Internet-wide scanning makes it cheap to find every machine still running a vulnerable version.

## How to verify
- Check that the package is installed (`dpkg -s unattended-upgrades`).
- Read the effective `APT::Periodic` values, for example with `apt-config dump | grep Periodic`.
- `unattended-upgrade --dry-run --debug` simulates a run without installing anything.
- Logs are in `/var/log/unattended-upgrades/`.

## How to fix
Install `unattended-upgrades` and set both `APT::Periodic::Update-Package-Lists "1";` and `APT::Periodic::Unattended-Upgrade "1";`, for example in `/etc/apt/apt.conf.d/20auto-upgrades`. Make sure no later-named file sets them back to `"0"`. Decide how you will handle updates that need a reboot (kernel and core libraries); unattended-upgrades can be configured to reboot automatically at a chosen time.

The HardenGarden remediation template for HG-UPD-001 installs the package and writes the two settings.

## References
- https://ubuntu.com/server/docs/how-to/software/automatic-updates/
- https://manpages.debian.org/bookworm/unattended-upgrades/unattended-upgrade.8.en.html
