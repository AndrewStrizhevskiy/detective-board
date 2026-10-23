"""Answer composer: parse [n: "quote"] citations, map them to anchors, mechanical self-check."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .context import REFUSAL_TEXT, Source
from .events import Anchor, Citation, CitationTrace, ProvenanceLabel

CITATION = re.compile(r'\[(\d+)(?:\s*:\s*"(.+?)")?\s*\]', re.S)
_EXEMPT = re.compile(r"^\W*(unknown\b|not (stated|found|mentioned|covered)\b)", re.I)
_MARK = "\x00{}\x00"


@dataclass
class Claim:
    text: str
    cites: list[tuple[int, str | None]]
    ok: bool = False


@dataclass
class CheckResult:
    ok: bool
    claims: list[Claim]
    traces: list[CitationTrace]
    unsupported: list[str]
    problems: list[str]
    partial_text: str = ""
    refusal_like: bool = False

    @property
    def has_verified(self) -> bool:
        return bool(self.partial_text)


def split_claims(answer: str) -> list[Claim]:
    marks: list[tuple[int, str | None]] = []

    def sub(m: re.Match[str]) -> str:
        marks.append((int(m.group(1)), m.group(2)))
        return _MARK.format(len(marks) - 1)

    s = CITATION.sub(sub, answer)
    # a citation after the full stop belongs to the sentence before it
    s = re.sub(r'([.!?]+["”)]*)\s*((?:\x00\d+\x00\s*)*\x00\d+\x00)', r"\2\1", s)
    claims: list[Claim] = []
    for sent in re.split(r"(?<=[.!?])\s+", s):
        ids = [int(i) for i in re.findall(r"\x00(\d+)\x00", sent)]
        text = re.sub(r"\x00\d+\x00", "", sent).strip()
        if not re.search(r"\w", text) or _EXEMPT.match(text):
            continue
        claims.append(Claim(text, [marks[i] for i in ids]))
    return claims


def self_check(answer: str, sources: list[Source], min_quote_chars: int = 6) -> CheckResult:
    if REFUSAL_TEXT.lower() in answer.lower() and not CITATION.search(answer):
        return CheckResult(False, [], [], [], ["model declined to answer"], refusal_like=True)
    by_n = {s.n: s for s in sources}
    claims = split_claims(answer)
    traces: list[CitationTrace] = []
    unsupported: list[str] = []
    problems: list[str] = []
    seen: set[tuple[int, str | None]] = set()
    for c in claims:
        valid = bool(c.cites)
        if not c.cites:
            unsupported.append(c.text)
            problems.append(f"claim without citation: {c.text[:80]!r}")
        for n, quote in c.cites:
            src = by_n.get(n)
            ok = bool(src and quote and len(quote) >= min_quote_chars and quote in src.text)
            if (n, quote) not in seen:
                seen.add((n, quote))
                traces.append(CitationTrace(n=n, verbatim=ok, source_exists=src is not None))
            if not ok:
                valid = False
                why = (
                    "no such source"
                    if src is None
                    else "missing quote"
                    if not quote
                    else "quote too short"
                    if len(quote) < min_quote_chars
                    else "quote is not verbatim in the source"
                )
                problems.append(f"[{n}] {why}: {(quote or '')[:60]!r}")
        c.ok = valid
    if not claims:
        problems.append("no claims with citations")
    good = [c for c in claims if c.ok]
    ok = bool(claims) and len(good) == len(claims)
    return CheckResult(
        ok,
        claims,
        traces,
        unsupported,
        problems,
        partial_text=" ".join(_with_cites(c) for c in good),
    )


def _with_cites(c: Claim) -> str:
    return c.text + " " + " ".join(f'[{n}: "{q}"]' for n, q in c.cites)


def citations_for(
    answer: str, sources: list[Source]
) -> tuple[list[Citation], list[ProvenanceLabel]]:
    by_n = {s.n: s for s in sources}
    cites: list[Citation] = []
    labels: dict[int, ProvenanceLabel] = {}
    seen: set[tuple[int, str]] = set()
    for m in CITATION.finditer(answer):
        n, quote = int(m.group(1)), m.group(2)
        s = by_n.get(n)
        if not s or not quote or (n, quote) in seen:
            continue
        i = s.text.find(quote)
        if i < 0:
            continue
        seen.add((n, quote))
        a = Anchor(
            story=s.story,
            chunk_id=s.chunk_id,
            char_start=s.char_start + i,
            char_end=s.char_start + i + len(quote),
            quote=quote,
        )
        cites.append(Citation(n=n, quote=quote, anchor=a, label=s.label))
        labels.setdefault(
            n,
            ProvenanceLabel(
                n=n,
                label=s.label,
                origin=s.origin,
                confidence=s.confidence,
                rule_id=s.rule_id,
                summary=s.summary,
                explanation=s.explanation,
            ),
        )
    return cites, [labels[k] for k in sorted(labels)]
