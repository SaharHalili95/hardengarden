# Host firewall
<!-- hg:kb checks=HG-FW-001 -->

## What it is
A host firewall is a packet filter running on the machine itself that decides which incoming connections are allowed. On Ubuntu and Debian the usual tools are **ufw** (Uncomplicated Firewall, a front end) and **nftables** (the kernel's current packet filtering framework, which ufw and modern iptables also use underneath).

HardenGarden reports PASS when ufw is active, or when an nftables ruleset contains a chain attached to the `input` hook. Without root it can only read configuration files, so the check is skipped on a live host without root.

## Why it matters
Without a firewall, every program that opens a listening socket on a network interface is reachable by anyone who can route packets to the machine. Services are often started for local use and accidentally listen on all interfaces: databases, caches, admin panels, debug servers. A default-deny incoming policy turns those mistakes into non-events.

## How attackers abuse it
- Internet-wide scanners find exposed databases and caches within hours and either steal data or use them as an entry point.
- Services without authentication by default become instant remote access when they are reachable.
- Once one machine on a network is compromised, missing host firewalls let the attacker move sideways to every other machine's services.

## How to verify
- With ufw (needs root): `ufw status` shows `Status: active` and the rules; `ufw status verbose` also shows the default policies. A fresh ufw install denies incoming and allows outgoing traffic, but ufw itself starts disabled.
- With nftables (needs root): `nft list ruleset` and look for a base chain with `hook input` and, ideally, `policy drop`.
- Without root: `/etc/ufw/ufw.conf` contains `ENABLED=yes` when ufw is set to start at boot; `/etc/nftables.conf` holds the nftables rules loaded by `nftables.service`.

## How to fix
With ufw: allow the services you need **first** (at least SSH, for example `ufw allow 22/tcp`), then enable the firewall. Enabling it makes it start at boot too. Over SSH, ufw asks for confirmation because a wrong rule set can cut the connection.

With nftables: write a ruleset with an `inet` table, a base chain on the `input` hook with a drop policy, and rules that accept established/related traffic, loopback, and the ports you need. Load it with `nft -f` and enable `nftables.service`.

The HardenGarden remediation template for HG-FW-001 uses ufw, allows SSH before enabling, and only applies changes when you explicitly ask it to.

## References
- https://help.ubuntu.com/community/UFW
- https://manpages.ubuntu.com/manpages/noble/en/man8/ufw.8.html
- https://wiki.nftables.org/wiki-nftables/index.php/Main_Page
- https://wiki.nftables.org/wiki-nftables/index.php/Simple_ruleset_for_a_server
