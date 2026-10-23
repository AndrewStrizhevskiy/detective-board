"""Query-focused windows over a chunk: whole sentences, exact char offsets, no mid-sentence cuts."""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

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
NAME_FACTOR = 0.6  # capitalised question words (names) identify the topic, not the answer
SAT_DAMP = 0.5  # how strongly story-wide words are discounted
MAX_FACTOR = 1.2  # hard cap = window_words * 1.2 (about 130 for the default 110)


def stem(w: str) -> str:
    for suf in _SUFFIX:
        if w.endswith(suf) and len(w) - len(suf) >= 3:
            return w[: -len(suf)]
    return w


def content_words(text: str) -> set[str]:
    return {stem(w) for w in _WORD.findall(text.lower()) if w not in STOP}


def idf_from_chunks(texts: list[str], stories: list[str] | None = None) -> dict[str, float]:
    """Word weight table; document = chunk. Deterministic.

    weight = ln(1 + N / (1 + df)), damped by (1 - saturation) where saturation is the highest
    share of one story's chunks that contain the word: names of the story's characters appear in
    most of its chunks and say nothing about which sentence holds the answer.
    """
    df: Counter[str] = Counter()
    per_story: dict[str, Counter[str]] = {}
    size: Counter[str] = Counter()
    for i, t in enumerate(texts):
        words = content_words(t)
        df.update(words)
        if stories:
            per_story.setdefault(stories[i], Counter()).update(words)
            size[stories[i]] += 1
    sat: dict[str, float] = {}
    for st, cnt in per_story.items():
        for w, c in cnt.items():
            sat[w] = max(sat.get(w, 0.0), c / size[st])
    n = len(texts)
    return {
        w: math.log(1 + n / (1 + c)) * (1 - SAT_DAMP * sat.get(w, 0.0))
        for w, c in sorted(df.items())
    }


@lru_cache(maxsize=4)
def idf_from_jsonl(path: str) -> Mapping[str, float]:
    """Weights over a chunks.jsonl file (cached per path). Missing file -> empty (plain overlap)."""
    p = Path(path)
    if not p.is_file():
        return {}
    rows = [json.loads(line) for line in p.read_text().splitlines() if line.strip()]
    return idf_from_chunks([r["text"] for r in rows], [r["story"] for r in rows])


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


def name_words(question: str) -> set[str]:
    """Stems of capitalised words that are not the first word of the question."""
    toks = re.findall(r"[^\W_]{3,}", question)
    first = re.match(r"\W*([^\W_]+)", question)
    skip = first.group(1) if first else ""
    return {stem(t.lower()) for t in toks if t[0].isupper() and t != skip}


def best_window(
    text: str, question: str, window_words: int = 110, idf: Mapping[str, float] | None = None
) -> Window:
    """Best contiguous run of whole sentences of about `window_words` words for the question."""
    spans = sentence_spans(text)
    if not spans:
        return Window(0, len(text), 0, 0.0)
    words = [len(text[a:b].split()) for a, b in spans]
    hi = max(1, int(window_words * MAX_FACTOR))
    if sum(words) <= hi:
        return Window(0, len(text), len(spans), 0.0)
    q = content_words(question)
    sent_words = [content_words(text[a:b]) for a, b in spans]
    if idf:  # words absent from the corpus are the rarest of all
        top = max(idf.values())
        weight = {w: idf.get(w, top) for w in q}
    else:
        weight = dict.fromkeys(q, 1.0)
    for w in (name_words(question) & weight.keys()) if idf else ():
        weight[w] *= NAME_FACTOR
    raw = [sum(weight[w] for w in q & sw) for sw in sent_words]
    best = max(range(len(spans)), key=lambda i: (raw[i], -i))  # first best sentence
    score = list(raw)
    unit = raw[best] / max(1, len(q & sent_words[best]))
    for j in (best - 1, best + 1):
        if 0 <= j < len(spans):
            score[j] += BONUS_ADJACENT * unit
    target = max(1, window_words)
    pick = (-1.0, 0, 0, 0)  # (score, -distance to target, -start, end)
    for i0 in range(len(spans)):
        total = 0
        acc = 0.0
        for j0 in range(i0, len(spans)):
            total += words[j0]
            if total > hi and j0 > i0:
                break
            acc += score[j0]
            cand = (round(acc, 9), -abs(total - target), -i0, j0)
            if cand > pick:
                pick = cand
    i, j = -pick[2], pick[3]
    start = 0 if i == 0 else spans[i][0]
    end = len(text) if j == len(spans) - 1 else spans[j][1]
    return Window(start, end, j - i + 1, sum(score[i : j + 1]))
