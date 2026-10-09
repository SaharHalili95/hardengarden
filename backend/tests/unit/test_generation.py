"""Grounded generation (R13-R16, R38) against the fake Ollama server."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from fake_ollama import Script, fake_ollama
from hardengarden.checks import ALL_CHECKS
from hardengarden.core.models import CheckResult, Status
from hardengarden.core.settings import Settings
from hardengarden.rag.assistant import Assistant, ExplanationCache
from hardengarden.rag.generate import (
    NOT_ENOUGH_INFORMATION,
    OLLAMA_MISSING,
    SEED,
    TEMPERATURE,
    UNGROUNDED,
    Answer,
    Generation,
    GenerationOptions,
    OllamaChat,
    Outcome,
    finalize,
    prepare,
    system_prompt,
)
from hardengarden.rag.kb import load_knowledge_base
from hardengarden.rag.models import QWEN_7B, Hardware, Memory
from hardengarden.rag.ollama import OllamaClient
from hardengarden.rag.retrieve import RetrievalResult, Retriever
from hardengarden.rag.service import KnowledgeService

ROOT_LOGIN = next(c for c in ALL_CHECKS if c.meta.id == "HG-SSH-001")
RICH = Hardware(Memory(32 * 1024**3, 24 * 1024**3), cpu_cores=8, gpu=None)


def _retrieval(question: str = "Should root log in over SSH?") -> RetrievalResult:
    return Retriever(load_knowledge_base()).search(question)


def _assistant(url: str, tmp_path: Path, hardware: Hardware = RICH) -> Assistant:
    settings = Settings(ollama_url=url, generation_timeout_s=10)
    return Assistant(
        settings,
        KnowledgeService(settings, base=tmp_path / "data"),
        cache=ExplanationCache(tmp_path / "cache"),
        hardware=hardware,
    )


def _result(evidence: list[str]) -> CheckResult:
    return CheckResult(check_id="HG-SSH-001", status=Status.FAIL, evidence=evidence, duration_ms=1)


# Pure behaviour of finalize()


def test_answer_with_valid_citation_is_kept() -> None:
    retrieval = _retrieval()
    cited = retrieval.hits[0].passage.id
    answer = finalize(f"It is risky [kb:{cited}].", retrieval, "m")
    assert answer.outcome is Outcome.ANSWERED
    assert answer.citations == (cited,)


def test_answer_without_citation_is_replaced() -> None:
    answer = finalize("Root login is fine, trust me.", _retrieval(), "m")
    assert (answer.outcome, answer.text) == (Outcome.UNGROUNDED, UNGROUNDED)


def test_invented_citations_do_not_count_and_are_removed() -> None:
    retrieval = _retrieval()
    real = retrieval.hits[0].passage.id
    only_fake = finalize("Claim [kb:made-up#x].", retrieval, "m")
    assert only_fake.outcome is Outcome.UNGROUNDED
    mixed = finalize(f"A [kb:{real}]. B [kb:made-up#x].", retrieval, "m")
    assert mixed.citations == (real,)
    assert "made-up" not in mixed.text


def test_model_refusal_token_gives_fixed_message() -> None:
    answer = finalize("NOT_ENOUGH_INFORMATION", _retrieval(), "m")
    assert (answer.outcome, answer.text) == (Outcome.NOT_ENOUGH_INFORMATION, NOT_ENOUGH_INFORMATION)


def test_system_prompt_is_the_repo_file() -> None:
    prompt = system_prompt()
    assert "untrusted_system_data" in prompt
    assert "NOT_ENOUGH_INFORMATION" in prompt
    assert "[kb:ID]" in prompt


# End to end against the fake Ollama server


def test_streamed_grounded_explanation(tmp_path: Path) -> None:
    with fake_ollama() as (url, script):
        assistant = _assistant(url, tmp_path)
        generation = assistant.explain(
            ROOT_LOGIN, _result(["PermitRootLogin yes (/etc/ssh/sshd_config:3)"])
        )
        assert isinstance(generation, Generation)
        chunks = list(generation)
        assert "".join(chunks).startswith("Root login is risky")
        answer = generation.answer
        assert answer is not None
        assert answer.outcome is Outcome.ANSWERED
        assert answer.citations == ("ssh-root-login#why-it-matters",)
        options = script.last_chat["options"]
        assert options == {"temperature": TEMPERATURE, "seed": SEED, "num_predict": 400}
        assert script.last_chat["messages"][0]["content"] == system_prompt()


def test_refusal_below_threshold_makes_no_model_call(tmp_path: Path) -> None:
    with fake_ollama() as (url, script):
        answer = _assistant(url, tmp_path).chat("How do I bake sourdough bread?")
        assert isinstance(answer, Answer)
        assert (answer.outcome, answer.text) == (
            Outcome.NOT_ENOUGH_INFORMATION,
            NOT_ENOUGH_INFORMATION,
        )
        assert script.chat_calls == 0


def test_ollama_down_gives_actionable_message(tmp_path: Path) -> None:
    assistant = _assistant("http://127.0.0.1:9", tmp_path)
    answer = assistant.explain(ROOT_LOGIN, _result([]))
    assert isinstance(answer, Answer)
    assert (answer.outcome, answer.text) == (Outcome.OLLAMA_UNAVAILABLE, OLLAMA_MISSING)
    chat = assistant.chat("Should root log in over SSH?")
    assert isinstance(chat, Answer)
    assert chat.outcome is Outcome.OLLAMA_UNAVAILABLE


def test_second_identical_explain_makes_zero_model_calls(tmp_path: Path) -> None:
    with fake_ollama() as (url, script):
        assistant = _assistant(url, tmp_path)
        first = assistant.explain(ROOT_LOGIN, _result(["PermitRootLogin yes"]))
        assert isinstance(first, Generation)
        first.run()
        assert script.chat_calls == 1
        second = assistant.explain(ROOT_LOGIN, _result(["PermitRootLogin yes"]))
        assert isinstance(second, Answer)
        assert second.cached
        assert second.citations == ("ssh-root-login#why-it-matters",)
        assert script.chat_calls == 1
        different = assistant.explain(ROOT_LOGIN, _result(["PermitRootLogin prohibit-password"]))
        assert isinstance(different, Generation)  # new evidence -> new key
        uncached = assistant.explain(ROOT_LOGIN, _result(["PermitRootLogin yes"]), use_cache=False)
        assert isinstance(uncached, Generation)


def test_ungrounded_answers_are_not_cached(tmp_path: Path) -> None:
    with fake_ollama(Script(reply="No citations here.")) as (url, script):
        assistant = _assistant(url, tmp_path)
        generation = assistant.explain(ROOT_LOGIN, _result([]))
        assert isinstance(generation, Generation)
        assert generation.run().outcome is Outcome.UNGROUNDED
        assert isinstance(assistant.explain(ROOT_LOGIN, _result([])), Generation)
        assert script.chat_calls == 1


def test_cache_files_are_private(tmp_path: Path) -> None:
    with fake_ollama() as (url, _):
        assistant = _assistant(url, tmp_path)
        generation = assistant.explain(ROOT_LOGIN, _result([]))
        assert isinstance(generation, Generation)
        generation.run()
    files = list((tmp_path / "cache").glob("*.json"))
    assert len(files) == 1
    assert files[0].stat().st_mode & 0o777 == 0o600
    assert (tmp_path / "cache").stat().st_mode & 0o777 == 0o700


def test_corrupt_cache_entry_is_ignored(tmp_path: Path) -> None:
    cache = ExplanationCache(tmp_path)
    (tmp_path / "abc.json").write_text("{broken")
    assert cache.get("abc") is None


# R38: hard timeout and cancel


def test_hard_timeout_stops_a_slow_model(tmp_path: Path) -> None:
    with fake_ollama(Script(reply=" ".join(["word"] * 50), token_delay_s=0.2)) as (url, _):
        client = OllamaClient(url)
        result = prepare(
            OllamaChat(client),
            QWEN_7B,
            "Should root log in over SSH?",
            _retrieval(),
            options=GenerationOptions(timeout_s=1.0),
        )
        assert isinstance(result, Generation)
        started = time.monotonic()
        answer = result.run()
        assert answer.outcome is Outcome.TIMEOUT
        assert time.monotonic() - started < 3.0


def test_cancel_stops_immediately_even_while_waiting_for_a_token(tmp_path: Path) -> None:
    with fake_ollama(Script(reply="one two three four", token_delay_s=5.0)) as (url, _):
        result = prepare(
            OllamaChat(OllamaClient(url)), QWEN_7B, "Should root log in over SSH?", _retrieval()
        )
        assert isinstance(result, Generation)
        threading.Timer(0.3, result.cancel).start()
        started = time.monotonic()
        answer = result.run()
        assert answer.outcome is Outcome.CANCELLED
        assert time.monotonic() - started < 2.0


def test_cancel_before_start(tmp_path: Path) -> None:
    with fake_ollama() as (url, _):
        result = prepare(
            OllamaChat(OllamaClient(url)), QWEN_7B, "Should root log in over SSH?", _retrieval()
        )
        assert isinstance(result, Generation)
        result.cancel()
        assert result.run().outcome is Outcome.CANCELLED


def test_model_error_is_reported(tmp_path: Path) -> None:
    result = prepare(
        OllamaChat(OllamaClient("http://127.0.0.1:9")), QWEN_7B, "Should root log in?", _retrieval()
    )
    assert isinstance(result, Generation)
    assert result.run().outcome is Outcome.OLLAMA_UNAVAILABLE


@pytest.mark.parametrize("timeout", [0.5])
def test_generation_respects_max_tokens_option(tmp_path: Path, timeout: float) -> None:
    with fake_ollama() as (url, script):
        result = prepare(
            OllamaChat(OllamaClient(url)), QWEN_7B, "Should root log in over SSH?", _retrieval(),
            options=GenerationOptions(timeout_s=10, max_tokens=128),
        )  # fmt: skip
        assert isinstance(result, Generation)
        result.run()
        assert script.last_chat["options"]["num_predict"] == 128
        assert timeout > 0
