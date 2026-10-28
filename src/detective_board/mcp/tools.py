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
    ClaimRec,
    EventRec,
    Explanation,
    FactBase,
    FactSource,
    Finding,
    TimeSpec,
)
from detective_board.symbolic.places import PlaceIndex, PlaceRel
from detective_board.symbolic.time import abs_bounds

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


PRESENCE_LIMIT = 12
_DENIAL_INFIX = " was not at "


def _claim_key(a: Any) -> tuple[str, int, int]:
    return (a.chunk_id, a.char_start, a.char_end)


def _speaker_of(ev: EventRec, claims: list[ClaimRec]) -> str | None:
    """Speaker of a reported event: the claim written from the same quote about the same fact
    (the ingesters give the claim `"X was at P, T"` for the event `"X at P, T"`). None when no
    claim matches exactly: the speaker is then not stated, never guessed."""
    keys = {_claim_key(a) for a in ev.anchors}
    want = ev.description.casefold()
    for c in claims:
        if c.prop is None and _DENIAL_INFIX in c.content:
            continue
        if keys & {_claim_key(a) for a in c.anchors}:
            if c.content.replace(" was at ", " at ", 1).casefold() == want:
                return c.speaker_id
    return None


def presence_table(
    source: FactSource,
    *,
    story: str,
    person_id: str,
    names: list[str] | None = None,
    limit: int = PRESENCE_LIMIT,
) -> dict[str, Any]:
    """Every place the graph holds for one person (events with a place, and denials), with who
    says so and the quote anchor, plus the R1 conflicts of the same person. Read-only; no rule
    verdict of its own: `conflicts` are the violated findings of `find_contradictions` R1.

    `names` are the surface forms of the person (name, aliases): a denial claim carries no person
    id, only the text `"<name> was not at <place>, <time>"`, so it is matched on these."""
    _check_id(story, "story")
    _check_id(person_id, "person_id")
    _check_limit(limit, 100)
    fb = source.load(story)
    _known_person(fb, person_id)
    place_name = {p.id: p.name for p in fb.places}
    claims = list(fb.claims)
    rows: list[dict[str, Any]] = []
    no_place = 0
    for ev in fb.events:
        if person_id not in ev.participants:
            continue
        if not ev.place_ref:
            no_place += 1
            continue
        speaker = None if ev.narrator else _speaker_of(ev, claims)
        row: dict[str, Any] = {
            "row_id": ev.id,
            "kind": "event",
            "polarity": "affirm",
            "place_id": ev.place_ref if ev.place_ref in place_name else None,
            "place": place_name.get(ev.place_ref, ev.place_ref),
            "when": _interval(ev.time),
            "time_text": ev.time.time_text if ev.time else None,
            "narrator": ev.narrator,
            "speaker_id": speaker,
            "confidence": ev.eff_confidence,
            "anchors": _anchors(ev),
        }
        if ev.curated:
            row["curated"] = True
        rows.append(row)
    wanted = [n.casefold() + _DENIAL_INFIX for n in (names or []) if n.strip()]
    for c in claims:
        low = c.content.casefold()
        hit = next((w for w in wanted if low.startswith(w)), None)
        if hit is None:
            continue
        where, _, when_text = c.content[len(hit) :].partition(", ")
        if not where.strip():
            continue
        row = {
            "row_id": c.id,
            "kind": "claim",
            "polarity": "deny",
            "place_id": None,
            "place": where.strip(),
            "when": None,
            "time_text": when_text.strip() or None,
            "narrator": False,
            "speaker_id": c.speaker_id,
            "confidence": c.confidence,
            "anchors": [a.model_dump(mode="json") for a in c.anchors],
        }
        if c.curated:
            row["curated"] = True
        rows.append(row)
    rows.sort(
        key=lambda r: (r["anchors"][0]["char_start"] if r["anchors"] else 10**12, r["row_id"])
    )
    rep = api.scan_presence_conflicts(fb, person_id=person_id, max_findings=10**6)
    conflicts = [
        {
            "rule": f.rule_id,
            "finding_id": f.finding_id,
            "reason_code": f.reason_code,
            "provenance": _provenance(f.conditional),
            "row_ids": [x.fact_id for x in f.explanation.facts if x.kind == "event"],
            "explanation": _expl(f.explanation),
        }
        for f in rep.findings
        if f.verdict.value == "violated"
    ]
    in_conflict = {i for c in conflicts for i in c["row_ids"]}
    keep = {r["row_id"] for r in rows if r["row_id"] in in_conflict}
    for r in rows:  # rows of a conflict are kept first, the rest in narration order
        if len(keep) >= limit:
            break
        keep.add(r["row_id"])
    shown = [r for r in rows if r["row_id"] in keep]
    return {
        "status": "ok" if rows else "insufficient_evidence",
        "person_id": person_id,
        "rows": shown,
        "total_rows": len(rows),
        "events_without_place": no_place,
        "truncated": len(shown) < len(rows),
        "conflicts": conflicts,
        "provenance": "derived",
        "rule_id": "R1",
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
    return _alibi_on(fb, person_id, window, claimed_place_id)


def _alibi_on(
    fb: FactBase, person_id: str, window: Window, claimed_place_id: str | None
) -> dict[str, Any]:
    """The body of `check_alibi` over an already loaded FactBase (shared with `scene_board`)."""
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


SCENE_LIMIT = 10
_BOARD_STATUS = {
    "contradicted": "excluded",
    "supported": "placed",
    "unknown": "not_excluded",
    "insufficient_evidence": "not_excluded",
}


def _scene_evidence(
    fb: FactBase, idx: PlaceIndex, scene_place: str, check: dict[str, Any]
) -> list[dict[str, Any]]:
    """The evidence of a `check_alibi` result, each item with where it puts the person relative to
    the scene (`at_scene`), who says so and whether the fact is human-checked."""
    out: list[dict[str, Any]] = []
    names = {p.id: p.name for p in fb.places}
    for item in check["evidence"]:
        entry = dict(item)
        ev = fb.event(item["event_id"])
        if ev is not None:
            pid = idx.resolve(ev.place_ref)
            entry["place_id"] = pid
            entry["place"] = names.get(pid or "", ev.place_ref)
            entry["at_scene"] = idx.rel(scene_place, ev.place_ref) in (
                PlaceRel.SAME,
                PlaceRel.CONTAINS,
            )
            entry["kind"] = (
                "places_person_at_claimed" if entry["at_scene"] else ("places_person_elsewhere")
            )
            entry["narrator"] = ev.narrator
            entry["speaker_id"] = None if ev.narrator else _speaker_of(ev, list(fb.claims))
            entry["time_text"] = ev.time.time_text if ev.time else None
            if ev.curated:
                entry["curated"] = True
        out.append(entry)
    return out


def _board_entry(
    fb: FactBase, idx: PlaceIndex, place_id: str, window: Window, person: str
) -> dict[str, Any]:
    placed = [e for e in fb.events if person in e.participants and e.place_ref]
    check = _alibi_on(fb, person, window, place_id)
    status = _BOARD_STATUS[check["status"]]
    entry: dict[str, Any] = {
        "person_id": person,
        "status": status,
        "alibi_status": check["status"],
        "reason_code": check["reason_code"],
        "provenance": check["provenance"],
        "placed_events": len(placed),
        "events_without_day": sum(1 for e in placed if abs_bounds(e.time) is None),
        "evidence": [],
        "notes": check["notes"],
    }
    if status != "not_excluded":
        entry["evidence"] = _scene_evidence(fb, idx, place_id, check)
        entry["explanation"] = check["explanation"]
        entry["also_at_scene"] = status == "excluded" and any(
            x.get("at_scene") for x in entry["evidence"]
        )
    return entry


def scene_board(
    source: FactSource,
    *,
    story: str,
    place: str,
    window: Window,
    person_ids: list[str] | None = None,
    victim_ids: list[str] | None = None,
    limit: int = SCENE_LIMIT,
) -> dict[str, Any]:
    """Alibi-exclusion board for a crime scene: for every person the graph holds for the story
    (or only `person_ids`), `check_alibi` against the scene's place and time window. A person the
    text places elsewhere at that time is `excluded` (testimony, not proof); one it places at the
    scene is `placed`; the rest are `not_excluded` (no usable event at that time; never
    "suspected"). No rule of its own, no verdict about guilt. The `victim_ids` are not part of the
    board; they are checked the same way and returned apart as `victims`. `place` is a place id,
    name or alias.

    The window needs a story day to be comparable: an event without a day or a clock time cannot
    place or exclude anyone (the rules never assume a day), it is only counted
    (`events_without_day`)."""
    _check_id(story, "story")
    _check_id(place, "place")
    _check_limit(limit, 50)
    if person_ids is not None and len(person_ids) > 300:
        raise ToolError("invalid_input", "person_ids must hold at most 300 ids")
    fb = source.load(story)
    idx = PlaceIndex(fb.places)
    place_id = idx.resolve(place)
    if place_id is None:
        raise ToolError("not_found", f"unknown place: {place!r}")
    universe = {p for e in fb.events for p in e.participants} | {c.speaker_id for c in fb.claims}
    victims = set(victim_ids or [])
    pool = universe if person_ids is None else universe & set(person_ids)
    entries = [_board_entry(fb, idx, place_id, window, p) for p in sorted(pool - victims)]
    rank = {"excluded": 0, "placed": 1, "not_excluded": 2}
    entries.sort(key=lambda x: (rank[x["status"]], -x["placed_events"], x["person_id"]))
    counts = {k: sum(1 for x in entries if x["status"] == k) for k in rank}
    shown = entries[:limit]
    victim_entries = [
        _board_entry(fb, idx, place_id, window, v) for v in sorted(victims & universe)
    ]
    decisive = [x for x in shown if x["status"] != "not_excluded"]
    return {
        "status": "ok" if entries else "insufficient_evidence",
        "story": story,
        "place_id": place_id,
        "place": next((p.name for p in fb.places if p.id == place_id), place_id),
        "window": window.model_dump(),
        "persons": shown,
        "total_persons": len(entries),
        "counts": counts,
        "victims": victim_entries,
        "truncated": len(shown) < len(entries),
        "provenance": (
            "conditional" if any(x["provenance"] == "conditional" for x in decisive) else "derived"
        ),
        "rule_id": "R1",
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
