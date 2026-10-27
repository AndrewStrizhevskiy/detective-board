"""Shared builders for Explanation and Finding objects."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Sequence

from detective_board.extract.curated_schema import CURATED_MARK
from detective_board.symbolic.facts import EventRec
from detective_board.symbolic.model import (
    RULE_VERSIONS,
    Anchor,
    EdgeRef,
    Explanation,
    FactRef,
    Finding,
    Step,
    Verdict,
)
from detective_board.symbolic.time import fmt_span

_RANK = {Verdict.VIOLATED: 0, Verdict.UNKNOWN: 1, Verdict.CONSISTENT: 2}


def anchor_key(a: Anchor) -> tuple[str, int, int, str, str]:
    return (a.story, a.char_start, a.char_end, a.chunk_id, a.quote)


def event_fact(e: EventRec, confidence: str | None = None) -> FactRef:
    conf = confidence or e.eff_confidence
    return FactRef(
        fact_id=e.id,
        kind="event",
        provenance="extracted",
        confidence=conf,  # type: ignore[arg-type]
        summary=f"{e.description} [{fmt_span(e.time)}]" + (f" {CURATED_MARK}" if e.curated else ""),
        anchors=list(e.anchors),
        curated=e.curated,
    )


def make_finding(
    *,
    rule_id: str,
    verdict: Verdict,
    reason_code: str,
    digest: str,
    id_parts: Iterable[str],
    facts: Iterable[FactRef] = (),
    edges: Iterable[EdgeRef] = (),
    steps: Sequence[tuple[str, list[str], str]] = (),
    depends: Iterable[FactRef] = (),
    subject: dict[str, str] | None = None,
    notes: Iterable[str] = (),
    missing: Iterable[str] = (),
    suspects: Iterable[str] = (),
) -> Finding:
    fact_map = {f.fact_id: f for f in facts}
    edge_map = {str(e.edge_id): e for e in edges}
    dep_map = {f.fact_id: f for f in depends if f.provenance == "extracted"}
    fact_list = [fact_map[k] for k in sorted(fact_map)]
    edge_list = [edge_map[k] for k in sorted(edge_map)]
    anchors: dict[tuple, Anchor] = {}
    for item in (*fact_list, *edge_list):
        for a in item.anchors:
            anchors[anchor_key(a)] = a
    dep_list = [dep_map[k] for k in sorted(dep_map)]
    if verdict is Verdict.UNKNOWN:
        weak: list[str] = []
        conditional = False
    else:
        weak = [f.fact_id for f in dep_list if f.confidence == "low"]
        conditional = bool(weak)
    version = RULE_VERSIONS[rule_id]
    expl = Explanation(
        rule_id=rule_id,
        rule_version=version,
        verdict=verdict,
        conditional=conditional,
        reason_code=reason_code,
        facts=fact_list,
        edges=edge_list,
        derivation=[
            Step(step=i, op=op, inputs=inp, output=out) for i, (op, inp, out) in enumerate(steps, 1)
        ],
        anchors=[anchors[k] for k in sorted(anchors)],
        depends_on_extracted=dep_list,
        weak=weak,
        missing=sorted(set(missing)),
        notes=sorted(set(notes)),
        subject=dict(sorted((subject or {}).items())),
        suspects=list(suspects),
    )
    h = hashlib.sha256("|".join(sorted(id_parts)).encode("utf-8")).hexdigest()[:12]
    return Finding(
        finding_id=f"{rule_id}:{h}",
        rule_id=rule_id,
        rule_version=version,
        verdict=verdict,
        conditional=conditional,
        reason_code=reason_code,
        explanation=expl,
        snapshot_digest=digest,
    )


def sort_findings(findings: Iterable[Finding]) -> list[Finding]:
    return sorted(findings, key=lambda f: (f.rule_id, _RANK[f.verdict], f.finding_id))
