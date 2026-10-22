"""Hybrid retrieval plus the relevance gate (score threshold and lexical support)."""

from __future__ import annotations

import re

from detective_board.retrieval import Hit

from .config import AgentConfig
from .events import GateTrace, HitTrace

_STOP = set(
    "the a an and or of to in on at by for with from is are was were be been did does do who whom "
    "whose what when where which why how that this these those it its his her their he she they "
    "them me you i we about after before into over under than then there as if not no yes any "
    "all can could would should will has have had tell say said story stories".split()
)
_W = re.compile(r"[a-z]+")


def terms(text: str) -> set[str]:
    """Content words, cut to a 5-letter prefix as a cheap stem."""
    return {w[:5] for w in _W.findall(text.lower()) if len(w) > 2 and w not in _STOP}


def support(question: str, hits: list[Hit]) -> tuple[float, list[str]]:
    """Best share of question terms found in one of the top-3 chunks; plus the missing terms."""
    q = terms(question)
    if not q or not hits:
        return 0.0, sorted(q)
    best, miss = 0.0, sorted(q)
    for h in hits[:3]:
        have = terms(h.text)
        share = len(q & have) / len(q)
        if share > best:
            best, miss = share, sorted(q - have)
    return best, miss


def gate(question: str, hits: list[Hit], cfg: AgentConfig) -> tuple[GateTrace, list[str]]:
    if not hits:
        return GateTrace(
            passed=False,
            best_score=0.0,
            threshold=cfg.min_score,
            support=0.0,
            min_support=cfg.min_support,
            reason="no hits",
        ), []
    best = hits[0].score
    sup, missing = support(question, hits)
    if best < cfg.min_score:
        reason = f"best score {best:.4f} below threshold {cfg.min_score}"
        ok = False
    elif sup < cfg.min_support:
        reason = f"top chunks cover {sup:.2f} of the question terms, need {cfg.min_support}"
        ok = False
    else:
        reason, ok = "relevant", True
    return GateTrace(
        passed=ok,
        best_score=best,
        threshold=cfg.min_score,
        support=round(sup, 3),
        min_support=cfg.min_support,
        reason=reason,
    ), missing


def hit_traces(hits: list[Hit]) -> list[HitTrace]:
    return [
        HitTrace(
            chunk_id=h.chunk_id,
            story=h.story,
            rank=i,
            rrf=h.score,
            ranks=dict(h.ranks),
            scores=dict(h.scores),
        )
        for i, h in enumerate(hits, 1)
    ]
