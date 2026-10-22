"""R3: a witness claim incompatible with an established fact (spec section 4)."""

from __future__ import annotations

from detective_board.symbolic._explain import event_fact, make_finding, sort_findings
from detective_board.symbolic.facts import ClaimRec, EventRec, FactBase, OrderProp, PresenceProp
from detective_board.symbolic.model import EdgeRef, FactRef, Finding, Report, Verdict
from detective_board.symbolic.places import PlaceIndex, PlaceRel
from detective_board.symbolic.rules.r1_presence import _cmp_text, _edges
from detective_board.symbolic.rules.r2_order import (
    OrderEdge,
    adjacency,
    build_edges,
    find_path,
)
from detective_board.symbolic.time import TimeRel, compare, has_any_time

RULE_ID = "R3"
NOTE_NARRATOR = "unreliable narrators and witnesses are not modelled"


def _claim_fact(c: ClaimRec) -> FactRef:
    return FactRef(
        fact_id=c.id,
        kind="claim",
        provenance="extracted",
        confidence=c.confidence,
        summary=c.content,
        anchors=list(c.anchors),
    )


def _asserts(c: ClaimRec) -> EdgeRef:
    return EdgeRef(
        edge_id=f"ASSERTS:{c.speaker_id}:{c.id}",
        rel="ASSERTS",
        src=c.speaker_id,
        dst=c.id,
        anchors=list(c.anchors),
    )


def _established(e: EventRec) -> bool:
    return e.narrator and e.presence_confidence == "high"


def _presence(fb: FactBase, c: ClaimRec, p: PresenceProp, digest: str) -> Finding:
    idx = PlaceIndex(fb.places)
    contra: list[EventRec] = []
    support: list[EventRec] = []
    claim_sourced = 0
    steps: list[tuple[str, list[str], str]] = []
    for e in fb.events:
        if p.person_id not in e.participants or e.place_ref is None or not has_any_time(e.time):
            continue
        cmp = compare(p.time, e.time)
        if cmp.rel is not TimeRel.OVERLAP:
            continue
        prel = idx.rel(p.place_ref, e.place_ref)
        if prel is PlaceRel.UNKNOWN:
            continue
        if not e.narrator:
            claim_sourced += prel is PlaceRel.DISTINCT
            continue
        steps.append(("interval_compare", [c.id, e.id], _cmp_text(cmp)))
        steps.append(("place_rel", [idx.label(p.place_ref), idx.label(e.place_ref)], prel.value))
        (contra if prel is PlaceRel.DISTINCT else support).append(e)
    for other in fb.claims:
        op = other.prop
        if other.id == c.id or not isinstance(op, PresenceProp) or op.person_id != p.person_id:
            continue
        if (
            compare(p.time, op.time).rel is TimeRel.OVERLAP
            and idx.rel(p.place_ref, op.place_ref) is PlaceRel.DISTINCT
        ):
            claim_sourced += 1
    used = [*contra, *support]
    if contra:
        verdict = Verdict.VIOLATED
        reason = (
            "CLAIM_INCOMPATIBLE_WITH_FACT"
            if any(_established(e) for e in contra)
            else "CLAIM_VS_EXTRACTED_EVENT"
        )
    elif support:
        verdict, reason = Verdict.CONSISTENT, "CLAIM_CORROBORATED"
    elif claim_sourced:
        verdict, reason = Verdict.UNKNOWN, "CLAIM_VS_CLAIM"
    else:
        verdict, reason = Verdict.UNKNOWN, "NO_DECISIVE_EVIDENCE"
    facts = [_claim_fact(c), *(event_fact(e, e.presence_confidence) for e in used)]
    return make_finding(
        rule_id=RULE_ID,
        verdict=verdict,
        reason_code=reason,
        digest=digest,
        id_parts=[c.id, *(e.id for e in used)],
        facts=facts,
        edges=[_asserts(c), *(x for e in used for x in _edges(p.person_id, e, idx))],
        steps=steps if used else [],
        depends=facts,
        subject={"claim_id": c.id, "person_id": p.person_id, "speaker_id": c.speaker_id},
        notes=[NOTE_NARRATOR],
        missing=["definite_overlapping_presence"] if verdict is Verdict.UNKNOWN else [],
    )


def _closure_path(edges: list[OrderEdge], a: str, b: str) -> tuple[list[OrderEdge] | None, bool]:
    """Path a<b over established edges first, then over any narrator-voice edge (weak)."""
    p = find_path(adjacency([e for e in edges if e.established]), a, b)
    if p is not None:
        return p, True
    return find_path(adjacency([e for e in edges if e.narrator]), a, b), False


def _order(fb: FactBase, c: ClaimRec, p: OrderProp, digest: str) -> Finding:
    edges, _ = build_edges(fb)
    a, b = p.before_event_id, p.after_event_id
    contra, _ = _closure_path(edges, b, a)
    support, _ = _closure_path(edges, a, b)
    if contra:
        verdict, reason = Verdict.VIOLATED, "CLAIM_INCOMPATIBLE_WITH_FACT"
    elif support:
        verdict, reason = Verdict.CONSISTENT, "CLAIM_CORROBORATED"
    else:
        verdict, reason = Verdict.UNKNOWN, "NO_DECISIVE_EVIDENCE"
    used_edges = [*(contra or []), *(support or [])]
    evs = {x for ed in used_edges for x in (ed.src, ed.dst)}
    facts = [_claim_fact(c), *(event_fact(e) for e in fb.events if e.id in evs)]
    deps = [_claim_fact(c)]
    for ed in used_edges:
        if ed.provenance == "extracted":
            deps.append(
                FactRef(
                    fact_id=ed.edge_id,
                    kind="order",
                    provenance="extracted",
                    confidence=ed.confidence,
                    summary=f"{ed.src} before {ed.dst}",
                    anchors=list(ed.anchors),
                )
            )
        else:
            deps.extend(event_fact(e) for e in fb.events if e.id in ed.events)
    return make_finding(
        rule_id=RULE_ID,
        verdict=verdict,
        reason_code=reason,
        digest=digest,
        id_parts=[c.id, *(ed.edge_id for ed in used_edges)],
        facts=facts,
        edges=[_asserts(c), *(ed.ref() for ed in used_edges)],
        steps=[
            ("order_edge", list(ed.events), f"{ed.src} < {ed.dst} ({ed.edge_id})")
            for ed in used_edges
        ],
        depends=deps,
        subject={"claim_id": c.id, "speaker_id": c.speaker_id},
        notes=[NOTE_NARRATOR],
        missing=[f"order_path:{a}->{b}"] if verdict is Verdict.UNKNOWN else [],
    )


def check_claim(fb: FactBase, claim_id: str) -> Finding:
    digest = fb.digest()
    c = fb.claim(claim_id)
    if c is None:
        return make_finding(
            rule_id=RULE_ID,
            verdict=Verdict.UNKNOWN,
            reason_code="UNKNOWN_CLAIM",
            digest=digest,
            id_parts=[claim_id],
            subject={"claim_id": claim_id},
            missing=[f"claim:{claim_id}"],
        )
    if c.prop is None:
        return make_finding(
            rule_id=RULE_ID,
            verdict=Verdict.UNKNOWN,
            reason_code="UNSTRUCTURED_CLAIM",
            digest=digest,
            id_parts=[c.id],
            facts=[_claim_fact(c)],
            edges=[_asserts(c)],
            subject={"claim_id": c.id, "speaker_id": c.speaker_id},
            missing=["structured_proposition"],
            notes=[NOTE_NARRATOR],
        )
    if isinstance(c.prop, PresenceProp):
        return _presence(fb, c, c.prop, digest)
    return _order(fb, c, c.prop, digest)


def scan_claims(fb: FactBase, *, speaker_id: str | None = None) -> Report:
    digest = fb.digest()
    findings = [
        check_claim(fb, c.id) for c in fb.claims if speaker_id is None or c.speaker_id == speaker_id
    ]
    stats = {"claims_examined": len(findings), "consistent": 0, "unknown": 0, "violated": 0}
    for f in findings:
        stats[f.verdict.value] += 1
    return Report(
        rule_id=RULE_ID,
        findings=sort_findings(findings),
        stats=dict(sorted(stats.items())),
        snapshot_digest=digest,
    )
