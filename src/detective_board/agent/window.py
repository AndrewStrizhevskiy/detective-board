"""Query-focused windows over a chunk: whole sentences, exact char offsets, no mid-sentence cuts."""

from __future__ import annotations

import re
from dataclasses import dataclass

_WORD = re.compile(r"[^\W_]{3,}")
STOP = frozenset(
    "the and for are was were has have had not but with from that this these those its his her "
    "their they them she him you your our out who whom what when where which while into onto "
    "than then there here been being will would could should can may might did does done also "
    "any all one two per via about after before over under upon very more most some such only "
    "because said says say tell story stories".split()
)
_SUFFIX = ("ing", "ed", "es", "s")
_ABBR = frozenset("dr mr mrs ms st no capt col messrs jr sr mt vs gen lt sgt inspector".split())
_END = re.compile(r"[.!?]+[\"”’')\]]*\s+")
BONUS_ADJACENT = 0.5
MAX_FACTOR = 1.2  # hard cap = window_words * 1.2 (about 130 for the default 110)


def stem(w: str) -> str:
    for suf in _SUFFIX:
        if w.endswith(suf) and len(w) - len(suf) >= 3:
            return w[: -len(suf)]
    return w


def content_words(text: str) -> set[str]:
    return {stem(w) for w in _WORD.findall(text.lower()) if w not in STOP}


@dataclass(frozen=True)
class Window:
    start: int  # offsets in the chunk text: text[start:end]
    end: int
    sentences: int
    score: float


def sentence_spans(text: str) -> list[tuple[int, int]]:
    """(start, end) of each sentence, trimmed of surrounding whitespace, in chunk offsets."""
    spans: list[tuple[int, int]] = []
    pos = 0
    for m in _END.finditer(text):
        nxt = text[m.end() : m.end() + 1]
        if nxt and nxt.islower():  # '"Where?" said Holmes.' is one sentence
            continue
        word = re.search(r"(\w+)\W*$", text[pos : m.start() + 1])
        if (
            word
            and m.group().startswith(".")
            and (
                word.group(1).lower() in _ABBR
                or (len(word.group(1)) == 1 and word.group(1).isupper())
            )
        ):
            continue
        _add(spans, text, pos, m.start() + len(m.group().rstrip()))
        pos = m.end()
    _add(spans, text, pos, len(text))
    return spans


def _add(spans: list[tuple[int, int]], text: str, a: int, b: int) -> None:
    seg = text[a:b]
    if seg.strip():
        a += len(seg) - len(seg.lstrip())
        b -= len(seg) - len(seg.rstrip())
        spans.append((a, b))


def best_window(text: str, question: str, window_words: int = 110) -> Window:
    """Best contiguous run of whole sentences of about `window_words` words for the question."""
    spans = sentence_spans(text)
    if not spans:
        return Window(0, len(text), 0, 0.0)
    words = [len(text[a:b].split()) for a, b in spans]
    hi = max(1, int(window_words * MAX_FACTOR))
    if sum(words) <= hi:
        return Window(0, len(text), len(spans), 0.0)
    q = content_words(question)
    raw = [float(len(q & content_words(text[a:b]))) for a, b in spans]
    best = max(range(len(spans)), key=lambda i: (raw[i], -i))  # first best sentence
    score = list(raw)
    for j in (best - 1, best + 1):
        if 0 <= j < len(spans):
            score[j] += BONUS_ADJACENT
    i = j = best
    total = words[best]
    target = max(1, window_words)
    while total < target:
        left = words[i - 1] if i > 0 else None
        right = words[j + 1] if j + 1 < len(spans) else None
        ok_l = left is not None and total + left <= hi
        ok_r = right is not None and total + right <= hi
        if not (ok_l or ok_r):
            break
        take_right = ok_r and (
            not ok_l or score[j + 1] >= score[i - 1]
        )  # tie: read forward, the answer usually follows
        if take_right:
            j += 1
            total += words[j]
        else:
            i -= 1
            total += words[i]
    start = 0 if i == 0 else spans[i][0]
    end = len(text) if j == len(spans) - 1 else spans[j][1]
    return Window(start, end, j - i + 1, sum(score[i : j + 1]))
