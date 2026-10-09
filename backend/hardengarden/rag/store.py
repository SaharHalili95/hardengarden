"""Local ChromaDB vector store (embedded, persistent, telemetry off)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import chromadb
from chromadb.config import Settings

from hardengarden.core.paths import private_dir

KB_COLLECTION = "hardengarden-kb"
MAN_COLLECTION = "hardengarden-manpages"


@dataclass(frozen=True, slots=True)
class StoredItem:
    id: str
    text: str
    metadata: dict[str, str]
    embedding: Sequence[float]


@dataclass(frozen=True, slots=True)
class VectorHit:
    id: str
    similarity: float


class VectorStore:
    """Thin wrapper so the rest of the code never touches Chroma APIs directly."""

    def __init__(self, path: Path) -> None:
        self.path = private_dir(path)
        self._client = chromadb.PersistentClient(
            path=str(self.path),
            settings=Settings(anonymized_telemetry=False, allow_reset=False),
        )

    def _collection(self, name: str) -> Any:  # noqa: ANN401  # justification: chromadb's Collection type is not exported stably
        return self._client.get_or_create_collection(
            name, embedding_function=None, metadata={"hnsw:space": "cosine"}
        )

    def fingerprints(self, collection: str) -> dict[str, str]:
        """Map stored id -> its ``fingerprint`` metadata (content hash + embedding model)."""
        data = self._collection(collection).get(include=["metadatas"])
        result: dict[str, str] = {}
        for item_id, meta in zip(data["ids"], data["metadatas"] or [], strict=False):
            result[str(item_id)] = str((meta or {}).get("fingerprint", ""))
        return result

    def upsert(self, collection: str, items: Sequence[StoredItem]) -> None:
        if not items:
            return
        self._collection(collection).upsert(
            ids=[i.id for i in items],
            documents=[i.text for i in items],
            metadatas=[dict(i.metadata) for i in items],
            embeddings=[list(i.embedding) for i in items],
        )

    def delete(self, collection: str, ids: Sequence[str]) -> None:
        if ids:
            self._collection(collection).delete(ids=list(ids))

    def count(self, collection: str) -> int:
        return int(self._collection(collection).count())

    def query(self, collection: str, embedding: Sequence[float], k: int) -> list[VectorHit]:
        col = self._collection(collection)
        total = int(col.count())
        if total == 0:
            return []
        result = col.query(query_embeddings=[list(embedding)], n_results=min(k, total))
        ids = result["ids"][0]
        distances = (result.get("distances") or [[1.0] * len(ids)])[0]
        return [VectorHit(str(i), 1.0 - float(d)) for i, d in zip(ids, distances, strict=True)]
