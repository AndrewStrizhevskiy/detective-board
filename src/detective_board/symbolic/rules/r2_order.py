"""R2: BEFORE is transitive and acyclic (spec section 4)."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from detective_board.symbolic._explain import event_fact, make_finding, sort_findings
from detective_board.symbolic.facts import EventRec, FactBase
from detective_board.symbolic.model import (
    Anchor,
    Confidence,
    EdgeRef,
    FactRef,
    Finding,
    Report,
    Verdict,
)
from detective_board.symbolic.time import fmt_span, strictly_before

RULE_ID = "R2"


@dataclass(frozen=True)
class OrderEdge:
    """BEFORE(src, dst): src ends before dst starts."""

    edge_id: str
    src: str
    dst: str
    provenance: str  # "extracted" (time_norm.rel) or "derived" (rule R2.time)
    confidence: Confidence
    narrator: bool
    anchors: tuple[Anchor, ...]
    events: tuple[str, ...]  # events whose time facts the edge rests on

    def ref(self) -> EdgeRef:
        return EdgeRef(
            edge_id=self.edge_id,
            rel="BEFORE",
            src=self.src,
            dst=self.dst,
            anchors=list(self.anchors),
        )

    @property
    def established(self) -> bool:
        return self.narrator and self.confidence == "high"


def _union(*lists: list[Anchor]) -> tuple[Anchor, ...]:
    seen = {
        (a.story, a.char_start, a.char_end, a.chunk_id, a.quote): a for lst in lists for a in lst
    }
    return tuple(seen[k] for k in sorted(seen))


def build_edges(fb: FactBase) -> tuple[list[OrderEdge], list[str]]:
    """All order edges sorted by edge id, plus the ids of unresolvable relative references."""
    edges: list[OrderEdge] = []
    unresolved: list[str] = []
    for e in fb.events:
        t = e.time
        if t is None or t.rel not in ("before", "after") or t.ref_event_id is None:
            continue
        ref = fb.event(t.ref_event_id)
        if ref is None:
            unresolved.append(e.id)
            continue
        src, dst = (ref.id, e.id) if t.rel == "after" else (e.id, ref.id)
        edges.append(
            OrderEdge(
                edge_id=f"ord:{src}>{dst}:rel",
                src=src,
                dst=dst,
                provenance="extracted",
                confidence=e.eff_confidence,
                narrator=e.narrator and ref.narrator,
                anchors=_union(e.anchors),
                events=(e.id,),
            )
        )
    for a in fb.events:
        for b in fb.events:
            if a.id != b.id and strictly_before(a.time, b.time):
                edges.append(
                    OrderEdge(
                        edge_id=f"ord:{a.id}>{b.id}:time",
                        src=a.id,
                        dst=b.id,
                        provenance="derived",
                        confidence="low"
                        if "low" in (a.eff_confidence, b.eff_confidence)
                        else "high",
                        narrator=a.narrator and b.narrator,
                        anchors=_union(a.anchors, b.anchors),
                        events=(a.id, b.id),
                    )
                )
    return sorted(edges, key=lambda x: x.edge_id), sorted(unresolved)


def adjacency(edges: list[OrderEdge]) -> dict[str, list[OrderEdge]]:
    adj: dict[str, list[OrderEdge]] = {}
    for ed in sorted(edges, key=lambda x: (x.src, x.dst, x.edge_id)):
        adj.setdefault(ed.src, []).append(ed)
    return adj


def find_path(
    adj: dict[str, list[OrderEdge]], start: str, goal: str, allowed: set[str] | None = None
) -> list[OrderEdge] | None:
    """Shortest path of >= 1 edges (BFS; neighbours in (dst, edge id) order)."""
    queue: deque[tuple[str, list[OrderEdge]]] = deque([(start, [])])
    seen: set[str] = set()
    while queue:
        node, path = queue.popleft()
        for ed in adj.get(node, ()):
            if allowed is not None and ed.dst not in allowed:
                continue
            if ed.dst == goal:
                return [*path, ed]
            if ed.dst not in seen:
                seen.add(ed.dst)
                queue.append((ed.dst, [*path, ed]))
    return None


def sccs(nodes: list[str], adj: dict[str, list[OrderEdge]]) -> list[list[str]]:
    """Tarjan, iterative; components and their members come out sorted."""
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    on: set[str] = set()
    stack: list[str] = []
    out: list[list[str]] = []
    counter = 0
    for root in nodes:
        if root in index:
            continue
        work: list[tuple[str, int]] = [(root, 0)]
        while work:
            v, i = work.pop()
            if i == 0:
                index[v] = low[v] = counter
                counter += 1
                stack.append(v)
                on.add(v)
            nbrs = adj.get(v, [])
            descended = False
            while i < len(nbrs):
                w = nbrs[i].dst
                i += 1
                if w not in index:
                    work.append((v, i))
                    work.append((w, 0))
                    descended = True
                    break
                if w in on:
                    low[v] = min(low[v], index[w])
            if descended:
                continue
            if low[v] == index[v]:
                comp: list[str] = []
                while True:
                    w = stack.pop()
                    on.discard(w)
                    comp.append(w)
                    if w == v:
                        break
                out.append(sorted(comp))
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[v])
    return sorted(out)


def _edge_dependencies(path: list[OrderEdge], fb: FactBase) -> list[FactRef]:
    deps: list[FactRef] = []
    for ed in path:
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
            deps.extend(event_fact(x) for x in (fb.event(i) for i in ed.events) if x is not None)
    return deps


def _path_finding(
    fb: FactBase,
    verdict: Verdict,
    reason: str,
    path: list[OrderEdge],
    digest: str,
    *,
    id_parts: list[str],
    subject: dict[str, str],
    notes: list[str] | None = None,
    missing: list[str] | None = None,
    suspects: list[str] | None = None,
) -> Finding:
    evs: list[EventRec] = []
    for ed in path:
        for eid in (ed.src, ed.dst):
            ev = fb.event(eid)
            if ev is not None:
                evs.append(ev)
    steps = [("order_edge", [*ed.events], f"{ed.src} < {ed.dst} ({ed.edge_id})") for ed in path]
    return make_finding(
        rule_id=RULE_ID,
        verdict=verdict,
        reason_code=reason,
        digest=digest,
        id_parts=[*id_parts, *(ed.edge_id for ed in path)],
        facts=[event_fact(e) for e in evs],
        edges=[ed.ref() for ed in path],
        steps=steps,
        depends=_edge_dependencies(path, fb),
        subject=subject,
        notes=notes or [],
        missing=missing or [],
        suspects=suspects or [],
    )


def _cycle_finding(fb: FactBase, comp: list[str], adj: dict, digest: str) -> Finding:
    start = comp[0]
    cycle = find_path(adj, start, start, set(comp)) or []
    rel_edges = [ed for ed in cycle if ed.provenance == "extracted"]
    suspects = [
        ed.edge_id for ed in sorted(rel_edges, key=lambda x: (x.confidence != "low", x.edge_id))
    ]
    return _path_finding(
        fb,
        Verdict.VIOLATED,
        "ORDER_CYCLE",
        cycle,
        digest,
        id_parts=["cycle", *comp],
        subject={"events": ",".join(comp)},
        notes=[
            "a minimal cycle is an indication; the layer does not decide which edge is wrong",
            f"scc_size={len(comp)}",
        ],
        suspects=suspects,
    )


def find_order_cycles(fb: FactBase, *, event_ids: list[str] | None = None) -> Report:
    digest = fb.digest()
    edges, unresolved = build_edges(fb)
    nodes = [e.id for e in fb.events]
    if event_ids is not None:
        keep = set(event_ids)
        nodes = [n for n in nodes if n in keep]
        edges = [ed for ed in edges if ed.src in keep and ed.dst in keep]
        unresolved = [u for u in unresolved if u in keep]
    adj = adjacency(edges)
    findings = []
    for comp in sccs(nodes, adj):
        cyclic = len(comp) > 1 or any(ed.dst == comp[0] for ed in adj.get(comp[0], ()))
        if cyclic:
            findings.append(_cycle_finding(fb, comp, adj, digest))
    return Report(
        rule_id=RULE_ID,
        findings=sort_findings(findings),
        stats={
            "consistent": 0,
            "cycles": len(findings),
            "edges": len(edges),
            "events": len(nodes),
            "unknown": 0,
            "unresolved_refs": len(unresolved),
            "violated": len(findings),
        },
        snapshot_digest=digest,
    )


def order_of(fb: FactBase, a: str, b: str) -> Finding:
    """reason_code carries the order: BEFORE (a<b), AFTER (b<a), CYCLIC, NO_PATH."""
    digest = fb.digest()
    subject = {"a": a, "b": b}
    ids = [a, b]
    unknown_ids = [i for i in ids if fb.event(i) is None]
    if unknown_ids:
        return make_finding(
            rule_id=RULE_ID,
            verdict=Verdict.UNKNOWN,
            reason_code="UNKNOWN_EVENT",
            digest=digest,
            id_parts=["order", *ids],
            subject=subject,
            missing=[f"event:{i}" for i in unknown_ids],
        )
    edges, unresolved = build_edges(fb)
    adj = adjacency(edges)
    pab = find_path(adj, a, b)
    pba = find_path(adj, b, a)
    if a == b:
        if pab is None:
            return make_finding(
                rule_id=RULE_ID,
                verdict=Verdict.UNKNOWN,
                reason_code="SAME_EVENT",
                digest=digest,
                id_parts=["order", a, b],
                subject=subject,
            )
        return _path_finding(
            fb, Verdict.VIOLATED, "CYCLIC", pab, digest, id_parts=["order", a, b], subject=subject
        )
    if pab and pba:
        return _path_finding(
            fb,
            Verdict.VIOLATED,
            "CYCLIC",
            [*pab, *pba],
            digest,
            id_parts=["order", a, b],
            subject=subject,
        )
    if pab or pba:
        path = pab or pba or []
        return _path_finding(
            fb,
            Verdict.CONSISTENT,
            "BEFORE" if pab else "AFTER",
            path,
            digest,
            id_parts=["order", a, b],
            subject=subject,
        )
    related = [u for u in unresolved if u in ids]
    ea, eb = fb.event(a), fb.event(b)
    return make_finding(
        rule_id=RULE_ID,
        verdict=Verdict.UNKNOWN,
        reason_code="NO_PATH",
        digest=digest,
        id_parts=["order", a, b],
        facts=[event_fact(x) for x in (ea, eb) if x is not None],
        steps=[("order_path", ids, "none")],
        subject=subject,
        missing=[f"order_path:{a}->{b}", *(f"resolvable_ref:{u}" for u in related)],
        notes=[
            f"{a}: {fmt_span(ea.time if ea else None)}",
            f"{b}: {fmt_span(eb.time if eb else None)}",
        ],
    )


def timeline(
    fb: FactBase,
    *,
    person_id: str | None = None,
    place_id: str | None = None,
    include_undated: bool = False,
    limit: int = 50,
) -> list[FactRef]:
    from detective_board.symbolic.places import PlaceIndex
    from detective_board.symbolic.time import abs_bounds

    idx = PlaceIndex(fb.places)
    dated: list[tuple[tuple[int, int], EventRec]] = []
    undated: list[EventRec] = []
    for e in fb.events:
        if person_id is not None and person_id not in e.participants:
            continue
        if place_id is not None and not idx.within(place_id, e.place_ref):
            continue
        b = abs_bounds(e.time)
        if b is None:
            undated.append(e)
        else:
            dated.append((b, e))
    dated.sort(key=lambda x: (x[0], x[1].id))
    out = [event_fact(e) for _, e in dated]
    if include_undated:
        out += [event_fact(e) for e in undated]
    return out[:limit]
