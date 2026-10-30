"""Alibi / presence table: a deterministic answer over the `presence_table` tool (no model call).

For the person the question names, one numbered line per place the graph holds for them: when,
where, who says so, the provenance label and a verbatim `[n: "quote"]`; then a verdict section
from rule R1 (the tool runs the same scan as `find_contradictions`). Nothing is invented: a slot
the graph does not hold reads "time not stated" / "place not stated" / "speaker not stated".
docs/symbolic-layer.md 11.5.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from detective_board.extract.curated_schema import CURATED_REVIEW

from .events import parse_explanation
from .linking import Link
from .rule_first import (
    ANCHORS_PER_FINDING,
    RuleAnswer,
    ToolOutcome,
    _chronological,
    _Cites,
    _error_reason,
    _label,
    _low_inputs,
    _plain,
    _sentence,
    _when_text,
)

MAX_CONFLICTS = 3
NO_CONFLICT = (
    "The rules found no violation among these rows; this does not show that the accounts agree."
)


def presence_names(graph: Any, outcomes: Sequence[ToolOutcome]) -> dict[str, str]:
    """Display names for the person and speaker ids in the table (graph lookup, best effort)."""
    ids: set[str] = set()
    for o in outcomes:
        if o.tool == "presence_table" and not o.error:
            ids.add(str(o.payload.get("person_id") or ""))
            ids.update(str(r.get("speaker_id")) for r in o.payload.get("rows") or [] if r)
    out: dict[str, str] = {}
    for i in ids - {"", "None"}:
        try:
            node = graph.get_node(i)
        except Exception:  # a lookup failure must not lose the table
            node = None
        if node is not None and node.name:
            out[i] = node.name
    return out


def _who(row: Mapping[str, Any], names: Mapping[str, str]) -> str:
    sid = row.get("speaker_id")
    who = (
        "the narrator"
        if row.get("narrator")
        else (names.get(str(sid), str(sid)) if sid else "speaker not stated")
    )
    return f"{_plain(who)} denies" if row.get("polarity") == "deny" else _plain(who)


def _label_text(row: Mapping[str, Any]) -> str:
    if row.get("curated"):
        return "curated"
    return f"extracted, {row.get('confidence') or 'unknown'} confidence"


def _row_line(i: int, row: Mapping[str, Any], names: Mapping[str, str], c: _Cites) -> str:
    # slots are text fragments: a trailing full stop would double the line's own
    when = _plain(row.get("time_text") or "").rstrip(" .") or _when_text(row.get("when"))[0]
    when = when or "time not stated"
    place = _plain(row.get("place") or "").rstrip(" .") or "place not stated"
    if row.get("polarity") == "deny":
        place = f"not at {place}"
    cite = None
    for a in [x for x in (row.get("anchors") or []) if isinstance(x, dict)][:ANCHORS_PER_FINDING]:
        cite = c.add(a, "extracted", summary=f"presence row: {place}"[:80])
        if cite:
            break
    return (
        f"{i}. When: {when}. Where: {place}. Who says so: {_who(row, names)}. "
        f"Source: {_label_text(row)} {cite or '(no citable quote)'}"
    )


def _conflict_lines(
    conflicts: Sequence[Mapping[str, Any]], index: Mapping[str, int], total: int
) -> list[str]:
    out: list[str] = []
    for f in conflicts[:MAX_CONFLICTS]:
        ids = list(dict.fromkeys(str(x) for x in f.get("row_ids") or []))
        shown = sorted(index[x] for x in ids if x in index)
        hidden = len(ids) - len(shown)
        parts = [f"row {n}" for n in shown] + ["a row that is not listed"] * min(hidden, 2)
        between = " and ".join(parts) if len(parts) <= 2 else ", ".join(parts)
        label = _label(f.get("provenance"))
        line = (
            f"- Conflict between {between if parts else 'rows that are not listed'}: "
            f"{f.get('rule', 'R1')} verdict violated ({_plain(f.get('reason_code', ''))}), "
            f"label {label}."
        )
        if label == "conditional":
            low = _low_inputs(parse_explanation(f.get("explanation")))
            line += (
                "\n  Conditional because these inputs are low-confidence: "
                f"{'; '.join(low) or 'see the explanation'}."
            )
        else:
            line += "\n  Derived: none of the extracted facts it depends on is low-confidence."
        out.append(line)
    if len(conflicts) > MAX_CONFLICTS:
        out.append(f"- {len(conflicts) - MAX_CONFLICTS} more conflicts are not listed.")
    return out


def build_presence_answer(
    *,
    story: str | None,
    outcomes: Sequence[ToolOutcome],
    link: Link | None,
    names: Mapping[str, str] | None = None,
    min_quote_chars: int = 6,
) -> RuleAnswer:
    names = names or {}
    c = _Cites(min_quote_chars)
    scope = story or "the retrieved story"
    o = next(x for x in outcomes if x.tool == "presence_table")
    if o.error:
        why = (
            link.note()
            if link is not None and link.status in ("not_found", "no_names")
            else _plain(_error_reason(o))
        )
        text = (
            f"No presence table could be built for {scope}: {why}. "
            "No places are reported, so nothing is said about where anyone was."
        )
        return RuleAnswer(text, c.sources, "failed")
    p = o.payload
    pid = str(p.get("person_id") or "")
    person = names.get(pid) or (link.mention if link is not None and link.mention else None)
    who = f"{person} in {scope}" if person else scope
    rows = [r for r in (p.get("rows") or []) if isinstance(r, dict)]
    no_place = int(p.get("events_without_place") or 0)
    if not rows:
        text = (
            f"The graph holds no place for {who} (status "
            f"{_plain(p.get('status', 'insufficient_evidence'))}), so no presence table is "
            "reported. This says what the extraction found, not what the story contains."
        )
        if no_place:
            text += f" {no_place} event(s) of this person have no place."
        return RuleAnswer(text, c.sources, "empty")
    total = int(p.get("total_rows") or len(rows))
    rows = _chronological(rows)  # type: ignore[arg-type]
    head = (
        f"Presence table for {who}: the graph holds {total} place{'s' if total != 1 else ''} "
        f"for this person; {len(rows)} {'is' if len(rows) == 1 else 'are'} shown"
        + (", the rest were cut off." if p.get("truncated") or len(rows) < total else ".")
    )
    lines = [_row_line(i, r, names, c) for i, r in enumerate(rows, 1)]
    index = {str(r.get("row_id")): i for i, r in enumerate(rows, 1)}
    conflicts = [f for f in (p.get("conflicts") or []) if isinstance(f, dict)]
    verdict = ["Verdict (rule R1):"]
    verdict += _conflict_lines(conflicts, index, len(rows)) if conflicts else [NO_CONFLICT]
    tail = [
        "Rows with a stated date and time come first, the others follow in order of narration. "
        '"The narrator" means the text states it as fact; a named speaker means the text '
        "reports what that person says; the table lists what the graph holds, not what the "
        "story contains."
    ]
    if no_place:
        tail.append(f"{no_place} further event(s) of this person have no place and are not listed.")
    curated = sum(1 for r in rows if r.get("curated"))
    if curated:
        tail.append(
            f"Curated: {curated} of the rows were entered and checked by the team "
            f"(prepared with tooling support, {CURATED_REVIEW}); "
            "they are not output of the automatic extraction."
        )
    extra: list[str] = []
    if link is not None and link.status == "ambiguous":
        extra.append(_sentence(f"Note: {link.note()}"))
    return RuleAnswer("\n".join([head, *lines, *verdict, *tail, *extra]), c.sources, "presence")


def surface_forms(graph: Any, person_id: str, link: Link | None) -> list[str]:
    """Name, aliases and the question's own wording of the person: a denial claim is matched on
    its text (it carries no person id)."""
    forms: list[str] = [link.mention] if link is not None and link.mention else []
    try:
        node = graph.get_node(person_id) if graph is not None else None
    except Exception:
        node = None
    if node is not None:
        forms += [node.name or "", *node.aliases]
    return list(dict.fromkeys(f for f in forms if f))
