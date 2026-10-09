"""Phase 2 gate metrics: Recall@5 >= 0.90 and negative rejection >= 0.95 (keyword mode).

Keyword mode is fully deterministic, so these numbers are reproducible in CI. The same
evaluation with the real embedding model runs via ``hardengarden kb eval`` on a machine with
Ollama (documented in the Phase 2 report).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hardengarden.checks import ALL_CHECKS
from hardengarden.core.settings import Settings
from hardengarden.rag.evaluate import evaluate, load_golden
from hardengarden.rag.kb import load_knowledge_base
from hardengarden.rag.retrieve import Retriever
from hardengarden.rag.service import KnowledgeService
from hgtest import HashEmbedder

HERE = Path(__file__).parent
GOLDEN = HERE / "golden.yaml"
HOLDOUT = HERE / "holdout.yaml"


def test_golden_set_shape() -> None:
    golden = load_golden(GOLDEN)
    assert len(golden["answerable"]) + len(golden["negative"]) >= 40
    assert len(golden["negative"]) >= 5
    slugs = {c.meta.kb_doc.removeprefix("knowledge/").removesuffix(".md") for c in ALL_CHECKS}
    for slug in slugs:
        assert sum(1 for q in golden["answerable"] if q["doc"] == slug) >= 3, slug


@pytest.mark.parametrize("path", [GOLDEN, HOLDOUT], ids=["golden", "holdout"])
def test_keyword_retrieval_meets_the_bar(path: Path) -> None:
    report = evaluate(Retriever(load_knowledge_base()), load_golden(path))
    assert report.recall_at_5 >= 0.90, report.misses
    assert report.negative_rejection >= 0.95, report.false_accepts
    assert not report.used_vectors


def test_hybrid_retrieval_keeps_the_bar_and_the_refusals(tmp_path: Path) -> None:
    """Vector fusion only re-ranks; it must not lower recall or accept off-topic questions."""
    embedder = HashEmbedder()
    service = KnowledgeService(Settings(), base=tmp_path, embedder=embedder)
    service.ingest()
    retriever = service.retriever()
    report = evaluate(retriever, load_golden(GOLDEN))
    assert report.used_vectors
    assert report.recall_at_5 >= 0.90, report.misses
    assert report.negative_rejection >= 0.95, report.false_accepts
