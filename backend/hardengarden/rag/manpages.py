"""Optional runtime ingestion of the user's own man pages (R19).

Man pages are read from the local system through :class:`SystemView` at runtime, stored only
in the user's private data directory, and never committed or packaged.
"""

from __future__ import annotations

import json
import re
import zlib
from dataclasses import asdict, dataclass
from pathlib import Path

from hardengarden.core.systemview import SystemView, SystemViewError

PAGES = (
    ("sshd_config", "5"),
    ("sshd", "8"),
    ("sudoers", "5"),
    ("ufw", "8"),
    ("nft", "8"),
    ("shadow", "5"),
    ("passwd", "5"),
    ("sysctl.d", "5"),
    ("unattended-upgrade", "8"),
)
MAN_ROOT = "/usr/share/man"
MAX_DECOMPRESSED = 2 * 1024 * 1024
CHUNK_CHARS = 1200

_ESCAPES = (
    (re.compile(r"\\f(?:\[[^\]]*\]|\(..|.)"), ""),  # font changes
    (re.compile(r"\\\((em|en)"), "-"),
    (re.compile(r"\\\(..|\\\[[^\]]*\]"), ""),  # other named glyphs
    (re.compile(r"\\[-e]"), lambda m: "-" if m.group(0) == r"\-" else "\\"),
    (re.compile(r"\\[&|^%:]"), ""),
)


@dataclass(frozen=True, slots=True)
class ManChunk:
    id: str
    page: str
    text: str


def decompress(data: bytes) -> str:
    """Decompress a .gz page with a hard output cap (no decompression bombs)."""
    if data[:2] != b"\x1f\x8b":
        return data.decode("utf-8", "replace")
    inflater = zlib.decompressobj(16 + zlib.MAX_WBITS)
    out = inflater.decompress(data, MAX_DECOMPRESSED + 1)
    if len(out) > MAX_DECOMPRESSED or inflater.unconsumed_tail:
        msg = "decompressed man page exceeds the size limit"
        raise ValueError(msg)
    return out.decode("utf-8", "replace")


def roff_to_text(source: str) -> str:
    """Very small troff/mdoc to text conversion: good enough for retrieval, not display."""
    lines: list[str] = []
    for raw in source.splitlines():
        if raw.startswith(('.\\"', "'\\\"")) or raw.strip() in {".", "'"}:
            continue
        line = raw
        if line.startswith((".", "'")):
            parts = line[1:].split(None, 1)
            line = parts[1] if len(parts) > 1 else ""
            line = re.sub(
                r"\b(Cm|Ar|Fl|Pa|Ql|Dq|Sq|Em|Nm|Ic|Li|Xr|Va|Ev|Op|Oo|Oc|Ns)\b ?", "", line
            )
        for pattern, replacement in _ESCAPES:
            line = pattern.sub(replacement, line)
        if line.strip():
            lines.append(line.strip())
    return " ".join(lines)


def chunk_page(page: str, text: str) -> list[ManChunk]:
    words = text.split()
    chunks: list[ManChunk] = []
    buffer: list[str] = []
    size = 0
    for word in words:
        buffer.append(word)
        size += len(word) + 1
        if size >= CHUNK_CHARS:
            chunks.append(ManChunk(f"man:{page}#{len(chunks):04d}", page, " ".join(buffer)))
            buffer, size = [], 0
    if buffer:
        chunks.append(ManChunk(f"man:{page}#{len(chunks):04d}", page, " ".join(buffer)))
    return chunks


def read_manpages(view: SystemView) -> list[ManChunk]:
    chunks: list[ManChunk] = []
    for name, section in PAGES:
        for candidate in (
            f"{MAN_ROOT}/man{section}/{name}.{section}.gz",
            f"{MAN_ROOT}/man{section}/{name}.{section}",
        ):
            try:
                text = roff_to_text(decompress(view.read_bytes(candidate)))
            except (SystemViewError, ValueError):
                continue
            chunks.extend(chunk_page(f"{name}.{section}", text))
            break
    return chunks


def save_manpages(path: Path, chunks: list[ManChunk]) -> None:
    path.write_text(json.dumps([asdict(c) for c in chunks]), encoding="utf-8")
    path.chmod(0o600)


def load_manpages(path: Path) -> list[ManChunk]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return [
        ManChunk(str(c["id"]), str(c["page"]), str(c["text"])) for c in raw if isinstance(c, dict)
    ]
