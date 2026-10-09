"""Retrieval with a confidence threshold (R13).

Ranking: BM25 over every chunk, fused with vector similarity (reciprocal rank fusion) when an
embedding model is available. Answerability: the IDF-weighted share of the question's terms
found in either of the two best-ranked sources. It is deterministic and needs no model, so
the refusal path is identical with and without Ollama and is fully tested in CI.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from hardengarden.rag.kb import KnowledgeBase
from hardengarden.rag.lexical import BM25, coverage, tokenize
from hardengarden.rag.manpages import ManChunk
from hardengarden.rag.store import KB_COLLECTION, MAN_COLLECTION, VectorHit

DEFAULT_THRESHOLD = 0.30
CONFIDENCE_SOURCES = 2  # answerability looks at the two best lexical sources
DEFAULT_K = 5
_RRF_K = 60


class QueryEmbedder(Protocol):
    def embed_query(self, text: str) -> list[float]: ...


class VectorSearch(Protocol):
    def query(self, collection: str, embedding: Sequence[float], k: int) -> list[VectorHit]: ...


@dataclass(frozen=True, slots=True)
class Passage:
    id: str
    source: str  # knowledge doc slug, or "man:<page>"
    title: str
    text: str


@dataclass(frozen=True, slots=True)
class Hit:
    passage: Passage
    score: float


@dataclass(frozen=True, slots=True)
class RetrievalResult:
    query: str
    hits: tuple[Hit, ...]
    confidence: float
    threshold: float
    used_vectors: bool

    @property
    def answerable(self) -> bool:
        return bool(self.hits) and self.confidence >= self.threshold

    @property
    def sources(self) -> list[str]:
        seen: list[str] = []
        for hit in self.hits:
            if hit.passage.source not in seen:
                seen.append(hit.passage.source)
        return seen


class Retriever:
    def __init__(
        self,
        kb: KnowledgeBase,
        *,
        manpages: Sequence[ManChunk] = (),
        threshold: float = DEFAULT_THRESHOLD,
        embedder: QueryEmbedder | None = None,
        vectors: VectorSearch | None = None,
    ) -> None:
        if not 0.0 < threshold <= 1.0:
            msg = "threshold must be in (0, 1]"
            raise ValueError(msg)
        self.kb = kb
        self.threshold = threshold
        self.embedder = embedder
        self.vectors = vectors
        self.passages: list[Passage] = [
            Passage(c.id, c.doc, c.title, c.text) for c in kb.chunks()
        ] + [Passage(m.id, f"man:{m.page}", m.page, m.text) for m in manpages]
        tokens = [tokenize(p.text) for p in self.passages]
        self.bm25 = BM25(tokens)
        self.by_id = {p.id: i for i, p in enumerate(self.passages)}
        self.vocabulary: dict[str, set[str]] = {}
        for passage, toks in zip(self.passages, tokens, strict=True):
            self.vocabulary.setdefault(passage.source, set()).update(toks)

    def _vector_ranking(self, query: str, k: int) -> list[str]:
        if self.embedder is None or self.vectors is None:
            return []
        embedding = self.embedder.embed_query(query)
        if not embedding:
            return []
        hits = self.vectors.query(KB_COLLECTION, embedding, k) + self.vectors.query(
            MAN_COLLECTION, embedding, k
        )
        hits.sort(key=lambda h: (-h.similarity, h.id))
        return [h.id for h in hits if h.id in self.by_id]

    def for_source(self, source: str, query: str) -> RetrievalResult:
        """All passages of one known document (used to explain a specific finding)."""
        hits = tuple(Hit(p, 1.0) for p in self.passages if p.source == source)
        return RetrievalResult(
            query=query,
            hits=hits,
            confidence=1.0 if hits else 0.0,
            threshold=self.threshold,
            used_vectors=False,
        )

    def search(self, query: str, k: int = DEFAULT_K) -> RetrievalResult:
        terms = tokenize(query)
        lexical = [s for s in self.bm25.score(terms) if s.score > 0]
        fused: dict[int, float] = {}
        for rank, scored in enumerate(lexical[: k * 4]):
            fused[scored.index] = fused.get(scored.index, 0.0) + 1.0 / (_RRF_K + rank + 1)
        vector_ids = self._vector_ranking(query, k * 4)
        for rank, chunk_id in enumerate(vector_ids):
            index = self.by_id[chunk_id]
            fused[index] = fused.get(index, 0.0) + 1.0 / (_RRF_K + rank + 1)
        ranked = sorted(fused.items(), key=lambda item: (-item[1], item[0]))[:k]
        hits = tuple(Hit(self.passages[i], score) for i, score in ranked)
        confidence = 0.0
        if hits and lexical:
            sources: list[str] = []
            for scored in lexical:
                source = self.passages[scored.index].source
                if source not in sources:
                    sources.append(source)
                if len(sources) == CONFIDENCE_SOURCES:
                    break
            confidence = max(coverage(terms, self.vocabulary[s], self.bm25) for s in sources)
        return RetrievalResult(
            query=query,
            hits=hits,
            confidence=round(confidence, 4),
            threshold=self.threshold,
            used_vectors=bool(vector_ids),
        )
