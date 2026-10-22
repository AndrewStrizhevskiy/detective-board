"""Feed extraction results into the graph (detective_board.graph.GraphStore, v1 ingest input)."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from detective_board.extract.pipeline import ChunkResult
from detective_board.extract.schema import Extraction as ExtractionV1
from detective_board.extract.schema_v2 import to_v1


def to_graph_input(res: ChunkResult, chunk_rec: Mapping[str, Any]) -> tuple[Any, ExtractionV1]:
    """(ChunkRef, v1 Extraction) as `GraphStore.ingest` expects. v2-only fields are not stored
    by the graph yet (they need graph-engineer support, see docs/backlog.md R-07)."""
    from detective_board.graph import ChunkRef

    return ChunkRef.from_record(dict(chunk_rec)), to_v1(res.to_extraction())


def ingest_results(
    store: Any,
    results: Iterable[ChunkResult],
    chunks_by_id: Mapping[str, Mapping[str, Any]],
) -> list[Any]:
    """Ingest usable results (status ok/repaired) into `store`; returns IngestReports."""
    items = [
        to_graph_input(r, chunks_by_id[r.chunk_id])
        for r in results
        if r.status in ("ok", "repaired") and r.chunk_id in chunks_by_id
    ]
    return store.ingest_many(items)
