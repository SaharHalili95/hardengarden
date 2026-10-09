#!/usr/bin/env python3
"""Writes GitHub release notes from Conventional Commits between two refs.

    release_notes.py --tag v0.1.0 [--since PREVIOUS_TAG] --glibc 2.35 > notes.md

Without ``--since`` the previous ``v*`` tag is used, or the whole history for the first
release. Merge commits are skipped. Standard library only.
"""

from __future__ import annotations

import argparse
import re
import subprocess
from collections.abc import Iterable

SECTIONS: tuple[tuple[str, str], ...] = (
    ("feat", "Features"),
    ("fix", "Fixes"),
    ("sec", "Security"),
    ("perf", "Performance"),
    ("docs", "Documentation"),
    ("test", "Tests"),
    ("ci", "CI and release"),
    ("build", "Build"),
    ("refactor", "Refactoring"),
    ("chore", "Maintenance"),
)
WORKFLOW = "https://github.com/SaharHalili95/hardengarden/.github/workflows/release.yml"
_SUBJECT = re.compile(r"^(?P<type>[a-z]+)(?:\((?P<scope>[^)]+)\))?(?P<breaking>!)?: (?P<text>.+)$")


def group(subjects: Iterable[str]) -> dict[str, list[str]]:
    """Groups commit subjects by section title; non-conventional subjects go to "Other"."""
    titles = dict(SECTIONS)
    grouped: dict[str, list[str]] = {}
    for subject in subjects:
        match = _SUBJECT.match(subject.strip())
        if match is None:
            grouped.setdefault("Other", []).append(subject.strip())
            continue
        title = titles.get(match["type"], "Other")
        line = match["text"]
        if match["scope"]:
            line = f"**{match['scope']}:** {line}"
        if match["breaking"]:
            line = f"**Breaking:** {line}"
        grouped.setdefault(title, []).append(line)
    return grouped


def render(tag: str, grouped: dict[str, list[str]], glibc: str) -> str:
    order = [title for _, title in SECTIONS] + ["Other"]
    out = [f"# HardenGarden {tag}", ""]
    out += [
        "HardenGarden is an educational/portfolio security tool. It is not a certified "
        "compliance scanner and does not replace a professional audit.",
        "",
        f"Native binaries were built on Ubuntu 22.04 (glibc {glibc}); they need glibc "
        f"{glibc} or newer (Ubuntu 22.04+, Debian 12+).",
        "",
    ]
    for title in order:
        if grouped.get(title):
            out += [f"## {title}", ""]
            out += [f"- {line}" for line in grouped[title]]
            out.append("")
    out += [
        "## Verify this release",
        "",
        "```sh",
        "sha256sum -c SHA256SUMS --ignore-missing",
        "cosign verify-blob SHA256SUMS --bundle SHA256SUMS.sigstore.json \\",
        f"  --certificate-identity {WORKFLOW}@refs/tags/{tag} \\",
        "  --certificate-oidc-issuer https://token.actions.githubusercontent.com",
        "```",
        "",
    ]
    return "\n".join(out)


def _git(*args: str) -> str:
    return subprocess.run(  # fixed git invocation, no shell
        ["git", *args], capture_output=True, text=True, check=True
    ).stdout


def previous_tag(tag: str) -> str | None:
    tags = [t for t in _git("tag", "--list", "v*", "--sort=-v:refname").split() if t != tag]
    return tags[0] if tags else None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tag", required=True)
    parser.add_argument("--since")
    parser.add_argument("--glibc", required=True)
    parser.add_argument("--ref", default="HEAD")
    args = parser.parse_args()
    since = args.since or previous_tag(args.tag)
    span = f"{since}..{args.ref}" if since else args.ref
    subjects = _git("log", "--no-merges", "--format=%s", span).splitlines()
    print(render(args.tag, group(subjects), args.glibc))


if __name__ == "__main__":
    main()
