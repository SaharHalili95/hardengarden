"""User settings, stored as JSON in the private data directory (0600)."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from hardengarden.core.paths import data_dir, private_dir
from hardengarden.rag.models import CHAT_MODELS
from hardengarden.rag.ollama import DEFAULT_URL, parse_endpoint

SETTINGS_FILE = "settings.json"


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    ollama_url: str = DEFAULT_URL
    embed_model: str = Field(default="nomic-embed-text", min_length=1, max_length=100)
    retrieval_threshold: float = Field(default=0.30, gt=0.0, le=1.0)
    chat_model: str | None = None  # None = pick by hardware tier (R36)
    generation_timeout_s: int = Field(default=120, ge=10, le=600)
    max_tokens: int = Field(default=400, ge=64, le=1024)

    @field_validator("chat_model")
    @classmethod
    def _known_chat_model(cls, value: str | None) -> str | None:
        if value is not None and value not in {m.name for m in CHAT_MODELS}:
            msg = f"chat_model must be one of {[m.name for m in CHAT_MODELS]}"
            raise ValueError(msg)
        return value

    @field_validator("ollama_url")
    @classmethod
    def _loopback_only(cls, value: str) -> str:
        return parse_endpoint(value).url  # raises EndpointNotAllowedError (a ValueError)


def settings_path(base: Path | None = None) -> Path:
    return (base or data_dir()) / SETTINGS_FILE


def load_settings(base: Path | None = None) -> Settings:
    path = settings_path(base)
    try:
        return Settings.model_validate(json.loads(path.read_text(encoding="utf-8")))
    except FileNotFoundError:
        return Settings()
    except (OSError, json.JSONDecodeError, ValidationError):
        return Settings()


def save_settings(settings: Settings, base: Path | None = None) -> Path:
    directory = private_dir(base or data_dir())
    path = directory / SETTINGS_FILE
    tmp = path.with_suffix(".tmp")
    tmp.write_text(settings.model_dump_json(indent=2), encoding="utf-8")
    tmp.chmod(0o600)
    tmp.replace(path)
    return path
