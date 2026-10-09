"""Wires the knowledge base, vector store, embedder and retriever together.

Everything degrades gracefully: without Ollama the retriever is lexical-only (R16).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from hardengarden.core.paths import data_dir
from hardengarden.core.settings import Settings
from hardengarden.core.systemview import SystemView
from hardengarden.rag.ingest import (
    DocumentEmbedder,
    IngestReport,
    ingest_knowledge_base,
    ingest_manpages,
)
from hardengarden.rag.kb import KnowledgeBase, load_knowledge_base
from hardengarden.rag.manpages import load_manpages, read_manpages, save_manpages
from hardengarden.rag.ollama import OllamaClient, OllamaEmbedder, OllamaError
from hardengarden.rag.retrieve import QueryEmbedder, Retriever
from hardengarden.rag.store import KB_COLLECTION, VectorStore

MANPAGES_FILE = "manpages.json"
VECTORS_DIR = "vectors"


@dataclass(frozen=True, slots=True)
class IngestSummary:
    kb_version: str
    lexical_chunks: int
    manpage_chunks: int
    vector_reports: tuple[IngestReport, ...]
    vectors_skipped_reason: str | None


class Embedder(DocumentEmbedder, QueryEmbedder, Protocol):
    """An embedding model usable for both ingestion and queries."""


class KnowledgeService:
    def __init__(
        self,
        settings: Settings,
        *,
        base: Path | None = None,
        kb: KnowledgeBase | None = None,
        embedder: Embedder | None = None,
    ) -> None:
        self.settings = settings
        self.base = base or data_dir()
        self.kb = kb or load_knowledge_base()
        self._embedder = embedder

    @property
    def manpages_path(self) -> Path:
        return self.base / MANPAGES_FILE

    def _store(self) -> VectorStore:
        return VectorStore(self.base / VECTORS_DIR)

    def embedder(self) -> Embedder:
        if self._embedder is not None:
            return self._embedder
        return OllamaEmbedder(OllamaClient(self.settings.ollama_url), self.settings.embed_model)

    def ingest(
        self, *, with_manpages: bool = False, view: SystemView | None = None
    ) -> IngestSummary:
        manpages = load_manpages(self.manpages_path)
        if with_manpages:
            self.base.mkdir(parents=True, exist_ok=True, mode=0o700)
            manpages = read_manpages(view or SystemView("/"))
            save_manpages(self.manpages_path, manpages)
        reports: list[IngestReport] = []
        skipped: str | None = None
        try:
            embedder = self.embedder()
            store = self._store()
            reports.append(ingest_knowledge_base(self.kb, store, embedder))
            if manpages:
                reports.append(ingest_manpages(manpages, store, embedder, self.kb.version))
        except OllamaError as exc:
            skipped = f"vector index not built: {exc}. Keyword search still works."
        return IngestSummary(
            kb_version=self.kb.version,
            lexical_chunks=len(self.kb.chunks()),
            manpage_chunks=len(manpages),
            vector_reports=tuple(reports),
            vectors_skipped_reason=skipped,
        )

    def retriever(self, *, use_vectors: bool = True) -> Retriever:
        manpages = load_manpages(self.manpages_path)
        if use_vectors and (self.base / VECTORS_DIR).is_dir():
            store = self._store()
            if store.count(KB_COLLECTION):
                return Retriever(
                    self.kb,
                    manpages=manpages,
                    threshold=self.settings.retrieval_threshold,
                    embedder=_SafeEmbedder(self.embedder()),
                    vectors=store,
                )
        return Retriever(self.kb, manpages=manpages, threshold=self.settings.retrieval_threshold)


class _SafeEmbedder:
    """If Ollama disappears after ingestion, fall back to lexical-only for that query."""

    def __init__(self, inner: Embedder) -> None:
        self.inner = inner

    def embed_query(self, text: str) -> list[float]:
        try:
            return self.inner.embed_query(text)
        except OllamaError:
            return []
