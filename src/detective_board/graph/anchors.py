"""Resolve a verbatim `quote` to offsets inside its chunk (graph zone, not done by the LLM)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

AnchorStatus = Literal["exact", "ws_normalised", "ambiguous", "missing"]


@dataclass(frozen=True)
class ChunkRef:
    """Chunk identity and text; `char_start` is the offset of `text` in the clean story text."""

    chunk_id: str
    story: str
    char_start: int
    char_end: int
    text: str
    contiguous: bool = True  # False: clean[char_start:char_end] != text, only rel offsets valid

    @classmethod
    def from_record(cls, rec: dict[str, Any], clean_text: str | None = None) -> ChunkRef:
        """From a `data/chunks.jsonl` record. With `clean_text` the contiguity check is done."""
        ok = True
        if clean_text is not None:
            ok = clean_text[rec["char_start"] : rec["char_end"]] == rec["text"]
        return cls(
            chunk_id=rec["chunk_id"],
            story=rec["story"],
            char_start=rec["char_start"],
            char_end=rec["char_end"],
            text=rec["text"],
            contiguous=ok,
        )


@dataclass(frozen=True)
class ResolvedQuote:
    status: AnchorStatus
    rel_start: int | None = None
    rel_end: int | None = None
    n_matches: int = 0
    quote: str = ""  # the actual chunk span (== text[rel_start:rel_end])

    @property
    def found(self) -> bool:
        return self.status != "missing"

    @property
    def ambiguous(self) -> bool:
        return self.status == "ambiguous"


def resolve_quote(text: str, quote: str) -> ResolvedQuote:
    """Exact substring first (first match wins, `ambiguous` if it occurs more than once);
    then a whitespace-insensitive match; otherwise `missing` (grounding failure)."""
    q = quote.strip()
    if not q:
        return ResolvedQuote("missing")
    starts: list[int] = []
    i = text.find(q)
    while i != -1:
        starts.append(i)
        i = text.find(q, i + 1)
    if starts:
        s = starts[0]
        return ResolvedQuote(
            "ambiguous" if len(starts) > 1 else "exact", s, s + len(q), len(starts), q
        )
    toks = q.split()
    pat = re.compile(r"\s+".join(re.escape(t) for t in toks))
    allm = list(pat.finditer(text))
    if not allm:
        return ResolvedQuote("missing")
    first = allm[0]
    return ResolvedQuote(
        "ambiguous" if len(allm) > 1 else "ws_normalised",
        first.start(),
        first.end(),
        len(allm),
        text[first.start() : first.end()],
    )
