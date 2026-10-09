"""Idempotent ingestion of the knowledge base (and optional man pages) into the vector store."""

from __future__ import annotations

import hashlib
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from hardengarden.rag.kb import KnowledgeBase
from hardengarden.rag.manpages import ManChunk
from hardengarden.rag.store import KB_COLLECTION, MAN_COLLECTION, StoredItem, VectorStore


class DocumentEmbedder(Protocol):
    @property
    def name(self) -> str: ...

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...


@dataclass(frozen=True, slots=True)
class IngestReport:
    collection: str
    added: int
    updated: int
    removed: int
    unchanged: int
    seconds: float
    kb_version: str


def _fingerprint(text: str, model: str) -> str:
    return hashlib.sha256(f"{model}\n{text}".encode()).hexdigest()[:24]


def _sync(
    store: VectorStore,
    collection: str,
    entries: Sequence[tuple[str, str, dict[str, str]]],
    embedder: DocumentEmbedder,
    kb_version: str,
) -> IngestReport:
    started = time.perf_counter()
    existing = store.fingerprints(collection)
    wanted = {item_id: (text, meta) for item_id, text, meta in entries}
    changed = [
        (item_id, text, meta)
        for item_id, (text, meta) in wanted.items()
        if existing.get(item_id) != _fingerprint(text, embedder.name)
    ]
    stale = sorted(set(existing) - set(wanted))
    if changed:
        vectors = embedder.embed_documents([text for _, text, _ in changed])
        store.upsert(
            collection,
            [
                StoredItem(
                    id=item_id,
                    text=text,
                    metadata={**meta, "fingerprint": _fingerprint(text, embedder.name),
                              "kb_version": kb_version, "embedding_model": embedder.name},
                    embedding=vector,
                )
                for (item_id, text, meta), vector in zip(changed, vectors, strict=True)
            ],
        )  # fmt: skip
    store.delete(collection, stale)
    updated = sum(1 for item_id, _, _ in changed if item_id in existing)
    return IngestReport(
        collection=collection,
        added=len(changed) - updated,
        updated=updated,
        removed=len(stale),
        unchanged=len(wanted) - len(changed),
        seconds=round(time.perf_counter() - started, 3),
        kb_version=kb_version,
    )


def ingest_knowledge_base(
    kb: KnowledgeBase, store: VectorStore, embedder: DocumentEmbedder
) -> IngestReport:
    entries = [
        (c.id, c.text, {"source": c.doc, "section": c.section, "doc_hash": c.doc_hash})
        for c in kb.chunks()
    ]
    return _sync(store, KB_COLLECTION, entries, embedder, kb.version)


def ingest_manpages(
    chunks: Sequence[ManChunk], store: VectorStore, embedder: DocumentEmbedder, kb_version: str
) -> IngestReport:
    entries = [(c.id, c.text, {"source": f"man:{c.page}"}) for c in chunks]
    return _sync(store, MAN_COLLECTION, entries, embedder, kb_version)
