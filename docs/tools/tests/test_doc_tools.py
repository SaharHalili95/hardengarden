"""Tests for the documentation tools (run from backend/: uv run pytest ../docs/tools/tests)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

TOOLS = Path(__file__).resolve().parent.parent


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, TOOLS / f"{name}.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # dataclasses look their module up while the class is created
    spec.loader.exec_module(module)
    return module


links = _load("check_links")
readme = _load("readme_commands")


def test_slugs_follow_github_rules() -> None:
    assert links.slug("ADR-012 — Open chromadb advisories: accepted") == (
        "adr-012--open-chromadb-advisories-accepted"
    )
    assert links.slug("Verify a `download`") == "verify-a-download"
    assert links.slug("[Linked](https://example.org) heading") == "linked-heading"


def test_duplicate_headings_get_numbered_anchors_and_code_is_ignored() -> None:
    text = "# Title\n## Usage\n```sh\n# not a heading\n```\n## Usage\n"
    assert links.anchors(text) == {"title", "usage", "usage-1"}


def test_links_are_found_outside_code_only(tmp_path: Path) -> None:
    text = (
        "See [docs](docs/a.md#part) and <https://example.org/x>.\n"
        "Bare https://example.com/page. and `https://in-code.example`\n"
        "```\n[skipped](nowhere.md)\n```\n"
    )
    found = [link.target for link in links.extract_links(tmp_path / "f.md", text)]
    assert found == ["docs/a.md#part", "https://example.org/x", "https://example.com/page"]


def test_internal_links_need_the_file_and_the_heading(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(links, "ROOT", tmp_path)
    (tmp_path / "a.md").write_text("# A\n## Part one\n", encoding="utf-8")
    source = tmp_path / "index.md"
    source.write_text("", encoding="utf-8")

    def check(target: str) -> str | None:
        result: str | None = links.check_internal(links.Link(source, 1, target))
        return result

    assert check("a.md#part-one") is None
    assert check("a.md") is None
    assert check("a.md#missing") == "missing heading #missing in a.md"
    assert check("gone.md") == "missing file gone.md"


def test_every_shell_block_needs_a_marker_and_skips_need_a_reason() -> None:
    text = (
        "<!-- readme-test: run -->\n```sh\necho ok\n```\n"
        "<!-- readme-test: skip (needs a release) -->\n```bash\ncurl x\n```\n"
        "<!-- readme-test: skip -->\n```sh\nfalse\n```\n"
        "```sh\nunmarked\n```\n"
        "```python\nprint('not shell')\n```\n"
    )
    blocks, errors = readme.parse(text)
    assert [(b.action, b.reason, b.code) for b in blocks] == [
        ("run", "", "echo ok"),
        ("skip", "needs a release", "curl x"),
    ]
    assert errors == [
        "line 10: 'skip' needs a reason in parentheses",
        "line 13: shell block without a readme-test marker",
    ]


def test_the_real_readme_is_fully_marked() -> None:
    blocks, errors = readme.parse((TOOLS.parent.parent / "README.md").read_text(encoding="utf-8"))
    assert errors == []
    assert any(b.action == "run" for b in blocks)
