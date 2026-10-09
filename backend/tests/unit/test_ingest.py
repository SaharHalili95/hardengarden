"""Ingestion: idempotent, incremental, deterministic IDs, no network egress (R7)."""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any

import pytest

from hardengarden.core.settings import Settings
from hardengarden.rag.ingest import ingest_knowledge_base, ingest_manpages
from hardengarden.rag.kb import load_knowledge_base
from hardengarden.rag.manpages import ManChunk
from hardengarden.rag.ollama import OllamaUnavailableError
from hardengarden.rag.service import KnowledgeService
from hardengarden.rag.store import KB_COLLECTION, MAN_COLLECTION, VectorStore
from hgtest import HashEmbedder

REPO_KB = Path(__file__).resolve().parents[3] / "knowledge"
_connects: list[Any] = []
_watch = False


def _hook(event: str, args: tuple[Any, ...]) -> None:
    if _watch and event == "socket.connect":
        _connects.append(args[1])


sys.addaudithook(_hook)


def _copy_kb(tmp_path: Path) -> Path:
    target = tmp_path / "kb"
    target.mkdir()
    for path in REPO_KB.glob("*.md"):
        (target / path.name).write_text(path.read_text())
    return target


def test_ingestion_is_idempotent_and_incremental(tmp_path: Path) -> None:
    kb_dir = _copy_kb(tmp_path)
    store = VectorStore(tmp_path / "vectors")
    embedder = HashEmbedder()
    kb = load_knowledge_base(kb_dir)
    first = ingest_knowledge_base(kb, store, embedder)
    assert (first.added, first.updated, first.removed) == (len(kb.chunks()), 0, 0)
    assert store.count(KB_COLLECTION) == len(kb.chunks())

    calls = embedder.calls
    second = ingest_knowledge_base(load_knowledge_base(kb_dir), store, embedder)
    assert (second.added, second.updated, second.removed, second.unchanged) == (
        0,
        0,
        0,
        len(kb.chunks()),
    )
    assert embedder.calls == calls  # nothing re-embedded
    assert store.count(KB_COLLECTION) == len(kb.chunks())

    aslr = kb_dir / "aslr.md"
    aslr.write_text(aslr.read_text().replace("## How to fix\n", "## How to fix\nEdited.\n"))
    third = ingest_knowledge_base(load_knowledge_base(kb_dir), store, embedder)
    assert (third.added, third.updated, third.removed) == (0, 1, 0)

    (kb_dir / "aslr.md").unlink()
    fourth = ingest_knowledge_base(load_knowledge_base(kb_dir), store, embedder)
    assert fourth.removed == 5
    assert store.count(KB_COLLECTION) == len(kb.chunks()) - 5


def test_changing_the_embedding_model_reembeds_everything(tmp_path: Path) -> None:
    store = VectorStore(tmp_path / "v")
    kb = load_knowledge_base(REPO_KB)
    ingest_knowledge_base(kb, store, HashEmbedder("model-a"))
    report = ingest_knowledge_base(kb, store, HashEmbedder("model-b"))
    assert report.updated == len(kb.chunks())


def test_manpage_collection_is_separate(tmp_path: Path) -> None:
    store = VectorStore(tmp_path / "v")
    chunks = [ManChunk("man:x.5#0000", "x.5", "text one"), ManChunk("man:x.5#0001", "x.5", "two")]
    report = ingest_manpages(chunks, store, HashEmbedder(), "v1")
    assert report.added == 2
    assert store.count(MAN_COLLECTION) == 2
    assert store.count(KB_COLLECTION) == 0


def test_store_directory_is_private(tmp_path: Path) -> None:
    VectorStore(tmp_path / "vectors")
    assert (tmp_path / "vectors").stat().st_mode & 0o777 == 0o700


def test_ingest_and_query_make_no_network_connections(tmp_path: Path) -> None:
    global _watch  # noqa: PLW0603  # justification: audit hooks cannot be removed; a flag gates them
    embedder = HashEmbedder()
    service = KnowledgeService(Settings(), base=tmp_path, embedder=embedder)
    _connects.clear()
    _watch = True
    try:
        service.ingest()
        service.retriever().search("Should root log in over ssh?")
    finally:
        _watch = False
    assert _connects == []


def test_ingestion_is_fast(tmp_path: Path) -> None:
    service = KnowledgeService(Settings(), base=tmp_path, embedder=HashEmbedder())
    started = time.perf_counter()
    service.ingest()
    assert time.perf_counter() - started < 60


def test_without_ollama_ingest_reports_keyword_only(tmp_path: Path) -> None:
    service = KnowledgeService(Settings(ollama_url="http://127.0.0.1:9"), base=tmp_path)
    summary = service.ingest()
    assert summary.vector_reports == ()
    assert summary.vectors_skipped_reason is not None
    assert "Keyword search still works" in summary.vectors_skipped_reason
    retriever = service.retriever()
    result = retriever.search("What permissions should /etc/shadow have?")
    assert result.answerable
    assert not result.used_vectors


def test_ollama_vanishing_after_ingest_falls_back_to_keywords(tmp_path: Path) -> None:
    settings = Settings(ollama_url="http://127.0.0.1:9")
    KnowledgeService(settings, base=tmp_path, embedder=HashEmbedder()).ingest()
    service = KnowledgeService(settings, base=tmp_path)  # real Ollama embedder, unreachable
    with pytest.raises(OllamaUnavailableError):
        service.embedder().embed_query("x")
    result = service.retriever().search("What does randomize_va_space 2 mean?")
    assert result.answerable
    assert not result.used_vectors
