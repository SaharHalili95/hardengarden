#!/usr/bin/env python3
"""Checks the links in every tracked Markdown file.

    check_links.py [--external] [FILE ...]

Internal links (relative paths and #anchors) must point to an existing file and, for
Markdown targets, to an existing heading (GitHub's anchor rules). With ``--external``, http(s)
links are fetched too: 2xx/3xx pass; 401, 403 and 429 are reported as warnings (sites that
block automated clients); anything else fails. Links to this repository on github.com are not
fetched (they describe the repository itself, which the internal check covers, and some only
exist after the first release). Links inside code blocks and inline code are ignored.
Standard library only.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OWN_REPO = (
    "https://github.com/SaharHalili95/hardengarden",
    "https://img.shields.io/github/v/release/SaharHalili95/hardengarden",
)
WARN_STATUSES = {401, 403, 429}
FIRST_ERROR_STATUS = 400
FIRST_SERVER_ERROR = 500
ATTEMPTS = 3
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) hardengarden-link-check"

_FENCE = re.compile(r"^\s*(```|~~~)")
_INLINE_CODE = re.compile(r"`[^`]*`")
_LINK = re.compile(r"!?\[(?:[^\[\]]|\[[^\]]*\])*\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
_AUTOLINK = re.compile(r"<(https?://[^>\s]+)>")
_BARE_URL = re.compile(r"https?://[^\s<>()\[\]\"'`]+")
_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")


@dataclass(frozen=True)
class Link:
    source: Path
    line: int
    target: str


def strip_code(lines: list[str]) -> list[str]:
    """Blanks fenced code blocks and inline code, keeping line numbers."""
    out: list[str] = []
    fenced = False
    for line in lines:
        if _FENCE.match(line):
            fenced = not fenced
            out.append("")
            continue
        out.append("" if fenced else _INLINE_CODE.sub("", line))
    return out


def extract_links(path: Path, text: str) -> list[Link]:
    links: list[Link] = []
    for number, line in enumerate(strip_code(text.splitlines()), start=1):
        targets = [m.group(1) for m in _LINK.finditer(line)]
        targets += [m.group(1) for m in _AUTOLINK.finditer(line)]
        # Bare URLs, which GitHub also renders as links.
        targets += [m.group(0).rstrip(".,;:") for m in _BARE_URL.finditer(line)]
        links += [Link(path, number, t) for t in dict.fromkeys(targets)]
    return links


def slug(heading: str) -> str:
    """GitHub's heading anchor: lower case, punctuation removed, spaces become hyphens."""
    text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", heading)  # links -> their text
    text = text.replace("`", "").strip().lower()
    text = "".join(ch for ch in text if ch.isalnum() or ch in " -_")
    return text.replace(" ", "-")


def anchors(text: str) -> set[str]:
    seen: dict[str, int] = {}
    result: set[str] = set()
    for line in strip_code(text.splitlines()):
        match = _HEADING.match(line)
        if match is None:
            continue
        base = slug(match.group(2))
        count = seen.get(base, 0)
        seen[base] = count + 1
        result.add(base if count == 0 else f"{base}-{count}")
    return result


def check_internal(link: Link) -> str | None:
    path_part, _, fragment = link.target.partition("#")
    if path_part:
        base = ROOT if path_part.startswith("/") else link.source.parent
        target = (base / path_part.lstrip("/")).resolve()
        if not target.exists():
            return f"missing file {path_part}"
    else:
        target = link.source
    if (
        fragment
        and target.suffix == ".md"
        and fragment not in anchors(target.read_text(encoding="utf-8"))
    ):
        return f"missing heading #{fragment} in {target.relative_to(ROOT)}"
    return None


def fetch_status(url: str) -> int | str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})  # noqa: S310 - http(s) only, checked by the caller
    for attempt in range(ATTEMPTS):
        last = attempt == ATTEMPTS - 1
        try:
            with urllib.request.urlopen(request, timeout=20) as response:  # noqa: S310 - same
                return int(response.status)
        except urllib.error.HTTPError as error:
            if error.code < FIRST_SERVER_ERROR or last:  # retry server errors only
                return int(error.code)
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            if last:
                return f"error: {error}"
        time.sleep(2 * (attempt + 1))
    return "error: no response"


def tracked_markdown() -> list[Path]:
    output = subprocess.run(
        ["git", "ls-files", "*.md"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout
    return [ROOT / line for line in output.splitlines() if line]


def main() -> None:
    parser = argparse.ArgumentParser(description="Check Markdown links.")
    parser.add_argument("--external", action="store_true", help="also fetch http(s) links")
    parser.add_argument("files", nargs="*", type=Path)
    args = parser.parse_args()
    files = [f.resolve() for f in args.files] or tracked_markdown()

    errors: list[str] = []
    warnings: list[str] = []
    external: dict[str, list[Link]] = {}
    count = 0
    for path in files:
        for link in extract_links(path, path.read_text(encoding="utf-8")):
            count += 1
            where = f"{path.relative_to(ROOT)}:{link.line}"
            if link.target.startswith(("http://", "https://")):
                external.setdefault(link.target, []).append(link)
            elif link.target.startswith("mailto:"):
                continue
            elif problem := check_internal(link):
                errors.append(f"{where}: {problem}")

    if args.external:
        for url, uses in sorted(external.items()):
            if url.startswith(OWN_REPO):
                continue
            status = fetch_status(url)
            first = f"{uses[0].source.relative_to(ROOT)}:{uses[0].line}"
            if isinstance(status, int) and status < FIRST_ERROR_STATUS:
                continue
            message = f"{first}: {url} -> {status}"
            (warnings if status in WARN_STATUSES else errors).append(message)

    for line in warnings:
        print(f"WARN  {line}")
    for line in errors:
        print(f"FAIL  {line}")
    scope = f"{len(external)} external URLs fetched" if args.external else "external not fetched"
    print(f"{count} links in {len(files)} files; {scope}; {len(errors)} broken")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
