"""Deterministic competing-hypotheses matrix over grounded evidence cards (ACH-light).

Per candidate: `support` = distinct chunks with a `points_to` card, `against` = distinct chunks with
a `clears` card, `kinds` = distinct evidence kinds among its `points_to` cards.
score = support + kind_bonus * (kinds - 1) - lam * against. The list is ranked by score (ties:
support, then name). The matrix ABSTAINS when the leader has fewer than `min_support` independent
chunks, or leads the runner-up by less than `margin`. The answer is always a `hypothesis`.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from detective_board.suspects.cards import Card


@dataclass
class Row:
    candidate: str
    support: int = 0
    against: int = 0
    kinds: int = 0
    score: float = 0.0
    quotes_for: list[str] = field(default_factory=list)
    quotes_against: list[str] = field(default_factory=list)


@dataclass
class Verdict:
    rows: list[Row]
    abstain: bool
    reason: str
    label: str = "hypothesis"

    @property
    def top(self) -> str | None:
        return self.rows[0].candidate if self.rows and not self.abstain else None


def build(
    cards: Sequence[Card],
    candidates: Sequence[str],
    *,
    lam: float = 1.0,
    kind_bonus: float = 0.5,
    min_support: int = 2,
    margin: float = 1.0,
) -> Verdict:
    rows = {c: Row(c) for c in candidates}
    f_chunks: dict[str, set[str]] = {c: set() for c in candidates}
    a_chunks: dict[str, set[str]] = {c: set() for c in candidates}
    kinds: dict[str, set[str]] = {c: set() for c in candidates}
    for card in cards:
        if card.candidate not in rows:
            continue
        r = rows[card.candidate]
        if card.effect == "points_to":
            if card.chunk_id not in f_chunks[card.candidate]:
                r.quotes_for.append(card.quote)
            f_chunks[card.candidate].add(card.chunk_id)
            kinds[card.candidate].add(card.kind)
        else:
            if card.chunk_id not in a_chunks[card.candidate]:
                r.quotes_against.append(card.quote)
            a_chunks[card.candidate].add(card.chunk_id)
    for c, r in rows.items():
        r.support, r.against, r.kinds = len(f_chunks[c]), len(a_chunks[c]), len(kinds[c])
        r.score = r.support + kind_bonus * max(0, r.kinds - 1) - lam * r.against
    ranked = sorted(rows.values(), key=lambda r: (-r.score, -r.support, r.candidate))
    if not ranked or ranked[0].support < min_support:
        return Verdict(
            ranked, True, f"top candidate has fewer than {min_support} independent chunks"
        )
    if len(ranked) > 1 and ranked[0].score - ranked[1].score < margin:
        return Verdict(ranked, True, f"lead over the runner-up is below {margin}")
    return Verdict(ranked, False, "")
