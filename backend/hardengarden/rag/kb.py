"""Knowledge-base loading and deterministic chunking.

Each document in ``knowledge/`` is Markdown with one ``# Title``, an
``<!-- hg:kb checks=... -->`` marker and ``## `` sections. Every section except
"References" becomes one chunk with a stable ID ``<doc-slug>#<section-slug>``. IDs depend
only on the file name and the heading text, never on position or content, so re-ingesting
an edited document updates chunks in place instead of duplicating them.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

MAX_DOC_BYTES = 16 * 1024
REQUIRED_SECTIONS = (
    "What it is",
    "Why it matters",
    "How attackers abuse it",
    "How to verify",
    "How to fix",
    "References",
)
_MARKER = re.compile(r"<!--\s*hg:kb\s+checks=([A-Z0-9,\- ]+)\s*-->")
_URL = re.compile(r"^-\s+(https://\S+)\s*$", re.M)
_SLUG = re.compile(r"[^a-z0-9]+")


class KnowledgeBaseError(Exception):
    pass


def slugify(text: str) -> str:
    return _SLUG.sub("-", text.lower()).strip("-")


@dataclass(frozen=True, slots=True)
class Chunk:
    id: str
    doc: str
    section: str
    title: str
    text: str
    doc_hash: str


@dataclass(frozen=True, slots=True)
class Document:
    slug: str
    title: str
    checks: tuple[str, ...]
    sections: dict[str, str]
    references: tuple[str, ...]
    sha256: str

    def chunks(self) -> list[Chunk]:
        return [
            Chunk(
                id=f"{self.slug}#{slugify(heading)}",
                doc=self.slug,
                section=heading,
                title=self.title,
                text=f"{self.title}. {heading}.\n{body}",
                doc_hash=self.sha256[:16],
            )
            for heading, body in self.sections.items()
            if heading != "References"
        ]


def parse_document(slug: str, text: str) -> Document:
    if len(text.encode()) > MAX_DOC_BYTES:
        msg = f"{slug}: document exceeds {MAX_DOC_BYTES} bytes"
        raise KnowledgeBaseError(msg)
    lines = text.splitlines()
    if not lines or not lines[0].startswith("# "):
        msg = f"{slug}: first line must be '# Title'"
        raise KnowledgeBaseError(msg)
    marker = _MARKER.search(text)
    if marker is None:
        msg = f"{slug}: missing '<!-- hg:kb checks=... -->' marker"
        raise KnowledgeBaseError(msg)
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in lines[1:]:
        if line.startswith("## "):
            current = line[3:].strip()
            if current in sections:
                msg = f"{slug}: duplicate section {current!r}"
                raise KnowledgeBaseError(msg)
            sections[current] = []
        elif current is not None:
            sections[current].append(line)
    missing = [s for s in REQUIRED_SECTIONS if s not in sections]
    if missing:
        msg = f"{slug}: missing sections {missing}"
        raise KnowledgeBaseError(msg)
    bodies = {heading: "\n".join(body).strip() for heading, body in sections.items()}
    references = tuple(_URL.findall(bodies["References"]))
    if not references:
        msg = f"{slug}: References must list at least one https:// URL"
        raise KnowledgeBaseError(msg)
    return Document(
        slug=slug,
        title=lines[0][2:].strip(),
        checks=tuple(c.strip() for c in marker.group(1).split(",") if c.strip()),
        sections=bodies,
        references=references,
        sha256=hashlib.sha256(text.encode()).hexdigest(),
    )


def default_kb_dir() -> Path:
    """Packaged copy in wheels; the repository's ``knowledge/`` in a source checkout."""
    packaged = Path(__file__).resolve().parent.parent / "kb_docs"
    if packaged.is_dir():
        return packaged
    return Path(__file__).resolve().parents[3] / "knowledge"


@dataclass(frozen=True, slots=True)
class KnowledgeBase:
    documents: tuple[Document, ...]

    @property
    def version(self) -> str:
        """Hash over every document hash: changes whenever any document changes."""
        digest = hashlib.sha256()
        for doc in sorted(self.documents, key=lambda d: d.slug):
            digest.update(f"{doc.slug}:{doc.sha256}\n".encode())
        return digest.hexdigest()[:16]

    def chunks(self) -> list[Chunk]:
        return [chunk for doc in self.documents for chunk in doc.chunks()]

    def document(self, slug: str) -> Document | None:
        return next((d for d in self.documents if d.slug == slug), None)

    def for_check(self, check_id: str) -> Document | None:
        return next((d for d in self.documents if check_id in d.checks), None)


def load_knowledge_base(directory: Path | None = None) -> KnowledgeBase:
    base = directory or default_kb_dir()
    paths = sorted(base.glob("*.md"))
    if not paths:
        msg = f"no knowledge-base documents found in {base}"
        raise KnowledgeBaseError(msg)
    return KnowledgeBase(
        tuple(parse_document(p.stem, p.read_text(encoding="utf-8")) for p in paths)
    )
