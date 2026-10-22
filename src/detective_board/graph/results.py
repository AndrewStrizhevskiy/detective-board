"""Trace-friendly result types: every query result carries node/edge ids and anchors."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from detective_board.symbolic.model import Anchor, Confidence


class _M(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class NodeHit(_M):
    id: str
    kind: Literal["person", "place", "item", "event", "claim"]
    story: str
    name: str | None
    aliases: list[str] = []
    confidence: Confidence
    provenance: Literal["extracted", "derived"] = "extracted"
    props: dict[str, Any] = {}
    anchors: list[Anchor] = []  # first `max_anchors`, ordered by position
    anchor_total: int = 0
    hops: int | None = None  # distance from the nearest seed (neighbour queries)

    @property
    def label(self) -> str:
        return self.name or str(
            self.props.get("description") or self.props.get("content") or self.id
        )


class EdgeHit(_M):
    id: int
    rel: str
    src: str
    dst: str
    confidence: Confidence
    provenance: Literal["extracted", "derived"] = "extracted"
    props: dict[str, Any] = {}
    anchor: Anchor


class GraphResult(_M):
    query_kind: str
    seeds: list[str] = []
    nodes: list[NodeHit] = []
    edges: list[EdgeHit] = []
    truncated: bool = False
    notes: list[str] = []

    @property
    def node_ids(self) -> list[str]:
        return [n.id for n in self.nodes]

    @property
    def edge_ids(self) -> list[int]:
        return [e.id for e in self.edges]

    @property
    def anchors(self) -> list[Anchor]:
        """All distinct anchors (node and edge), ordered by position, for UI highlighting."""
        seen: dict[tuple, Anchor] = {}
        for a in [*(a for n in self.nodes for a in n.anchors), *(e.anchor for e in self.edges)]:
            seen.setdefault((a.story, a.chunk_id, a.char_start, a.char_end, a.rel_start), a)
        return [seen[k] for k in sorted(seen, key=lambda k: (k[0], k[2], k[3], k[1], k[4] or 0))]

    def trace_payload(self) -> dict[str, Any]:
        """Payload of the `retrieve.graph` trace event (docs/data-schema.md section 5)."""
        return {
            "query_kind": self.query_kind,
            "seeds": list(self.seeds),
            "nodes": [{"id": n.id, "kind": n.kind, "name": n.label} for n in self.nodes],
            "edges": [
                {
                    "id": e.id,
                    "rel": e.rel,
                    "src": e.src,
                    "dst": e.dst,
                    "anchor": e.anchor.model_dump(mode="json"),
                }
                for e in self.edges
            ],
            "truncated": self.truncated,
        }


class PathResult(GraphResult):
    """Shortest path: `nodes` and `edges` are in path order (nodes[i] --edges[i]--> nodes[i+1],
    direction-insensitive: check `EdgeHit.src/dst` for the stored direction)."""

    found: bool = False
    hops: int | None = None
