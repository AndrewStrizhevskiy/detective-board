"""Rule-first answers: for contradiction / alibi questions the answer is a deterministic template
built from the rule tool's result and its Explanation. No model call, no paraphrase.

Three shapes (docs/symbolic-layer.md, "Rule-first answers"):
  findings  one short sentence per finding (rule, verdict, label, reason) + verbatim quotes
  empty     "no violation among the extracted facts; this does not show consistency" + coverage
  failed    what was missing (tool error, skipped step, ambiguous or unknown person)

Citations use the [n: "quote"] form of the self-check; every quote is copied from an anchor of the
rule result or from a retrieved chunk, so the check passes by construction. Words that assert
consistency appear only as the explicit negation of the empty-result sentence, inside quoted
source text, or as the verdict a rule really returned.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from detective_board.symbolic.api import Explanation, scan_presence_conflicts
from detective_board.symbolic.facts import FactBase, PresenceProp

from .context import Source
from .events import Label, parse_explanation
from .linking import Link
from .window import content_words, sentence_spans

log = logging.getLogger(__name__)

MAX_FINDINGS = 4  # findings written out; the rest is counted
ANCHORS_PER_FINDING = 2
MAX_PASSAGES = 3
QUOTE_CAP = 240
_BAD_QUOTE = re.compile(r'"\s*\]')  # would end a [n: "..."] citation early


@dataclass(frozen=True)
class ToolOutcome:
    """One rule-tool call as the agent saw it (error payloads included)."""

    tool: str
    payload: dict[str, Any]

    @property
    def error(self) -> dict[str, Any] | None:
        e = self.payload.get("error")
        return e if isinstance(e, dict) else None


@dataclass(frozen=True)
class RuleItem:
    """A rule verdict worth reporting: a finding of find_contradictions or a decisive alibi."""

    rule_id: str
    verdict: str
    reason: str
    label: Label
    explanation: Explanation | None
    facts: list[str]
    low_inputs: list[str]
    anchors: list[dict[str, Any]]
    window: str = ""
    curated: int = 0  # facts of the explanation that are human-checked, not extracted


def _plain(text: object) -> str:
    """One line, no brackets (they would read as citations)."""
    return " ".join(str(text).replace("[", "(").replace("]", ")").split())


def _label(prov: object) -> Label:
    return "conditional" if prov == "conditional" else "derived"


def _low_inputs(exp: Explanation | None) -> list[str]:
    if exp is None:
        return []
    weak = set(exp.weak)
    pool = [f for f in exp.depends_on_extracted if f.fact_id in weak or f.confidence == "low"]
    return [_plain(f.summary) for f in pool]


def _item_from_finding(it: dict[str, Any], default: object) -> RuleItem:
    exp = parse_explanation(it.get("explanation"))
    anchors = it.get("anchors") or (exp and [a.model_dump() for a in exp.anchors]) or []
    return RuleItem(
        rule_id=str(it.get("rule") or (exp.rule_id if exp else "rule")),
        verdict=exp.verdict.value if exp else str(it.get("verdict") or "violated"),
        reason=str(it.get("reason_code") or (exp.reason_code if exp else "")),
        label=_label(it.get("provenance", default)),
        explanation=exp,
        facts=[_plain(f.summary) for f in exp.facts[:3]] if exp else [],
        low_inputs=_low_inputs(exp),
        anchors=[a for a in anchors if isinstance(a, dict)],
        window=_plain(exp.subject.get("window", "")) if exp else "",
        curated=sum(1 for f in exp.facts if f.curated) if exp else 0,
    )


def decisive_items(outcomes: Sequence[ToolOutcome]) -> list[RuleItem]:
    """Findings that carry a real verdict. An empty list, an error, or an alibi check that
    came out `unknown` yields nothing here: those are absence of a result."""
    out: list[RuleItem] = []
    for o in outcomes:
        if o.error:
            continue
        p = o.payload
        if o.tool == "find_contradictions":
            out += [
                _item_from_finding(it, p.get("provenance", "derived"))
                for it in (p.get("findings") or [])
                if isinstance(it, dict)
            ]
        elif o.tool == "check_alibi":
            exp = parse_explanation(p.get("explanation"))
            if exp is not None and exp.verdict.value in ("violated", "consistent"):
                out.append(
                    _item_from_finding(
                        {
                            "rule": exp.rule_id,
                            "reason_code": p.get("reason_code") or exp.reason_code,
                            "provenance": p.get("provenance"),
                            "explanation": p["explanation"],
                        },
                        "derived",
                    )
                )
    return out


def has_rule_verdict(outcomes: Sequence[ToolOutcome]) -> bool:
    return bool(decisive_items(outcomes))


# ---------------------------------------------------------------------------- coverage
@dataclass(frozen=True)
class Coverage:
    story: str
    events: int
    claims: int
    exact_times: int
    story_days: int
    presence_props: int
    pairs: int
    undecided: int

    def text(self) -> str:
        if not self.events and not self.claims:
            return "the graph holds no events and no claims for this story."
        return (
            f"the graph holds {self.events} events and {self.claims} claims for this story; "
            f"{self.exact_times} events have an exact clock time, {self.story_days} have a "
            f"story day, and {self.presence_props} claims carry a presence proposition; "
            f"rule R1 examined {self.pairs} event pairs and could not decide "
            f"{self.undecided} of them."
        )


def coverage_of(fb: FactBase) -> Coverage:
    times = [e.time for e in fb.events if e.time is not None]
    stats = scan_presence_conflicts(fb, include_consistent=True, max_findings=1).stats
    return Coverage(
        story=fb.story,
        events=len(fb.events),
        claims=len(fb.claims),
        exact_times=sum(1 for t in times if t.exact and t.lo is not None),
        story_days=sum(1 for t in times if t.day is not None),
        presence_props=sum(1 for c in fb.claims if isinstance(c.prop, PresenceProp)),
        pairs=stats.get("pairs_examined", 0),
        undecided=stats.get("unknown", 0),
    )


def coverage_for(tools: object, graph: object, story: str | None) -> Coverage | None:
    """Coverage of `story` from the fact source the rules read (the in-process client's own, else
    the graph store). None when no source is reachable (e.g. a stdio MCP server): then the answer
    says so instead of guessing."""
    if not story:
        return None
    source = getattr(tools, "source", None)
    if source is None and hasattr(graph, "conn"):
        from detective_board.graph import SqliteFactSource

        source = SqliteFactSource(graph)  # type: ignore[arg-type]
    if source is None:
        return None
    try:
        return coverage_of(source.load(story))
    except Exception as exc:  # noqa: BLE001 - coverage is a courtesy, never a failure
        log.warning("coverage unavailable: %s: %s", type(exc).__name__, exc)
        return None


# ---------------------------------------------------------------------------- the template
@dataclass
class RuleAnswer:
    text: str
    sources: list[Source]
    kind: str  # findings | empty | failed


@dataclass
class _Cites:
    """Numbered sources with verbatim quotes, de-duplicated by position."""

    min_chars: int
    sources: list[Source] = field(default_factory=list)
    _seen: dict[tuple[str, int, int], int] = field(default_factory=dict)

    def quote(self, text: str) -> str | None:
        q = " ".join(text.split())
        if len(q) > QUOTE_CAP:
            q = q[:QUOTE_CAP].rsplit(" ", 1)[0]
        return q if len(q) >= self.min_chars and not _BAD_QUOTE.search(q) else None

    def add(
        self,
        a: Mapping[str, Any],
        label: Label,
        *,
        origin: str = "tool",
        rule_id: str | None = None,
        summary: str = "",
        explanation: Explanation | None = None,
        full_text: str | None = None,
        span: tuple[int, int] | None = None,
    ) -> str | None:
        """The `[n: "quote"]` for an anchor, or None when the quote cannot be cited."""
        q = self.quote(a["quote"])
        if q is None:
            return None
        key = (a["chunk_id"], a["char_start"], a["char_end"])
        n = self._seen.get(key)
        if n is None:
            n = len(self.sources) + 1
            self._seen[key] = n
            text = full_text if full_text is not None else a["quote"]
            self.sources.append(
                Source(
                    n,
                    a["chunk_id"],
                    a["story"],
                    a["char_start"],
                    a["char_end"],
                    text,
                    origin,  # type: ignore[arg-type]
                    label,
                    rule_id=rule_id,
                    summary=summary,
                    explanation=explanation,
                    win_start=span[0] if span else 0,
                    win_end=span[1] if span else None,
                )
            )
        return f'[{n}: "{q}"]'


def _finding_sentence(it: RuleItem, c: _Cites) -> str:
    where = f" for the window {it.window}" if it.window else ""
    head = f"{it.rule_id} reports verdict {it.verdict} ({it.reason}){where}, label {it.label}"
    head += f": {'; '.join(it.facts)}." if it.facts else "."
    cites = [
        s
        for a in it.anchors[:ANCHORS_PER_FINDING]
        if (
            s := c.add(
                a,
                it.label,
                rule_id=it.rule_id,
                summary=f"{it.rule_id} {it.reason}".strip(),
                explanation=it.explanation,
            )
        )
    ]
    line = head + (" " + " ".join(cites) if cites else "")
    if it.label == "conditional":
        why = "; ".join(it.low_inputs) or "see the explanation"
        line += f"\nConditional because these inputs are low-confidence: {why}."
    else:
        line += "\nDerived: none of the extracted facts it depends on is low-confidence."
    if it.curated:
        line += (
            f"\nCurated: {it.curated} of the facts it rests on were entered and checked by the "
            "team (AI-assisted, human re-check pending); they are not output of the automatic "
            "extraction."
        )
    return "- " + line.replace("\n", "\n  ")


def _passages(
    hits: Sequence[Any], question: str, idf: Mapping[str, float] | None, c: _Cites
) -> list[str]:
    q = content_words(question)
    lines: list[str] = []
    for h in hits:
        if len(lines) >= MAX_PASSAGES:
            break
        best: tuple[float, tuple[int, int]] | None = None
        for a, b in sentence_spans(h.text):
            s = sum((idf or {}).get(w, 1.0) for w in q & content_words(h.text[a:b]))
            if s > 0 and (best is None or s > best[0]):
                best = (s, (a, b))
        if best is None:
            continue
        a, b = best[1]
        # the shown excerpt is the chosen sentence; the quote is that sentence (or a prefix)
        cite = c.add(
            {
                "chunk_id": h.chunk_id,
                "story": h.story,
                "char_start": h.char_start,
                "char_end": h.char_end,
                "quote": h.text[a:b],
            },
            "source_text",
            origin="vector",
            summary=f"retrieved chunk (rrf {h.score:.4f})",
            full_text=h.text,
            span=(a, b),
        )
        if cite:
            lines.append(f"- passage from {h.chunk_id} {cite}")
    return lines


def _sentence(text: str) -> str:
    t = _plain(text).rstrip(".")
    return (t[:1].upper() + t[1:] + ".") if t else ""


def _error_reason(o: ToolOutcome) -> str:
    e = o.error or {}
    code, msg = str(e.get("code", "tool_error")), _plain(e.get("message", ""))
    if code in ("skipped", "ambiguous"):
        return f"{o.tool} was not run: {msg}"
    return f"{o.tool} failed ({code})" + (f": {msg}" if msg and msg != "tool call failed" else "")


def build_answer(
    *,
    question: str,
    story: str | None,
    outcomes: Sequence[ToolOutcome],
    link: Link | None,
    notes: Sequence[str],
    hits: Sequence[Any],
    coverage: Coverage | None,
    idf: Mapping[str, float] | None = None,
    min_quote_chars: int = 6,
) -> RuleAnswer:
    c = _Cites(min_quote_chars)
    items = decisive_items(outcomes)
    errors = [o for o in outcomes if o.error]
    ok = [o for o in outcomes if not o.error]
    scope = story or "the retrieved story"
    extra: list[str] = []
    ambiguous = any((o.error or {}).get("code") == "ambiguous" for o in errors)
    if link is not None and link.status == "ambiguous" and (ok or not ambiguous):
        tail = ", so the scan covered the whole story" if ok else ""
        extra.append(_sentence(f"Note: {link.note()}{tail}"))
    elif link is not None and link.status in ("not_found", "no_names") and ok:
        extra.append(_sentence(f"Note: {link.reason}; the scan covered the whole story"))
    for n in notes:
        if str(n).startswith("SCOPE WIDENED: "):
            extra.append(_sentence(str(n).removeprefix("SCOPE WIDENED: ")))
    extra += [_sentence(_error_reason(o)) for o in errors if ok or items]
    for o in ok:
        if o.payload.get("truncated"):
            extra.append(f"{o.tool} truncated its list; more results exist.")

    if items:
        shown = [_finding_sentence(it, c) for it in items[:MAX_FINDINGS]]
        n = len(items)
        head = f"Rule engine result for {scope}: {n} finding{'s' if n != 1 else ''}."
        if n > MAX_FINDINGS:
            head += f" The first {MAX_FINDINGS} are shown."
        return RuleAnswer("\n".join([head, *shown, *extra]), c.sources, "findings")

    if ok:  # the tools ran and returned nothing decisive
        parts = [
            f"The rule engine found no violation among the facts extracted for {scope}. "
            "This does not show that the accounts are consistent: "
            + (coverage.text() if coverage else "coverage figures are not available here.")
        ]
        for o in ok:
            exp = parse_explanation(o.payload.get("explanation"))
            if o.tool == "check_alibi" and exp is not None:
                miss = f" Missing: {', '.join(exp.missing)}." if exp.missing else ""
                parts.append(
                    f"{exp.rule_id} check_alibi returned verdict {exp.verdict.value} "
                    f"({exp.reason_code}).{miss}"
                )
        parts += extra
        lines = _passages(hits, question, idf, c)
        if lines:
            parts.append(
                "Text passages that may be relevant (not rule results):\n" + "\n".join(lines)
            )
        return RuleAnswer("\n".join(parts), c.sources, "empty")

    reasons = [_error_reason(o) for o in errors] or ["the rule engine was not run"]
    text = (
        "The rule engine could not answer this question: "
        + "; ".join(_plain(r) for r in reasons)
        + ". No rule result was produced, so nothing is reported about this question."
    )
    return RuleAnswer("\n".join([text, *extra]) if extra else text, c.sources, "failed")
