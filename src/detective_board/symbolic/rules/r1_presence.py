"""R1: one person cannot be at two different places at the same time (spec section 4)."""

from __future__ import annotations

from detective_board.symbolic._explain import event_fact, make_finding, sort_findings
from detective_board.symbolic.facts import EventRec, FactBase
from detective_board.symbolic.model import EdgeRef, Finding, Report, TimeSpec, Verdict
from detective_board.symbolic.places import PlaceIndex, PlaceRel
from detective_board.symbolic.time import (
    TimeCmp,
    TimeRel,
    abs_bounds,
    compare,
    fmt_abs,
    fmt_span,
    has_any_time,
)

RULE_ID = "R1"
NOTE_TRAVEL = "travel time between places is not modelled"


def _edges(person: str, e: EventRec, idx: PlaceIndex) -> list[EdgeRef]:
    out = [
        EdgeRef(
            edge_id=f"PARTICIPATED_IN:{person}:{e.id}",
            rel="PARTICIPATED_IN",
            src=person,
            dst=e.id,
            anchors=list(e.anchors),
        )
    ]
    if e.place_ref is not None:
        place = idx.label(e.place_ref)
        out.append(
            EdgeRef(
                edge_id=f"OCCURRED_AT:{e.id}:{place}",
                rel="OCCURRED_AT",
                src=e.id,
                dst=place,
                anchors=list(e.anchors),
            )
        )
    return out


def _cmp_text(c: TimeCmp) -> str:
    if c.rel is TimeRel.OVERLAP and c.intersection is not None:
        lo, hi = c.intersection
        return f"overlap [{fmt_abs(lo)},{fmt_abs(hi)})" if lo < hi else f"overlap at {fmt_abs(lo)}"
    return c.rel.value.lower() + (" (possible_overlap)" if c.possible_overlap else "")


def _eligible(fb: FactBase, person: str) -> tuple[list[EventRec], int, int]:
    """Examinable events of `person`, plus the skipped_no_place / skipped_no_time counts."""
    ok: list[EventRec] = []
    no_place = no_time = 0
    for e in fb.events:
        if person not in e.participants:
            continue
        if e.place_ref is None:
            no_place += 1
        elif not has_any_time(e.time):
            no_time += 1
        else:
            ok.append(e)
    return ok, no_place, no_time


def _pair(person: str, e1: EventRec, e2: EventRec, idx: PlaceIndex, digest: str) -> Finding:
    c = compare(e1.time, e2.time)
    prel = idx.rel(e1.place_ref, e2.place_ref)
    notes = [NOTE_TRAVEL]
    missing: list[str] = []
    if c.rel is TimeRel.DISJOINT:
        verdict, reason = Verdict.CONSISTENT, "TIME_DISJOINT"
    elif prel in (PlaceRel.SAME, PlaceRel.CONTAINS):
        verdict, reason = Verdict.CONSISTENT, "PLACE_COMPATIBLE"
    elif c.rel is TimeRel.OVERLAP:
        if prel is PlaceRel.DISTINCT:
            verdict, reason = Verdict.VIOLATED, "OVERLAP_DIFFERENT_PLACES"
        else:
            verdict, reason = Verdict.UNKNOWN, "PLACE_UNRESOLVED"
            missing += [
                f"resolved_place:{e.id}" for e in (e1, e2) if idx.resolve(e.place_ref) is None
            ]
    else:
        verdict, reason = Verdict.UNKNOWN, "TIME_UNDECIDED"
        missing += [
            f"exact_time:{e.id}"
            for e in (e1, e2)
            if abs_bounds(e.time) is None or e.time is None or not e.time.exact
        ]
        if c.possible_overlap and prel is PlaceRel.DISTINCT:
            notes.append("possible_overlap")
    steps = [
        ("interval_compare", [e1.id, e2.id], _cmp_text(c)),
        ("place_rel", [idx.label(e1.place_ref), idx.label(e2.place_ref)], prel.value),
    ]
    return make_finding(
        rule_id=RULE_ID,
        verdict=verdict,
        reason_code=reason,
        digest=digest,
        id_parts=[person, e1.id, e2.id],
        facts=[event_fact(e1, e1.presence_confidence), event_fact(e2, e2.presence_confidence)],
        edges=[*_edges(person, e1, idx), *_edges(person, e2, idx)],
        steps=steps,
        depends=[event_fact(e1, e1.presence_confidence), event_fact(e2, e2.presence_confidence)],
        subject={"person_id": person},
        notes=notes,
        missing=missing,
    )


def scan_presence_conflicts(
    fb: FactBase,
    *,
    person_id: str | None = None,
    include_consistent: bool = False,
    max_findings: int = 100,
) -> Report:
    digest = fb.digest()
    idx = PlaceIndex(fb.places)
    people = sorted({p for e in fb.events for p in e.participants})
    if person_id is not None:
        people = [p for p in people if p == person_id]
    stats = {
        "pairs_examined": 0,
        "violated": 0,
        "unknown": 0,
        "consistent": 0,
        "skipped_no_place": 0,
        "skipped_no_time": 0,
        "skipped_same_occurrence": 0,
    }
    findings: list[Finding] = []
    for person in people:
        evs, no_place, no_time = _eligible(fb, person)
        stats["skipped_no_place"] += no_place
        stats["skipped_no_time"] += no_time
        for i, e1 in enumerate(evs):
            for e2 in evs[i + 1 :]:
                if e1.occurrence_id is not None and e1.occurrence_id == e2.occurrence_id:
                    stats["skipped_same_occurrence"] += 1
                    continue
                f = _pair(person, e1, e2, idx, digest)
                stats["pairs_examined"] += 1
                stats[f.verdict.value] += 1
                keep = (
                    include_consistent
                    or f.verdict is Verdict.VIOLATED
                    or "possible_overlap" in f.explanation.notes
                )
                if keep:
                    findings.append(f)
    return Report(
        rule_id=RULE_ID,
        findings=sort_findings(findings)[:max_findings],
        stats=dict(sorted(stats.items())),
        snapshot_digest=digest,
    )


def check_presence(
    fb: FactBase, *, person_id: str, window: TimeSpec, place_id: str | None = None
) -> Finding:
    digest = fb.digest()
    idx = PlaceIndex(fb.places)
    subject = {"person_id": person_id, "window": fmt_span(window)}
    id_parts = [person_id, fmt_span(window), place_id or "?"]
    claimed = idx.resolve(place_id)
    if claimed is None:
        return make_finding(
            rule_id=RULE_ID,
            verdict=Verdict.UNKNOWN,
            reason_code="PLACE_UNRESOLVED",
            digest=digest,
            id_parts=id_parts,
            subject={**subject, "place_id": place_id or ""},
            missing=["resolved_place:query"],
            notes=[NOTE_TRAVEL],
        )
    subject["place_id"] = claimed
    evs, _, _ = _eligible(fb, person_id)
    contra: list[EventRec] = []
    support: list[EventRec] = []
    unresolved: list[EventRec] = []
    for e in evs:
        if compare(window, e.time).rel is not TimeRel.OVERLAP:
            continue
        prel = idx.rel(claimed, e.place_ref)
        if prel is PlaceRel.DISTINCT:
            contra.append(e)
        elif prel is PlaceRel.UNKNOWN:
            unresolved.append(e)
        else:
            support.append(e)
    used = [*contra, *support]
    if contra:
        verdict, reason = Verdict.VIOLATED, "ALIBI_CONTRADICTED"
    elif support:
        verdict, reason = Verdict.CONSISTENT, "ALIBI_SUPPORTED"
    else:
        verdict = Verdict.UNKNOWN
        reason = "NO_DECISIVE_EVIDENCE" if evs else "NO_DATED_EVENTS"
        used = unresolved
    steps = [("window", [fmt_span(window)], f"place {claimed}")]
    for e in used:
        steps.append(("interval_compare", [e.id], _cmp_text(compare(window, e.time))))
        steps.append(
            ("place_rel", [claimed, idx.label(e.place_ref)], idx.rel(claimed, e.place_ref).value)
        )
    return make_finding(
        rule_id=RULE_ID,
        verdict=verdict,
        reason_code=reason,
        digest=digest,
        id_parts=[*id_parts, *(e.id for e in used)],
        facts=[event_fact(e, e.presence_confidence) for e in used],
        edges=[x for e in used for x in _edges(person_id, e, idx)],
        steps=steps,
        depends=[event_fact(e, e.presence_confidence) for e in used],
        subject=subject,
        notes=[NOTE_TRAVEL],
        missing=[f"resolved_place:{e.id}" for e in unresolved]
        + (["definite_overlap_with_dated_event"] if verdict is Verdict.UNKNOWN else []),
    )
