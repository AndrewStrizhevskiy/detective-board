"""JSON views over `graph.GraphStore` for the UI (read-only)."""

from __future__ import annotations

from typing import Any

from detective_board.graph import GraphResult, GraphStore, normalize_name

ENTITY_KINDS = ("person", "place", "item")


def _node(n: Any) -> dict[str, Any]:
    d = n.model_dump(mode="json")
    d["label"] = n.label
    return d


def _edge(e: Any) -> dict[str, Any]:
    return e.model_dump(mode="json")


def result_json(res: GraphResult, **extra: Any) -> dict[str, Any]:
    """Nodes and edges with provenance (`extracted`/`derived`), confidence and anchors; the
    union of all anchors is repeated in `anchors` for highlighting."""
    return {
        "query_kind": res.query_kind,
        "seeds": list(res.seeds),
        "nodes": [_node(n) for n in res.nodes],
        "edges": [_edge(e) for e in res.edges],
        "anchors": [a.model_dump(mode="json") for a in res.anchors],
        "truncated": res.truncated,
        "notes": list(res.notes),
        **extra,
    }


def subgraph(
    graph: GraphStore, entity: str, hops: int, *, story: str | None, max_nodes: int
) -> dict[str, Any]:
    res = graph.neighbours(entity, k=hops, story=story, max_nodes=max_nodes)
    return result_json(res, entity=entity, hops=hops)


def _like(s: str) -> str:
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def search_entities(
    graph: GraphStore, q: str, *, kind: str | None, story: str | None, limit: int
) -> dict[str, Any]:
    """Entities whose name or alias contains `q` (case-insensitive); exact matches first.
    Empty `q` lists entities by number of mentions."""
    where, args = [f"n.kind IN ({','.join('?' * len(ENTITY_KINDS))})"], list(ENTITY_KINDS)
    if kind:
        where.append("n.kind=?")
        args.append(kind)
    if story:
        where.append("n.story=?")
        args.append(story)
    needle = normalize_name(q, "person") if q else ""
    exact = {normalize_name(q, k) for k in ENTITY_KINDS} if q else set()
    if needle or q:
        pat = "%" + _like(needle or q.casefold()) + "%"
        where.append(
            "(n.norm_name LIKE ? ESCAPE '\\' OR n.id IN (SELECT node_id FROM g_mention"
            " WHERE role IN ('name','alias') AND surface_norm LIKE ? ESCAPE '\\'))"
        )
        args += [pat, pat]
    rows = graph.conn.execute(
        "SELECT n.id, n.norm_name, (SELECT COUNT(*) FROM g_mention m WHERE m.node_id=n.id) mentions"
        f" FROM g_node n WHERE {' AND '.join(where)}",
        args,
    ).fetchall()
    rows = sorted(
        rows,
        key=lambda r: (r["norm_name"] not in exact, -r["mentions"], r["norm_name"] or "", r["id"]),
    )
    ids = [r["id"] for r in rows]
    nodes = []
    for nid in ids[:limit]:
        n = graph.get_node(nid)
        if n:
            nodes.append(
                {**_node(n), "mentions": next(r["mentions"] for r in rows if r["id"] == nid)}
            )
    return {"q": q, "entities": nodes, "total": len(ids), "truncated": len(ids) > limit}
