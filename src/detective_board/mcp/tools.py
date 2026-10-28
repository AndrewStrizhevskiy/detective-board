"""Tool functions of `timeline-alibi`: thin wrappers over detective_board.symbolic.api.

No logic of their own: parse and validate input, load facts through a FactSource, call the
rules, map the result to the JSON of docs/mcp-contracts.md. The agent calls the same API
in-process, so both paths agree.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from detective_board.mcp.errors import ToolError
from detective_board.symbolic import api
from detective_board.symbolic.api import (
    EventRec,
    Explanation,
    FactBase,
    FactSource,
    Finding,
    TimeSpec,
)

SIZE_CAP_BYTES = 64 * 1024


class Window(BaseModel):
    """Contract `Interval`: minutes of the story day."""

    model_config = ConfigDict(extra="forbid")

    story_day: int | None = None
    start_min: int = Field(ge=0, le=1440)
    end_min: int = Field(ge=0, le=1440)

    @model_validator(mode="after")
    def _ordered(self) -> Window:
        if self.start_min > self.end_min:
            raise ValueError("start_min must not exceed end_min")
        return self


def _expl(e: Explanation) -> dict[str, Any]:
    return e.model_dump(mode="json")


def _provenance(conditional: bool) -> str:
    return "conditional" if conditional else "derived"


def _interval(t: TimeSpec | None) -> dict[str, Any] | None:
    if t is None or (t.day is None and t.lo is None and t.hi is None):
        return None
    return {
        "story_day": t.day,
        "start_min": t.lo,
        "end_min": t.hi,
        "time_text": t.time_text,
        "confidence": t.confidence,
    }


def _anchors(e: EventRec) -> list[dict[str, Any]]:
    return [a.model_dump(mode="json") for a in e.anchors]


def _check_id(value: str | None, name: str) -> None:
    if value is not None and not (0 < len(value) <= 200):
        raise ToolError("invalid_input", f"{name} must be 1..200 characters")


def _check_limit(limit: int, hi: int) -> None:
    if not 1 <= limit <= hi:
        raise ToolError("invalid_input", f"limit must be in 1..{hi}")


def _known_person(fb: FactBase, person_id: str) -> None:
    # a person known only through claims (speaks, takes part in no event) is known too
    if not (
        any(person_id in e.participants for e in fb.events)
        or any(c.speaker_id == person_id for c in fb.claims)
    ):
        raise ToolError("not_found", f"unknown person: {person_id!r}")


def _known_place(fb: FactBase, place_id: str) -> None:
    if not any(p.id == place_id for p in fb.places):
        raise ToolError("not_found", f"unknown place: {place_id!r}")


def build_timeline(
    source: FactSource,
    *,
    story: str,
    person_id: str | None = None,
    place_id: str | None = None,
    include_undated: bool = False,
    limit: int = 50,
) -> dict[str, Any]:
    _check_id(story, "story")
    _check_limit(limit, 200)
    fb = source.load(story)
    if person_id is not None:
        _known_person(fb, person_id)
    if place_id is not None:
        _known_place(fb, place_id)
    kw = {"person_id": person_id, "place_id": place_id, "limit": 10**6}
    dated = api.timeline(fb, include_undated=False, **kw)
    everything = api.timeline(fb, include_undated=True, **kw)
    selected = everything if include_undated else dated
    undated_count = len(everything) - len(dated)
    events: list[dict[str, Any]] = []
    for ref in selected[:limit]:
        ev = fb.event(ref.fact_id)
        if ev is None:  # cannot happen: refs come from fb
            continue
        item: dict[str, Any] = {
            "event_id": ev.id,
            "description": ev.description,
            "when": _interval(ev.time),
            "place_id": ev.place_ref,
            "participants": list(ev.participants),
            "anchors": _anchors(ev),
        }
        if ev.curated:  # human-checked fact; the key is absent for extracted events
            item["curated"] = True
        events.append(item)
    return {
        "status": "ok" if events else "insufficient_evidence",
        "events": events,
        "undated_count": undated_count,
        "total_events": len(everything),
        "truncated": len(selected) > limit,
        "provenance": "derived",
        "rule_id": "R2",
    }


def check_alibi(
    source: FactSource,
    *,
    story: str,
    person_id: str,
    window: Window,
    claimed_place_id: str | None = None,
) -> dict[str, Any]:
    _check_id(story, "story")
    _check_id(person_id, "person_id")
    fb = source.load(story)
    _known_person(fb, person_id)
    if claimed_place_id is not None:
        _known_place(fb, claimed_place_id)
    spec = TimeSpec(
        day=window.story_day,
        lo=window.start_min,
        hi=window.end_min,
        exact=True,
        confidence="high",
    )
    f = api.check_presence(fb, person_id=person_id, window=spec, place_id=claimed_place_id)
    return _alibi_result(f)


def _alibi_result(f: Finding) -> dict[str, Any]:
    status = {
        "ALIBI_SUPPORTED": "supported",
        "ALIBI_CONTRADICTED": "contradicted",
        "NO_DATED_EVENTS": "insufficient_evidence",
    }.get(f.reason_code, "unknown")
    kind = {"supported": "places_person_at_claimed"}.get(status, "places_person_elsewhere")
    evidence = []
    for fact in f.explanation.facts:
        if fact.kind == "event":
            evidence.append(
                {
                    "kind": kind,
                    "event_id": fact.fact_id,
                    "summary": fact.summary,
                    "confidence": fact.confidence,
                    "anchors": [a.model_dump(mode="json") for a in fact.anchors],
                }
            )
        elif fact.kind == "claim":
            evidence.append(
                {
                    "kind": "claim_by_other",
                    "event_id": fact.fact_id,
                    "summary": fact.summary,
                    "confidence": fact.confidence,
                    "anchors": [a.model_dump(mode="json") for a in fact.anchors],
                }
            )
    return {
        "status": status,
        "evidence": evidence,
        "notes": list(f.explanation.notes),
        "provenance": _provenance(f.conditional),
        "reason_code": f.reason_code,
        "explanation": _expl(f.explanation),
    }


_OVERLAP_REASONS = {"PLACE_COMPATIBLE", "OVERLAP_DIFFERENT_PLACES"}


def find_overlaps(
    source: FactSource,
    *,
    story: str,
    person_ids: list[str] | None = None,
    same_place_only: bool = True,
    limit: int = 25,
) -> dict[str, Any]:
    _check_id(story, "story")
    _check_limit(limit, 100)
    if person_ids is not None and not 1 <= len(person_ids) <= 10:
        raise ToolError("invalid_input", "person_ids must hold 1..10 ids")
    fb = source.load(story)
    people = person_ids if person_ids is not None else [None]
    for p in person_ids or []:
        _check_id(p, "person_ids[]")
        _known_person(fb, p)
    wanted = {"PLACE_COMPATIBLE"} if same_place_only else _OVERLAP_REASONS
    items: list[Finding] = []
    for p in people:
        rep = api.scan_presence_conflicts(
            fb, person_id=p, include_consistent=True, max_findings=10**6
        )
        items += [x for x in rep.findings if x.reason_code in wanted]
    items.sort(key=lambda x: x.finding_id)
    overlaps = []
    for f in items[:limit]:
        ids = [x.fact_id for x in f.explanation.facts if x.kind == "event"][:2]
        a, b = (fb.event(i) for i in ids)
        overlaps.append(
            {
                "a": ids[0],
                "b": ids[1],
                "overlap": _intersection(a, b),
                "place_id": a.place_ref if a else None,
                "shared_person_ids": [f.explanation.subject.get("person_id", "")],
                "anchors": [x.model_dump(mode="json") for x in f.explanation.anchors],
                "verdict": f.verdict.value,
                "reason_code": f.reason_code,
                "provenance": _provenance(f.conditional),
                "explanation": _expl(f.explanation),
            }
        )
    return {
        "status": "ok" if overlaps else "insufficient_evidence",
        "overlaps": overlaps,
        "truncated": len(items) > limit,
    }


def _intersection(a: EventRec | None, b: EventRec | None) -> dict[str, Any] | None:
    if a is None or b is None or a.time is None or b.time is None:
        return None
    ta, tb = a.time, b.time
    if None in (ta.lo, ta.hi, tb.lo, tb.hi) or ta.day != tb.day:
        return None
    lo, hi = max(ta.lo, tb.lo), min(ta.hi, tb.hi)  # type: ignore[type-var]
    if lo > hi:
        return None
    return {"story_day": ta.day, "start_min": lo, "end_min": hi}


def find_contradictions(
    source: FactSource,
    *,
    story: str,
    person_id: str | None = None,
    rules: list[Literal["R1", "R2", "R3"]] | None = None,
    limit: int = 25,
) -> dict[str, Any]:
    _check_id(story, "story")
    _check_limit(limit, 100)
    chosen = tuple(rules) if rules else ("R1", "R2", "R3")
    fb = source.load(story)
    if person_id is not None:
        _known_person(fb, person_id)
    findings: list[Finding] = []
    for rule in chosen:
        if rule == "R1":
            rep = api.scan_presence_conflicts(fb, person_id=person_id, max_findings=10**6)
        elif rule == "R2":
            rep = api.find_order_cycles(fb)
        else:
            rep = api.scan_claims(fb, speaker_id=person_id)
        findings += [f for f in rep.findings if f.verdict.value == "violated"]
    out = [
        {
            "rule": f.rule_id,
            "finding_id": f.finding_id,
            "reason_code": f.reason_code,
            "provenance": _provenance(f.conditional),
            "explanation": _expl(f.explanation),
            "anchors": [a.model_dump(mode="json") for a in f.explanation.anchors],
        }
        for f in findings[:limit]
    ]
    return {"status": "ok", "findings": out, "truncated": len(findings) > limit}
