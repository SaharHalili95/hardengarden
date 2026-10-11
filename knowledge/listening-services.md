# Listening services on network interfaces
<!-- hg:kb checks=HG-NET-001 -->

## What it is
A listening service is a program waiting for incoming connections (TCP) or datagrams (UDP) on a port. It can bind to a loopback address (`127.0.0.1`, `::1`), which only local programs can reach, or to a network-facing address, including the wildcard addresses `0.0.0.0` and `::` that mean "every interface".

HardenGarden reads the kernel's socket tables in `/proc/net/tcp`, `tcp6`, `udp` and `udp6` (no root needed) and lists sockets bound to non-loopback addresses. SSH on TCP 22 and DHCP clients on UDP 68/546 are expected; anything else is a WARN that deserves a look. It is a WARN rather than a FAIL because many servers legitimately offer services.

## Why it matters
Every network-facing listener is attack surface: its code, its configuration and its authentication are all reachable from outside. Services that are only used by local programs (a database behind a web app, a metrics agent, a development server) should listen on loopback, where the network cannot reach them at all.

## How attackers abuse it
- Mass scanners index open ports on the internet and match them against known vulnerabilities and default credentials.
- Development and debug servers bound to `0.0.0.0` by mistake often have no authentication.
- Even services meant to be public become the entry point when a vulnerability in them is published.

## How to verify
- `ss -tuln` lists TCP and UDP listening sockets with numeric addresses; adding `-p` shows the owning process, which generally needs root for other users' processes.
- In the output, `0.0.0.0:PORT`, `[::]:PORT`, `*:PORT` or a specific external IP mean network-facing; `127.0.0.x` and `[::1]` mean local only.
- For each network-facing port, ask: who needs to reach this, from where?

## How to fix
For each unexpected listener, pick one:
- **Not needed:** stop and disable the service.
- **Only used locally:** change its configuration to bind to `127.0.0.1` / `::1`.
- **Needed from some networks only:** keep it, and restrict access with the host firewall (see HG-FW-001).
- **Needed publicly:** keep it, keep it patched, and require authentication.

There is no single safe automatic fix, so HardenGarden offers guidance only for this check.

## References
- https://manpages.debian.org/bookworm/iproute2/ss.8.en.html
- https://manpages.debian.org/bookworm/manpages/proc.5.en.html
