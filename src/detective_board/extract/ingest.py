"""Feed extraction results into the graph (detective_board.graph.GraphStore, v1 ingest input)."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from detective_board.extract.pipeline import ChunkResult, apply_repair
from detective_board.extract.repair import REPAIR_VERSION
from detective_board.extract.schema_v2 import Extraction


def to_graph_input(
    res: ChunkResult, chunk_rec: Mapping[str, Any], *, repair: bool = True
) -> tuple[Any, Extraction]:
    """(ChunkRef, v2 Extraction) for `GraphStore.ingest`. v2 is a superset of v1; the graph keeps
    the claim about_*/polarity and event in_speech/transit fields (backlog R-11). A result that
    was not repaired by the pipeline (older run files, `repair=False`) is repaired here from the
    chunk text, so `just graph` from cached model output always ingests grounded fields."""
    from detective_board.graph import ChunkRef

    if repair and res.extraction and res.repair.get("version") != REPAIR_VERSION:
        apply_repair(res, str(chunk_rec["text"]))

    return ChunkRef.from_record(dict(chunk_rec)), res.to_extraction()


def ingest_results(
    store: Any,
    results: Iterable[ChunkResult],
    chunks_by_id: Mapping[str, Mapping[str, Any]],
    *,
    repair: bool = True,
) -> list[Any]:
    """Ingest usable results (status ok/repaired) into `store`; returns IngestReports."""
    items = [
        to_graph_input(r, chunks_by_id[r.chunk_id], repair=repair)
        for r in results
        if r.status in ("ok", "repaired") and r.chunk_id in chunks_by_id
    ]
    return store.ingest_many(items)
