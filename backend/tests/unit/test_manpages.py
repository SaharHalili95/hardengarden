"""Runtime man-page ingestion (R19): bounded decompression, roff stripping, chunking."""

from __future__ import annotations

import gzip
from pathlib import Path

import pytest

from hardengarden.rag.kb import load_knowledge_base
from hardengarden.rag.manpages import (
    CHUNK_CHARS,
    MAX_DECOMPRESSED,
    chunk_page,
    decompress,
    load_manpages,
    read_manpages,
    roff_to_text,
    save_manpages,
)
from hardengarden.rag.retrieve import Retriever
from hgtest import make_view

# A synthetic page written for this test (not copied from any real manual).
ROFF = r""".\" synthetic test page
.TH DEMO 5
.SH NAME
demo \- a made\-up configuration file
.Sh DESCRIPTION
.It Cm FrobnicateLevel
Sets the \fBfrobnication\fR level\&. Higher values \(em such as 9 \(em frobnicate more\e.
.
"""


def test_roff_to_text() -> None:
    text = roff_to_text(ROFF)
    assert "synthetic" not in text  # comments dropped
    assert "demo - a made-up configuration file" in text
    assert "FrobnicateLevel" in text
    assert "Sets the frobnication level." in text
    assert "\\f" not in text


def test_decompress_plain_and_gzip() -> None:
    assert decompress(b"plain text") == "plain text"
    assert decompress(gzip.compress(b"zipped")) == "zipped"


def test_decompression_bomb_is_refused() -> None:
    bomb = gzip.compress(b"\0" * (MAX_DECOMPRESSED + 10))
    with pytest.raises(ValueError, match="size limit"):
        decompress(bomb)


def test_chunking_is_deterministic() -> None:
    text = " ".join(f"word{i}" for i in range(1000))
    chunks = chunk_page("demo.5", text)
    assert chunks == chunk_page("demo.5", text)
    assert chunks[0].id == "man:demo.5#0000"
    assert all(len(c.text) <= CHUNK_CHARS + 20 for c in chunks)
    assert " ".join(c.text for c in chunks) == text


def test_read_from_system_view_and_roundtrip(tmp_path: Path) -> None:
    view = make_view(tmp_path, {"/usr/share/man/man5/sudoers.5": ROFF})
    (view.root / "usr/share/man/man5/sshd_config.5.gz").write_bytes(gzip.compress(ROFF.encode()))
    chunks = read_manpages(view)
    assert {c.page for c in chunks} == {"sshd_config.5", "sudoers.5"}
    target = tmp_path / "m.json"
    save_manpages(target, chunks)
    assert target.stat().st_mode & 0o777 == 0o600
    assert load_manpages(target) == chunks
    assert load_manpages(tmp_path / "missing.json") == []


def test_manpage_text_is_searchable() -> None:
    chunks = chunk_page("demo.5", roff_to_text(ROFF))
    retriever = Retriever(load_knowledge_base(), manpages=chunks)
    result = retriever.search("What does FrobnicateLevel do?")
    assert result.hits[0].passage.source == "man:demo.5"
