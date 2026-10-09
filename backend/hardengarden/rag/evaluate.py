"""Retrieval evaluation against a golden set (Phase 2 metrics)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from hardengarden.rag.retrieve import Retriever


@dataclass(frozen=True, slots=True)
class EvalReport:
    answerable: int
    negative: int
    recall_at_5: float
    negative_rejection: float
    misses: list[str] = field(default_factory=list)
    false_accepts: list[str] = field(default_factory=list)
    used_vectors: bool = False


def load_golden(path: Path) -> dict[str, list[dict[str, str]]]:
    data: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        msg = "golden file must be a mapping with 'answerable' and 'negative'"
        raise TypeError(msg)
    return {
        "answerable": [dict(x) for x in data.get("answerable", [])],
        "negative": [dict(x) for x in data.get("negative", [])],
    }


def evaluate(retriever: Retriever, golden: dict[str, list[dict[str, str]]]) -> EvalReport:
    """Recall@5 counts a question only if it is accepted AND its doc is in the top 5."""
    misses: list[str] = []
    used_vectors = False
    for item in golden["answerable"]:
        result = retriever.search(item["q"], k=5)
        used_vectors = used_vectors or result.used_vectors
        if not (result.answerable and item["doc"] in result.sources):
            misses.append(f"{item['q']} (expected {item['doc']}, got {result.sources[:3]}, "
                          f"confidence {result.confidence})")  # fmt: skip
    false_accepts: list[str] = []
    for item in golden["negative"]:
        result = retriever.search(item["q"], k=5)
        if result.answerable:
            false_accepts.append(f"{item['q']} (confidence {result.confidence})")
    answerable, negative = len(golden["answerable"]), len(golden["negative"])
    return EvalReport(
        answerable=answerable,
        negative=negative,
        recall_at_5=round(1 - len(misses) / answerable, 4) if answerable else 0.0,
        negative_rejection=round(1 - len(false_accepts) / negative, 4) if negative else 0.0,
        misses=misses,
        false_accepts=false_accepts,
        used_vectors=used_vectors,
    )
