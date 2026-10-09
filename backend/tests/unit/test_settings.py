"""Settings: loopback-only Ollama URL (ADR-002 #4), private storage, safe defaults."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from hardengarden.core.paths import cache_dir, data_dir
from hardengarden.core.settings import Settings, load_settings, save_settings, settings_path


def test_defaults() -> None:
    settings = Settings()
    assert settings.ollama_url == "http://127.0.0.1:11434"
    assert settings.embed_model == "nomic-embed-text"


@pytest.mark.parametrize(
    "url", ["http://10.1.1.1:11434", "http://example.com", "https://localhost"]
)
def test_remote_ollama_url_is_a_validation_error(url: str) -> None:
    with pytest.raises(ValidationError, match=r"must be one of|must use http"):
        Settings(ollama_url=url)
    settings = Settings()
    with pytest.raises(ValidationError):
        settings.ollama_url = url


def test_url_is_normalized() -> None:
    assert Settings(ollama_url="http://LOCALHOST:1234/").ollama_url == "http://localhost:1234"


def test_save_and_load_roundtrip(tmp_path: Path) -> None:
    saved = save_settings(Settings(ollama_url="http://[::1]:5000"), tmp_path / "data")
    assert saved.stat().st_mode & 0o777 == 0o600
    assert (tmp_path / "data").stat().st_mode & 0o777 == 0o700
    assert load_settings(tmp_path / "data").ollama_url == "http://[::1]:5000"


def test_missing_or_corrupt_file_gives_defaults(tmp_path: Path) -> None:
    assert load_settings(tmp_path) == Settings()
    settings_path(tmp_path).write_text("{not json")
    assert load_settings(tmp_path) == Settings()
    settings_path(tmp_path).write_text('{"ollama_url": "http://evil.example"}')
    assert load_settings(tmp_path) == Settings()


def test_xdg_directories(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "d"))
    monkeypatch.setenv("XDG_CACHE_HOME", "relative/ignored")
    assert data_dir() == tmp_path / "d" / "hardengarden"
    assert cache_dir() == Path.home() / ".cache" / "hardengarden"
