"""Output safety for LLM text (R12, R15): plain text only, no runnable commands, no links.

The same rules run on the live token stream and on the final answer, so what the user sees
while the answer streams is already sanitized.
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


# First words that make a line look like a shell command, judged as soon as the first word
# is complete so the rest of the line is never streamed to the user.
_COMMAND_START = re.compile(
    r"^\s*(?:[$#>](?:\s|$)|(?:sudo|su|sh|bash|zsh|curl|wget|chmod|chown|rm|echo|sed|tee|dd|"
    r"systemctl|apt|apt-get|ufw|nft|iptables|usermod|useradd|userdel|passwd|visudo|sysctl|"
    r"cat|mkfs|kill|pkill|crontab)\b)",
    re.I,
)


def sanitize_fragment(text: str) -> str:
    """Rules that apply inside prose: tags, links, URLs, HTML and inline commands."""
    text = _UNTRUSTED_TAG.sub("", text)
    text = _MD_LINK.sub(lambda m: m.group(1), text)
    text = _URL.sub(LINK_REMOVED, text)
    text = _HTML_TAG.sub("", text)
    return _INLINE_COMMAND.sub(COMMAND_REMOVED, text)


def sanitize_line(line: str) -> str:
    if _COMMAND_LINE.match(line) or _COMMAND_START.match(line):
        return COMMAND_REMOVED
    return sanitize_fragment(line)


def _safe_cut(text: str) -> int:
    """Index up to which ``text`` can be emitted now: the last space before anything that is
    still open (an inline code span, a [link](...), an <html tag) and might change meaning."""
    cut = max(text.rfind(" "), text.rfind("\t")) + 1
    holds: list[int] = []
    if text.count("`") % 2:
        holds.append(text.rfind("`"))
    bracket = text.rfind("[")
    if bracket != -1 and (
        "]" not in text[bracket:]
        or ("](" in text[bracket:] and ")" not in text[text.index("](", bracket) :])
    ):
        holds.append(bracket)
    angle = text.rfind("<")
    if angle != -1 and ">" not in text[angle:]:
        holds.append(angle)
    if holds:
        cut = min(cut, *holds)
    return max(cut, 0)


class StreamSanitizer:
    """Streams sanitized text as tokens arrive, without waiting for whole lines.

    Each line is classified once its first word is complete: command-looking lines are
    suppressed entirely (one placeholder at the end of the line); code fences drop
    everything until they close; prose is emitted up to the last safe cut point.
    """

    def __init__(self) -> None:
        self._buffer = ""
        self._in_fence = False
        self._state: str | None = None  # None (unclassified), "prose" or "command"
        self._fence_candidate = False

    def _finish_line(self, rest: str, newline: str) -> str:
        state, self._state = self._state, None
        if state is None and _FENCE.match(rest):
            self._in_fence = not self._in_fence
            return COMMAND_REMOVED + newline if self._in_fence else ""
        if self._in_fence:
            return ""
        if state == "command" or (
            state is None and (_COMMAND_LINE.match(rest) or _COMMAND_START.match(rest))
        ):
            return COMMAND_REMOVED + newline
        return sanitize_fragment(rest) + newline

    def _partial(self) -> str:
        if self._in_fence:
            return ""
        if self._state is None:
            stripped = self._buffer.lstrip()
            if stripped.startswith(("`", "~")) or not re.match(r"\s*\S+\s", self._buffer):
                return ""  # wait: possible fence, or first word still incomplete
            is_command = _COMMAND_LINE.match(self._buffer) or _COMMAND_START.match(self._buffer)
            self._state = "command" if is_command else "prose"
        if self._state == "command":
            return ""
        cut = _safe_cut(self._buffer)
        if cut <= 0:
            return ""
        emitted, self._buffer = self._buffer[:cut], self._buffer[cut:]
        return sanitize_fragment(emitted)

    def feed(self, text: str) -> str:
        self._buffer += text
        out: list[str] = []
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            out.append(self._finish_line(line, "\n"))
        out.append(self._partial())
        return "".join(out)

    def flush(self) -> str:
        rest, self._buffer = self._buffer, ""
        if not rest and self._state is None:
            return ""
        return self._finish_line(rest, "")


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
