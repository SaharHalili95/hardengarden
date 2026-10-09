#!/usr/bin/env python3
"""Runs the shell commands in README.md so the documented commands cannot rot.

    readme_commands.py [README] [--list]

Every ``sh``/``bash`` code block must be preceded by a marker comment:

    <!-- readme-test: run -->
    <!-- readme-test: skip (why it cannot run in CI, and what tests it instead) -->

Unmarked blocks, or a skip without a reason, are errors. Marked blocks run in order with
``bash -euo pipefail`` from the repository root; any failure fails the run. Standard library
only.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SHELLS = {"sh", "bash", "shell"}
_MARKER = re.compile(r"^<!--\s*readme-test:\s*(run|skip)\s*(?:\((.+)\))?\s*-->$")


@dataclass(frozen=True)
class Block:
    line: int
    action: str
    reason: str
    code: str


def parse(text: str) -> tuple[list[Block], list[str]]:
    blocks: list[Block] = []
    errors: list[str] = []
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        opening = lines[index].strip()
        if not opening.startswith("```"):
            index += 1
            continue
        lang = opening[3:].strip().split(" ")[0]
        end = index + 1
        while end < len(lines) and lines[end].strip() != "```":
            end += 1
        if lang in SHELLS:
            previous = next(
                (lines[i].strip() for i in range(index - 1, -1, -1) if lines[i].strip()), ""
            )
            marker = _MARKER.match(previous)
            if marker is None:
                errors.append(f"line {index + 1}: shell block without a readme-test marker")
            elif marker.group(1) == "skip" and not marker.group(2):
                errors.append(f"line {index + 1}: 'skip' needs a reason in parentheses")
            else:
                code = "\n".join(lines[index + 1 : end])
                blocks.append(Block(index + 1, marker.group(1), marker.group(2) or "", code))
        index = end + 1
    return blocks, errors


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the commands documented in a README.")
    parser.add_argument("readme", nargs="?", type=Path, default=ROOT / "README.md")
    parser.add_argument("--list", action="store_true", help="only list blocks and markers")
    args = parser.parse_args()
    blocks, errors = parse(args.readme.read_text(encoding="utf-8"))
    for error in errors:
        print(f"FAIL  {error}")
    if errors:
        sys.exit(1)
    for block in blocks:
        label = "run " if block.action == "run" else f"skip ({block.reason})"
        print(f"== line {block.line}: {label}", flush=True)
        if args.list or block.action == "skip":
            continue
        print(block.code, flush=True)
        result = subprocess.run(
            ["bash", "-euo", "pipefail", "-c", block.code], cwd=ROOT, check=False
        )
        if result.returncode != 0:
            print(f"FAIL  block at line {block.line} exited {result.returncode}")
            sys.exit(1)
    ran = sum(b.action == "run" for b in blocks)
    print(f"{ran} block(s) ran, {len(blocks) - ran} skipped with a reason")


if __name__ == "__main__":
    main()
