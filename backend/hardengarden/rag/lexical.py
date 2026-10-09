"""Deterministic lexical retrieval (BM25) and an answerability signal.

This runs with no model at all, so knowledge-base search is reproducible, testable in CI
and available even when Ollama is not (R16). When an embedding model is available, its
ranking is fused with this one (see ``retrieve.py``).
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_STOPWORD_LINES = (
    "a about after all also am an and any are as at be been before being both but by can could",
    "did do does doing done during each else etc for from get gets got had has have having he",
    "her here him his how however i if in into is it its itself just let like make makes may me",
    "might more most much must my need needs no nor not now of off on once one only or other our",
    "out over own please same say says see seem she should so some such tell than that the their",
    "them then there these they this those through to too under until up us use used using very",
    "want was way we well were what when where whether which while who whom why will with would",
    "yes you your explain mean means instead really thing things something someone anything",
)
STOPWORDS = frozenset(" ".join(_STOPWORD_LINES).split())

# Minimum token lengths before a suffix is stripped, so short words stay intact.
_MIN_IES, _MIN_ING, _MIN_ED, _MIN_S = 5, 6, 5, 4


def stem(token: str) -> str:
    """Tiny suffix stripper: enough to match plurals and -ing/-ed forms."""
    if len(token) >= _MIN_IES and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) >= _MIN_ING and token.endswith("ing"):
        return token[:-3]
    if len(token) >= _MIN_ED and token.endswith("ed") and not token.endswith("eed"):
        return token[:-2]
    if len(token) >= _MIN_S and token.endswith("s") and not token.endswith(("ss", "us", "is")):
        return token[:-1]
    return token


def tokenize(text: str) -> list[str]:
    """Lower-case word tokens; CamelCase is split and also kept joined (PermitRootLogin)."""
    tokens: list[str] = []
    for raw in re.findall(r"[A-Za-z0-9_]+", text):
        parts = _CAMEL.sub(" ", raw.replace("_", " ")).lower().split()
        if len(parts) > 1:
            tokens.append("".join(parts))
        tokens.extend(parts)
    return [stem(t) for t in tokens if t not in STOPWORDS and len(t) > 1]


@dataclass(frozen=True, slots=True)
class Scored:
    index: int
    score: float


class BM25:
    def __init__(self, documents: list[list[str]], *, k1: float = 1.5, b: float = 0.75) -> None:
        self.k1, self.b = k1, b
        self.docs = [Counter(d) for d in documents]
        self.lengths = [len(d) for d in documents]
        self.avg = sum(self.lengths) / len(self.lengths) if self.lengths else 0.0
        n = len(documents)
        frequency: Counter[str] = Counter()
        for doc in self.docs:
            frequency.update(doc.keys())
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in frequency.items()}
        self.max_idf = math.log(1 + (n + 0.5) / 0.5)

    def term_idf(self, term: str) -> float:
        return self.idf.get(term, self.max_idf)

    def score(self, query: list[str]) -> list[Scored]:
        scored: list[Scored] = []
        for i, doc in enumerate(self.docs):
            total = 0.0
            norm = self.k1 * (1 - self.b + self.b * self.lengths[i] / (self.avg or 1.0))
            for term in set(query):
                tf = doc.get(term, 0)
                if tf:
                    total += self.idf[term] * tf * (self.k1 + 1) / (tf + norm)
            scored.append(Scored(i, total))
        return sorted(scored, key=lambda s: (-s.score, s.index))


def coverage(query: list[str], vocabulary: set[str], bm25: BM25) -> float:
    """IDF-weighted share of the query's terms that occur in ``vocabulary``.

    Terms unknown to the whole knowledge base get the maximum IDF, so off-topic questions
    ("sourdough bread") score near zero while on-topic ones score high.
    """
    terms = set(query)
    if not terms:
        return 0.0
    total = sum(bm25.term_idf(t) for t in terms)
    hit = sum(bm25.term_idf(t) for t in terms if t in vocabulary)
    return hit / total if total else 0.0
