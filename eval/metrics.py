"""Mechanical metrics for eval/run_eval.py (stdlib only, no model, no judge).

Every function takes plain dicts and lists so it can be unit-tested with hand-made cases
(tests/eval/test_metrics.py). Definitions follow issue #6 and eval/golden/README.md:

- citation correctness: the quote is a verbatim substring of the cited chunk (whitespace and
  quote-mark tolerant, the same matcher as the gold builder) AND the chunk is a gold chunk;
- answer-sentence hit: a cited quote overlaps a gold quote span in the story text;
- refusal precision / recall on out-of-corpus questions, false-refusal rate on answerable ones;
- retrieval recall@k at chunk level (any gold chunk in the top k);
- contradiction detection: precision, recall, false-positive rate on controls (one decision per item);
- Wilson 95 % intervals for every share and an exact McNemar test for paired configurations.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Sequence
from typing import Any

Spans = Callable[
    [str, str], list[tuple[int, int]]
]  # (text, quote) -> spans, e.g. chunk_gold.find_spans

Z95 = 1.959963984540054


def wilson(k: int, n: int, z: float = Z95) -> tuple[float, float]:
    """Wilson score interval for k successes out of n; (0, 1) when n is 0."""
    if n <= 0:
        return (0.0, 1.0)
    p = k / n
    den = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (max(0.0, centre - half), min(1.0, centre + half))


def share(k: int, n: int) -> dict[str, Any]:
    """A proportion with its n and Wilson interval; value None when n is 0 (never 0/0 = 0)."""
    lo, hi = wilson(k, n)
    return {"k": k, "n": n, "value": (k / n) if n else None, "ci95": [round(lo, 4), round(hi, 4)]}


def mcnemar_exact(b: int, c: int) -> float:
    """Two-sided exact McNemar p-value from the discordant pairs (b: only A right, c: only B right)."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / 2**n
    return min(1.0, 2 * tail)


def paired(a: dict[str, bool], b: dict[str, bool]) -> dict[str, Any]:
    """Paired comparison of two configurations on the same questions (ids in both)."""
    ids = sorted(set(a) & set(b))
    only_a = sum(1 for i in ids if a[i] and not b[i])
    only_b = sum(1 for i in ids if b[i] and not a[i])
    return {
        "n": len(ids),
        "only_a": only_a,
        "only_b": only_b,
        "p_mcnemar": round(mcnemar_exact(only_a, only_b), 4),
    }


# ----------------------------------------------------------------------------- citations


def unique_citations(citations: Iterable[dict]) -> list[dict]:
    """Drop duplicate citations (same chunk, same quote after whitespace folding)."""
    seen: set[tuple[str, str]] = set()
    out = []
    for c in citations:
        key = (str(c.get("chunk_id", "")), " ".join(str(c.get("quote", "")).split()))
        if key in seen or not key[1]:
            continue
        seen.add(key)
        out.append(c)
    return out


def citation_verdicts(
    citations: Iterable[dict], chunk_text: dict[str, str], gold_chunks: Sequence[str], spans: Spans
) -> list[dict]:
    """Per unique citation: verbatim in its chunk, in a gold chunk, and correct (both)."""
    gold = set(gold_chunks)
    out = []
    for c in unique_citations(citations):
        cid = str(c.get("chunk_id", ""))
        text = chunk_text.get(cid)
        verbatim = bool(text) and bool(spans(text, str(c["quote"])))
        in_gold = cid in gold
        out.append(
            {
                "chunk_id": cid,
                "verbatim": verbatim,
                "gold_chunk": in_gold,
                "correct": verbatim and in_gold,
            }
        )
    return out


def answer_sentence_hit(
    citations: Iterable[dict],
    story_text: dict[str, str],
    gold_spans: Sequence[tuple[str, int, int]],
    spans: Spans,
) -> bool:
    """True when a cited quote overlaps a gold quote span in the story text."""
    for c in unique_citations(citations):
        story = str(c.get("story", ""))
        text = story_text.get(story)
        if not text:
            continue
        for s, e in spans(text, str(c["quote"])):
            if any(gs == story and s < ge and gs_ < e for gs, gs_, ge in gold_spans):
                return True
    return False


# ----------------------------------------------------------------------------- answers


def refusal_counts(rows: Iterable[dict]) -> dict[str, Any]:
    """rows: {answerable: bool, refused: bool}. Precision and recall of refusing out-of-corpus
    questions, and the false-refusal rate on answerable ones."""
    rows = list(rows)
    refused = [r for r in rows if r["refused"]]
    unanswerable = [r for r in rows if not r["answerable"]]
    answerable = [r for r in rows if r["answerable"]]
    tp = sum(1 for r in refused if not r["answerable"])
    return {
        "refusal_precision": share(tp, len(refused)),
        "refusal_recall": share(tp, len(unanswerable)),
        "false_refusal_rate": share(sum(1 for r in answerable if r["refused"]), len(answerable)),
    }


def recall_at_k(ranked: Sequence[str], gold: Sequence[str], k: int) -> bool | None:
    """Any gold chunk among the first k retrieved; None when the question has no gold chunk."""
    if not gold:
        return None
    return bool(set(ranked[:k]) & set(gold))


# ----------------------------------------------------------------------------- contradictions


def detection(items: Iterable[dict]) -> dict[str, Any]:
    """items: {expected: bool, found: bool}. One decision per item (eval/golden/README.md)."""
    items = list(items)
    tp = sum(1 for i in items if i["expected"] and i["found"])
    fp = sum(1 for i in items if not i["expected"] and i["found"])
    fn = sum(1 for i in items if i["expected"] and not i["found"])
    tn = sum(1 for i in items if not i["expected"] and not i["found"])
    p, r = share(tp, tp + fp), share(tp, tp + fn)
    f1 = None
    if p["value"] is not None and r["value"] is not None and (p["value"] + r["value"]) > 0:
        f1 = 2 * p["value"] * r["value"] / (p["value"] + r["value"])
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "precision": p,
        "recall": r,
        "f1": f1,
        "fp_rate_controls": share(fp, fp + tn),
    }
