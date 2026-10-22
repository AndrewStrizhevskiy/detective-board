"""Quote grounding: is the model's `quote` a verbatim span of the chunk?

Comparison is whitespace- and typography-normalised (curly quotes, dashes, ellipsis). A quote
that only matches after normalisation counts as `exact` and is rewritten to the chunk's own
characters. Otherwise a high-threshold difflib re-anchoring is tried (`fuzzy`), else `none`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Literal

Grounded = Literal["exact", "fuzzy", "none"]

_MAP = {
    "‘": "'", "’": "'", "‚": "'", "‛": "'",
    "“": '"', "”": '"', "„": '"',
    "–": "-", "—": "-", "−": "-",
    "…": "...", " ": " ",
}  # fmt: skip
_WS = re.compile(r"\s+")


@dataclass(frozen=True)
class Normalised:
    text: str
    src: str  # original string
    idx: tuple[int, ...]  # normalised char -> original index of its source char
    ends: tuple[int, ...]  # normalised char -> original end (exclusive) of its source char(s)

    def span(self, a: int, b: int) -> str:
        """Original substring for normalised [a, b)."""
        return self.src[self.idx[a] : self.ends[b - 1]]


def normalise(s: str) -> Normalised:
    out: list[str] = []
    idx: list[int] = []
    ends: list[int] = []
    i, n = 0, len(s)
    while i < n:
        ch = s[i]
        if ch.isspace():
            j = i
            while j < n and s[j].isspace():
                j += 1
            out.append(" ")
            idx.append(i)
            ends.append(j)
            i = j
            continue
        rep = _MAP.get(ch, ch)
        for r in rep:
            out.append(r)
            idx.append(i)
            ends.append(i + 1)
        i += 1
    return Normalised("".join(out), s, tuple(idx), tuple(ends))


@dataclass(frozen=True)
class GroundResult:
    grounded: Grounded
    span: str | None = None  # the chunk's own text for the quote (exact/fuzzy)
    ratio: float = 0.0


def _snap(text: str, a: int, b: int) -> tuple[int, int]:
    """Widen/narrow [a, b) to word boundaries."""
    while a > 0 and text[a - 1].isalnum() and a < len(text) and text[a].isalnum():
        a -= 1
    while b < len(text) and b > 0 and text[b - 1].isalnum() and text[b].isalnum():
        b += 1
    return a, b


def ground_quote(
    quote: str, chunk: Normalised, *, threshold: float = 0.85, min_fuzzy_len: int = 12
) -> GroundResult:
    q = normalise(quote.strip()).text
    if not q:
        return GroundResult("none")
    pos = chunk.text.find(q)
    if pos >= 0:
        return GroundResult("exact", chunk.span(pos, pos + len(q)), 1.0)
    if len(q) < min_fuzzy_len:
        return GroundResult("none")
    sm = SequenceMatcher(None, chunk.text, q, autojunk=False)
    blocks = [m for m in sm.get_matching_blocks() if m.size >= 4]
    if not blocks:
        return GroundResult("none")
    best = max(blocks, key=lambda m: m.size)
    lo, hi = best.a - best.b - len(q), best.a - best.b + 2 * len(q)
    near = [m for m in blocks if lo <= m.a - m.b <= hi and abs(m.a - best.a) <= 2 * len(q)]
    first, last = min(near, key=lambda m: m.b), max(near, key=lambda m: m.b)
    a = max(0, first.a - first.b)
    b = min(len(chunk.text), last.a + last.size + (len(q) - last.b - last.size))
    a, b = _snap(chunk.text, a, b)
    cand = chunk.text[a:b].strip()
    if not cand:
        return GroundResult("none")
    ratio = SequenceMatcher(None, cand, q, autojunk=False).ratio()
    if ratio < threshold:
        return GroundResult("none", None, round(ratio, 3))
    a2 = a + (len(chunk.text[a:b]) - len(chunk.text[a:b].lstrip()))
    return GroundResult("fuzzy", chunk.span(a2, a2 + len(cand)), round(ratio, 3))
