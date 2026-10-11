# Address space layout randomization (ASLR)
<!-- hg:kb checks=HG-KRN-001 -->

## What it is
Address space layout randomization places a program's stack, shared libraries, memory mappings and heap at random addresses each time it starts. The Linux kernel controls it with the `kernel.randomize_va_space` setting, visible at `/proc/sys/kernel/randomize_va_space`:
- `0`: no randomization,
- `1`: randomizes the stack, memory mappings (including shared libraries) and the VDSO page, but **not** the heap,
- `2`: everything in level 1 plus the heap.

HardenGarden reports PASS for `2`, WARN for `1` and FAIL for `0`. Reading the value needs no root.

## Why it matters
Many memory-corruption exploits need to know where something is in memory: a function to jump to, a buffer to overwrite. With randomization the addresses change from run to run, so exploits become unreliable or need an extra information leak. It is a cheap, system-wide defence that makes a whole class of attacks much harder.

## How attackers abuse it
- With ASLR disabled, exploit code can use fixed addresses that work on every machine with the same binaries.
- With heap randomization missing (level 1), heap-based exploits can rely on predictable heap addresses.

## How to verify
- `cat /proc/sys/kernel/randomize_va_space` shows the running value.
- `sysctl kernel.randomize_va_space` shows the same.
- Persistent settings live in `/etc/sysctl.d/*.conf`, `/run/sysctl.d/`, `/usr/local/lib/sysctl.d/` and `/usr/lib/sysctl.d/`. Files are applied in name order and the last file setting a key wins. Look for files that set it to `0`, and check the kernel command line for `norandmaps`.

## How to fix
Set the value to `2` now and persist it in a file under `/etc/sysctl.d/` whose name sorts after any file that lowers it (local files conventionally use numbers 60–90). Remove any setting that disables it. Only very old binaries that assume a fixed heap layout are known to break with level 2.

The HardenGarden remediation template for HG-KRN-001 sets the running value and writes a persistent drop-in file.

## References
- https://www.kernel.org/doc/html/latest/admin-guide/sysctl/kernel.html
- https://manpages.debian.org/bookworm/systemd/sysctl.d.5.en.html
