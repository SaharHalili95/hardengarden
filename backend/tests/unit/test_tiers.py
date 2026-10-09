"""Hardware tiers, memory guard and consent-gated downloads (R36-R39)."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from fake_ollama import Script, fake_ollama
from hardengarden.core.settings import Settings
from hardengarden.rag.assistant import (
    AIState,
    ConsentRequiredError,
    UnknownModelError,
    compute_status,
    start_pull,
)
from hardengarden.rag.generate import Answer, OllamaChat, Outcome, prepare
from hardengarden.rag.kb import load_knowledge_base
from hardengarden.rag.models import (
    GIB,
    NOMIC,
    QWEN_1_5B,
    QWEN_3B,
    QWEN_7B,
    Hardware,
    InsufficientMemoryError,
    Memory,
    Tier,
    detect_hardware,
    ensure_memory,
    model_for,
    read_memory,
    select_tier,
)
from hardengarden.rag.ollama import OllamaClient
from hardengarden.rag.retrieve import Retriever
from hgtest import make_view


@pytest.mark.parametrize(
    ("gib", "tier", "model"),
    [
        (64, Tier.BEST, QWEN_7B),
        (15.6, Tier.BEST, QWEN_7B),  # a nominal 16 GB machine
        (15.0, Tier.BEST, QWEN_7B),
        (14.9, Tier.STANDARD, QWEN_3B),
        (7.7, Tier.STANDARD, QWEN_3B),  # a nominal 8 GB machine
        (7.4, Tier.REDUCED, QWEN_1_5B),
        (3.8, Tier.REDUCED, QWEN_1_5B),  # a nominal 4 GB machine
        (3.4, Tier.DISABLED, None),
        (1, Tier.DISABLED, None),
    ],
)
def test_tier_table(gib: float, tier: Tier, model: object) -> None:
    selected = select_tier(int(gib * GIB), ollama_available=True)
    assert selected is tier
    assert model_for(selected) == model


def test_no_ollama_or_unknown_memory_disables_ai() -> None:
    assert select_tier(64 * GIB, ollama_available=False) is Tier.DISABLED
    assert select_tier(None, ollama_available=True) is Tier.DISABLED


def test_override_and_reduced_quality_flag() -> None:
    assert model_for(Tier.BEST, "qwen2.5:1.5b-instruct") == QWEN_1_5B
    assert QWEN_1_5B.reduced_quality
    assert not QWEN_7B.reduced_quality
    assert NOMIC.download_bytes < QWEN_1_5B.download_bytes


def test_read_memory_from_proc(tmp_path: Path) -> None:
    view = make_view(
        tmp_path,
        {"/proc/meminfo": "MemTotal:  16000000 kB\nMemFree: 1 kB\nMemAvailable:  8000000 kB\n"},
    )
    assert read_memory(view) == Memory(16_000_000 * 1024, 8_000_000 * 1024)
    assert read_memory(make_view(tmp_path / "x", {"/proc/meminfo": "garbage\n"})) is None
    assert read_memory(make_view(tmp_path / "y", {"/etc/x": ""})) is None
    assert detect_hardware(view).cpu_cores >= 1


def test_memory_guard_message_and_block() -> None:
    low = Memory(16 * GIB, 1 * GIB)
    with pytest.raises(InsufficientMemoryError) as caught:
        ensure_memory(QWEN_7B, low)
    assert str(caught.value) == (
        "Not enough free memory for model qwen2.5:7b-instruct — "
        "close apps or switch to a smaller model"
    )
    ensure_memory(QWEN_1_5B, Memory(16 * GIB, 4 * GIB))
    ensure_memory(QWEN_7B, None)  # unknown memory: do not block


def test_low_memory_blocks_generation_before_any_model_call(tmp_path: Path) -> None:
    with fake_ollama() as (url, script):
        retrieval = Retriever(load_knowledge_base()).search("Should root log in over SSH?")
        result = prepare(
            OllamaChat(OllamaClient(url)),
            QWEN_7B,
            "q",
            retrieval,
            memory=Memory(16 * GIB, GIB // 2),
        )
        assert isinstance(result, Answer)
        assert result.outcome is Outcome.INSUFFICIENT_MEMORY
        assert script.chat_calls == 0


@pytest.mark.parametrize(
    ("installed", "memory", "override", "state"),
    [
        (["qwen2.5:7b-instruct"], Memory(32 * GIB, 20 * GIB), None, AIState.READY),
        ([], Memory(32 * GIB, 20 * GIB), None, AIState.MODEL_NOT_DOWNLOADED),
        (["qwen2.5:7b-instruct"], Memory(32 * GIB, 1 * GIB), None, AIState.NOT_ENOUGH_MEMORY),
        (["qwen2.5:1.5b-instruct"], Memory(6 * GIB, 4 * GIB), None, AIState.REDUCED_QUALITY),
        (["qwen2.5:3b-instruct"], Memory(2 * GIB, 1 * GIB), None, AIState.DISABLED),
        (
            ["qwen2.5:1.5b-instruct:latest"],
            Memory(32 * GIB, 20 * GIB),
            "qwen2.5:1.5b-instruct",
            AIState.REDUCED_QUALITY,
        ),
    ],
)
def test_ai_status_states(
    installed: list[str], memory: Memory, override: str | None, state: AIState
) -> None:
    with fake_ollama(Script(installed=installed)) as (url, _):
        status = compute_status(
            Settings(ollama_url=url, chat_model=override),
            OllamaClient(url),
            Hardware(memory, 4, None),
        )
        assert status.state is state
        assert status.tier_overridden is (override is not None)
        assert status.to_dict()["state"] == state.value


def test_ai_status_without_ollama() -> None:
    status = compute_status(
        Settings(ollama_url="http://127.0.0.1:9"), OllamaClient("http://127.0.0.1:9")
    )
    assert status.state is AIState.OLLAMA_NOT_INSTALLED
    assert "Scanning" in status.message


def test_gpu_detected_from_running_models() -> None:
    with fake_ollama(Script(vram=4 * GIB)) as (url, _):
        status = compute_status(Settings(ollama_url=url), OllamaClient(url))
        assert status.hardware.gpu is True


def test_no_download_without_explicit_consent() -> None:
    with fake_ollama() as (url, script):
        with pytest.raises(ConsentRequiredError):
            start_pull(OllamaClient(url), "qwen2.5:7b-instruct", consent=False)
        with pytest.raises(UnknownModelError):
            start_pull(OllamaClient(url), "evil/model", consent=True)
        assert script.pull_calls == 0


def test_consented_download_reports_progress() -> None:
    with fake_ollama() as (url, script):
        steps = list(start_pull(OllamaClient(url), "qwen2.5:1.5b-instruct", consent=True))
        assert steps[0].status == "pulling manifest"
        assert steps[-1].status == "success"
        assert [s.completed for s in steps if s.total] == [200, 400, 600, 800, 1000]
        assert script.pull_calls == 1


def test_download_can_be_cancelled() -> None:
    with fake_ollama(Script(pull_steps=100, pull_delay_s=0.1)) as (url, _):
        pull = start_pull(OllamaClient(url), "qwen2.5:1.5b-instruct", consent=True)
        threading.Timer(0.3, pull.cancel).start()
        seen = list(pull)
        assert pull.cancelled
        assert len(seen) < 50
