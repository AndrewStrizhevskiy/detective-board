"""Answer composer: parse [n: "quote"] citations, map them to anchors, mechanical self-check."""

from __future__ import annotations

import re
from dataclasses import dataclass

from detective_board.extract.ground import normalise

from .context import REFUSAL_TEXT, Source
from .events import Anchor, Citation, CitationTrace, ProvenanceLabel

CITATION = re.compile(r'\[(\d+)(?:\s*:\s*"(.+?)")?\s*\]', re.S)
_EXEMPT = re.compile(r"^\W*(unknown\b|not (stated|found|mentioned|covered)\b)", re.I)
_MARK = "\x00{}\x00"
DEFAULT_MIN_OVERLAP = 0.3  # [P] share of the claim's content words that the cited quotes must hold
_WORD = re.compile(r"[^\W_]{3,}")
_STOP = frozenset(
    "the and for are was were has have had not but with from that this these those its his her "
    "their they them she him you your our out who whom what when where which while into onto "
    "than then there here been being will would could should can may might did does done also "
    "any all one two per via about after before over under upon very more most some such only "
    "because said says say".split()
)
_SUFFIX = ("ing", "ed", "es", "s")


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


def _stem(w: str) -> str:
    for suf in _SUFFIX:
        if w.endswith(suf) and len(w) - len(suf) >= 3:
            return w[: -len(suf)]
    return w


def content_words(text: str) -> set[str]:
    return {_stem(w) for w in _WORD.findall(text.lower()) if w not in _STOP}


def _supported(claim: str, quotes: list[str], min_overlap: float) -> bool:
    """Lexical support: the cited quotes together hold at least `min_overlap` of the claim's
    content words. A claim without content words (only stopwords) has nothing to compare and
    is not rejected here."""
    want = content_words(claim)
    if not want:
        return True
    have: set[str] = set()
    for q in quotes:
        have |= content_words(q)
    hit = want & have
    return bool(hit) and len(hit) / len(want) >= min_overlap


def _norm(s: str) -> str:
    return normalise(s).text.strip()


def self_check(
    answer: str,
    sources: list[Source],
    min_quote_chars: int = 6,
    min_overlap: float = DEFAULT_MIN_OVERLAP,
) -> CheckResult:
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
            nq = _norm(quote) if quote else ""
            ok = bool(src and nq and len(nq) >= min_quote_chars and nq in normalise(src.text).text)
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
                    if len(nq) < min_quote_chars
                    else "quote is not verbatim in the source"
                )
                problems.append(f"[{n}] {why}: {(quote or '')[:60]!r}")
        if valid and c.cites and not _supported(c.text, [q or "" for _, q in c.cites], min_overlap):
            valid = False
            problems.append(f"claim not supported by its quote: {c.text[:80]!r}")
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
        nq = _norm(quote)
        sn = normalise(s.text)
        j = sn.text.find(nq) if nq else -1
        if j < 0:
            continue
        seen.add((n, quote))
        i, end = sn.idx[j], sn.ends[j + len(nq) - 1]
        quote = s.text[i:end]  # the source's own characters
        a = Anchor(
            story=s.story,
            chunk_id=s.chunk_id,
            char_start=s.char_start + i,
            char_end=s.char_start + end,
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
