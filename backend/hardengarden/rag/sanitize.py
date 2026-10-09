"""Output safety for LLM text (R12, R15): plain text only, no runnable commands, no links.

The same rules run on the live token stream (line by line) and on the final answer, so what
the user sees while the answer streams is already sanitized.
"""

from __future__ import annotations

import re

COMMAND_REMOVED = "[command removed: use the HardenGarden remediation script]"
LINK_REMOVED = "[link removed]"

_FENCE = re.compile(r"^\s*(```|~~~)")
_MD_LINK = re.compile(r"!?\[([^\]]*)\]\((?:[^()\s]|\([^()]*\))*\)")
_URL = re.compile(r"\b(?:https?|ftp|file)://\S+|\bwww\.\S+", re.I)
_HTML_TAG = re.compile(r"</?[A-Za-z][^>]*>")
# Lines that look like something to paste into a shell.
_COMMAND_LINE = re.compile(
    r"^\s*(?:[$#>]\s+\S|sudo\b|su\s+-|(?:sh|bash|zsh)\s+-c\b|curl\b.*\|\s*(?:sh|bash)|"
    r"wget\b|chmod\b|chown\b|rm\s+-|echo\b.*>>?|sed\s+-i\b|systemctl\b|apt(?:-get)?\s+\w|"
    r"ufw\s+\w|nft\s+\w|usermod\b|passwd\b|visudo\b|sysctl\s+-w\b|cat\s+<<)",
    re.I,
)
_INLINE_COMMAND = re.compile(
    r"`([^`]*\b(?:sudo|chmod|chown|rm -|curl|wget|sed -i|systemctl|apt(?:-get)? install)\b[^`]*)`",
    re.I,
)
_UNTRUSTED_TAG = re.compile(
    r"</?\s*(untrusted_system_data|kb_passage|system|user|assistant)\b[^>]*>", re.I
)


def sanitize_line(line: str) -> str:
    if _COMMAND_LINE.match(line):
        return COMMAND_REMOVED
    line = _UNTRUSTED_TAG.sub("", line)
    line = _MD_LINK.sub(lambda m: m.group(1), line)
    line = _URL.sub(LINK_REMOVED, line)
    line = _HTML_TAG.sub("", line)
    return _INLINE_COMMAND.sub(COMMAND_REMOVED, line)


class StreamSanitizer:
    """Line-buffered sanitizer for streamed tokens. Code fences are dropped entirely."""

    def __init__(self) -> None:
        self._buffer = ""
        self._in_fence = False

    def _emit_line(self, line: str) -> str | None:
        if _FENCE.match(line):
            self._in_fence = not self._in_fence
            return COMMAND_REMOVED if self._in_fence else None
        if self._in_fence:
            return None
        return sanitize_line(line)

    def feed(self, text: str) -> str:
        self._buffer += text
        out: list[str] = []
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            emitted = self._emit_line(line)
            if emitted is not None:
                out.append(emitted + "\n")
        return "".join(out)

    def flush(self) -> str:
        rest, self._buffer = self._buffer, ""
        if not rest:
            return ""
        emitted = self._emit_line(rest)
        return emitted or ""


def sanitize_text(text: str) -> str:
    sanitizer = StreamSanitizer()
    result = sanitizer.feed(text) + sanitizer.flush()
    collapsed = re.sub(
        rf"(?:{re.escape(COMMAND_REMOVED)}\n?){{2,}}", COMMAND_REMOVED + "\n", result
    )
    return collapsed.strip()


def neutralize_untrusted(text: str) -> str:
    """Make system-derived text unable to close or forge prompt structure (R15)."""
    # Angle brackets become U+2039/U+203A so the text can never open or close a prompt tag.
    return text.replace("<", "\u2039").replace(">", "\u203a").replace("[kb:", "[kb-")
