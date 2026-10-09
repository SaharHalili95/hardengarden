"""Knowledge-base linter (Phase 2) and chunking determinism."""

from __future__ import annotations

from pathlib import Path

import pytest

from hardengarden.checks import ALL_CHECKS
from hardengarden.rag.kb import (
    MAX_DOC_BYTES,
    REQUIRED_SECTIONS,
    KnowledgeBaseError,
    default_kb_dir,
    load_knowledge_base,
    parse_document,
    slugify,
)

REPO_KB = Path(__file__).resolve().parents[3] / "knowledge"
VALID = """# Title
<!-- hg:kb checks=HG-TST-001 -->

## What it is
a
## Why it matters
b
## How attackers abuse it
c
## How to verify
d
## How to fix
e
## References
- https://example.org/doc
"""


def test_every_check_has_a_matching_kb_doc() -> None:
    kb = load_knowledge_base(REPO_KB)
    for check in ALL_CHECKS:
        path = Path(__file__).resolve().parents[3] / check.meta.kb_doc
        assert path.is_file(), check.meta.kb_doc
        doc = kb.document(path.stem)
        assert doc is not None
        assert check.meta.id in doc.checks, (check.meta.id, doc.slug)
        assert kb.for_check(check.meta.id) == doc


def test_every_doc_is_used_by_a_check() -> None:
    kb = load_knowledge_base(REPO_KB)
    referenced = {Path(c.meta.kb_doc).stem for c in ALL_CHECKS}
    assert {d.slug for d in kb.documents} == referenced


@pytest.mark.parametrize("path", sorted(REPO_KB.glob("*.md")), ids=lambda p: p.stem)
def test_doc_structure_references_and_size(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    assert len(text.encode()) <= MAX_DOC_BYTES
    doc = parse_document(path.stem, text)
    assert list(doc.sections)[: len(REQUIRED_SECTIONS)] == list(REQUIRED_SECTIONS)
    assert doc.references
    assert all(url.startswith("https://") for url in doc.references)


def test_no_licensed_benchmark_text() -> None:
    """R18: the KB is original writing; it must not quote or cite CIS benchmark material."""
    for path in REPO_KB.glob("*.md"):
        text = path.read_text(encoding="utf-8").lower()
        assert "cisecurity" not in text
        assert "cis benchmark" not in text


def test_chunk_ids_are_stable_unique_and_content_independent() -> None:
    kb = load_knowledge_base(REPO_KB)
    ids = [c.id for c in kb.chunks()]
    assert len(ids) == len(set(ids))
    assert ids == [c.id for c in load_knowledge_base(REPO_KB).chunks()]
    assert "ssh-root-login#how-to-fix" in ids
    assert not any(i.endswith("#references") for i in ids)
    edited = parse_document("x", VALID.replace("\na\n", "\nchanged body\n"))
    assert [c.id for c in edited.chunks()] == [c.id for c in parse_document("x", VALID).chunks()]


def test_kb_version_changes_with_content(tmp_path: Path) -> None:
    (tmp_path / "x.md").write_text(VALID)
    first = load_knowledge_base(tmp_path).version
    assert load_knowledge_base(tmp_path).version == first
    (tmp_path / "x.md").write_text(VALID.replace("\nb\n", "\nB\n"))
    assert load_knowledge_base(tmp_path).version != first


@pytest.mark.parametrize(
    ("text", "error"),
    [
        ("no title", "first line"),
        ("# T\n## What it is\n", "marker"),
        (VALID.replace("## How to fix\ne\n", ""), "missing sections"),
        (VALID.replace("- https://example.org/doc", "- http://insecure"), "References"),
        (VALID + "## What it is\nagain\n", "duplicate"),
        (VALID + "x" * MAX_DOC_BYTES, "exceeds"),
    ],
)
def test_invalid_documents_are_rejected(text: str, error: str) -> None:
    with pytest.raises(KnowledgeBaseError, match=error):
        parse_document("bad", text)


def test_empty_kb_directory(tmp_path: Path) -> None:
    with pytest.raises(KnowledgeBaseError, match="no knowledge-base"):
        load_knowledge_base(tmp_path)


def test_default_dir_and_slugify() -> None:
    assert default_kb_dir().is_dir()
    assert slugify("How attackers abuse it") == "how-attackers-abuse-it"
    assert slugify("  /etc/shadow & co ") == "etc-shadow-co"
