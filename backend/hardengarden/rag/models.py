"""Model catalog and hardware tiers (R36-R39).

Download sizes are the sizes published on ollama.com for the default quantization of each
tag. They are shown to the user BEFORE any download (R37); while downloading, the dialog
shows the exact byte count reported by Ollama itself. Verify these values against
https://ollama.com/library/qwen2.5/tags before each release (release checklist).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import StrEnum

from hardengarden.core.systemview import SystemView, SystemViewError

GIB = 1024**3


@dataclass(frozen=True, slots=True)
class ModelInfo:
    name: str
    download_bytes: int
    reduced_quality: bool = False

    @property
    def required_free_bytes(self) -> int:
        """Weights plus ~20 % runtime overhead and 512 MiB for context (R39)."""
        return int(self.download_bytes * 1.2) + 512 * 1024**2


QWEN_7B = ModelInfo("qwen2.5:7b-instruct", 4_700_000_000)
QWEN_3B = ModelInfo("qwen2.5:3b-instruct", 1_900_000_000)
QWEN_1_5B = ModelInfo("qwen2.5:1.5b-instruct", 986_000_000, reduced_quality=True)
NOMIC = ModelInfo("nomic-embed-text", 274_000_000)
CATALOG: dict[str, ModelInfo] = {m.name: m for m in (QWEN_7B, QWEN_3B, QWEN_1_5B, NOMIC)}
CHAT_MODELS = (QWEN_7B, QWEN_3B, QWEN_1_5B)


class Tier(StrEnum):
    BEST = "best"  # >= 16 GB
    STANDARD = "standard"  # 8-16 GB
    REDUCED = "reduced"  # 4-8 GB
    DISABLED = "disabled"  # < 4 GB or no Ollama


TIER_MODELS: dict[Tier, ModelInfo | None] = {
    Tier.BEST: QWEN_7B,
    Tier.STANDARD: QWEN_3B,
    Tier.REDUCED: QWEN_1_5B,
    Tier.DISABLED: None,
}

# "16 GB" machines report about 15.3-15.7 GiB of MemTotal because the kernel and firmware
# reserve some memory, so the boundaries sit slightly below the nominal sizes.
TIER_FLOORS_GIB: tuple[tuple[Tier, float], ...] = (
    (Tier.BEST, 15.0),
    (Tier.STANDARD, 7.5),
    (Tier.REDUCED, 3.5),
)


@dataclass(frozen=True, slots=True)
class Memory:
    total_bytes: int
    available_bytes: int


@dataclass(frozen=True, slots=True)
class Hardware:
    memory: Memory | None
    cpu_cores: int
    gpu: bool | None  # None = unknown (only Ollama can tell, once a model is loaded)


def read_memory(view: SystemView | None = None) -> Memory | None:
    """Parse ``/proc/meminfo`` without root."""
    try:
        text = (view or SystemView("/")).read_text("/proc/meminfo")
    except SystemViewError:
        return None
    values: dict[str, int] = {}
    for line in text.splitlines():
        key, _, rest = line.partition(":")
        parts = rest.split()
        if parts and parts[0].isdigit():
            values[key.strip()] = int(parts[0]) * 1024  # kB -> bytes
    if "MemTotal" not in values:
        return None
    return Memory(values["MemTotal"], values.get("MemAvailable", values.get("MemFree", 0)))


def detect_hardware(view: SystemView | None = None, *, gpu: bool | None = None) -> Hardware:
    return Hardware(memory=read_memory(view), cpu_cores=os.cpu_count() or 1, gpu=gpu)


def select_tier(total_bytes: int | None, *, ollama_available: bool) -> Tier:
    if not ollama_available or total_bytes is None:
        return Tier.DISABLED
    gib = total_bytes / GIB
    for tier, floor in TIER_FLOORS_GIB:
        if gib >= floor:
            return tier
    return Tier.DISABLED


def model_for(tier: Tier, override: str | None = None) -> ModelInfo | None:
    if override:
        return CATALOG.get(override)
    return TIER_MODELS[tier]


class InsufficientMemoryError(Exception):
    def __init__(self, model: ModelInfo, available: int) -> None:
        self.model = model
        self.available = available
        super().__init__(
            f"Not enough free memory for model {model.name} — "
            "close apps or switch to a smaller model"
        )


def ensure_memory(model: ModelInfo, memory: Memory | None) -> None:
    """R39: refuse to start a generation that would not fit in free memory."""
    if memory is not None and memory.available_bytes < model.required_free_bytes:
        raise InsufficientMemoryError(model, memory.available_bytes)
