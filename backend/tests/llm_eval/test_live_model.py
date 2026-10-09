"""Live evaluation against a real local model (Phase 3 small-model evaluation).

Not part of the default run. Needs Ollama on 127.0.0.1 with the model under test plus
nomic-embed-text, and an ingested knowledge base:

    HG_EVAL_MODEL=qwen2.5:1.5b-instruct uv run pytest -m live tests/llm_eval -s

The bar is the same for every model (the spec forbids lowering it for small models):
grounded-answer rate >= 0.90 on answerable prompts, and 100 % refusal on negatives.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from hardengarden.checks import ALL_CHECKS
from hardengarden.core.engine import run_scan
from hardengarden.core.settings import Settings
from hardengarden.core.systemview import SystemView
from hardengarden.rag.assistant import Assistant, ExplanationCache
from hardengarden.rag.evaluate import load_golden
from hardengarden.rag.generate import Answer, Generation, Outcome
from hardengarden.rag.service import KnowledgeService

pytestmark = pytest.mark.live

MODEL = os.environ.get("HG_EVAL_MODEL", "qwen2.5:7b-instruct")
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "systems"
GOLDEN = Path(__file__).resolve().parents[1] / "rag_eval" / "golden.yaml"
GROUNDED_BAR = 0.90


def _finish(result: Generation | Answer) -> Answer:
    if isinstance(result, Generation):
        return result.run()
    return result


@pytest.fixture(scope="module")
def assistant(tmp_path_factory: pytest.TempPathFactory) -> Assistant:
    settings = Settings(chat_model=MODEL, generation_timeout_s=300)
    knowledge = KnowledgeService(settings, base=tmp_path_factory.mktemp("data"))
    knowledge.ingest()
    cache = ExplanationCache(tmp_path_factory.mktemp("cache"))
    return Assistant(settings, knowledge, cache=cache)


def test_explanations_are_grounded(assistant: Assistant) -> None:
    report = run_scan(SystemView(FIXTURES / "misconfigured" / "root"), ALL_CHECKS)
    outcomes: list[Outcome] = []
    for check in ALL_CHECKS:
        result = next(r for r in report.results if r.check_id == check.meta.id)
        answer = _finish(assistant.explain(check, result, use_cache=False))
        outcomes.append(answer.outcome)
        print(f"{MODEL} {check.meta.id}: {answer.outcome.value} {list(answer.citations)}")  # noqa: T201  # justification: evaluation report output
    grounded = outcomes.count(Outcome.ANSWERED) / len(outcomes)
    print(f"{MODEL} grounded explanation rate: {grounded:.2f}")  # noqa: T201  # justification: evaluation report output
    assert grounded >= GROUNDED_BAR


def test_questions_are_grounded_or_refused(assistant: Assistant) -> None:
    golden = load_golden(GOLDEN)
    answered = [_finish(assistant.chat(q["q"])) for q in golden["answerable"][::4]]
    rate = sum(a.outcome is Outcome.ANSWERED for a in answered) / len(answered)
    refused = [_finish(assistant.chat(q["q"])) for q in golden["negative"]]
    refusal = sum(a.outcome is Outcome.NOT_ENOUGH_INFORMATION for a in refused) / len(refused)
    print(f"{MODEL} grounded chat rate: {rate:.2f}; negative refusal: {refusal:.2f}")  # noqa: T201  # justification: evaluation report output
    assert rate >= GROUNDED_BAR
    assert refusal == 1.0
