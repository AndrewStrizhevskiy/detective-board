"""What the agent needs from other zones, as protocols (adapters for GraphStore and MCP)."""

from __future__ import annotations

from typing import Any, Literal, Protocol

from detective_board.graph.results import GraphResult, PathResult
from detective_board.retrieval import Embedder, Hit, Store, hybrid_search


class Retriever(Protocol):
    def search(self, query: str, limit: int) -> list[Hit]: ...


class GraphBackend(Protocol):
    """Subset of `detective_board.graph.GraphStore` used by the agent."""

    def find_entities(
        self, name: str, *, kind: str | None = None, story: str | None = None, limit: int = 50
    ) -> GraphResult: ...

    def neighbours(
        self,
        ref: str,
        k: int = 1,
        *,
        story: str | None = None,
        direction: Literal["out", "in", "both"] = "both",
    ) -> GraphResult: ...

    def shortest_path(self, a: str, b: str, *, story: str | None = None) -> PathResult: ...

    def events_by_person(self, person: str, *, story: str | None = None) -> GraphResult: ...


class ToolClient(Protocol):
    """Synchronous facade over the MCP session (`McpSession.call_tool` is async).
    Returns the tool's JSON payload or the shared error object `{"error": {...}}`."""

    def call(self, tool: str, arguments: dict[str, Any], *, timeout: float) -> dict[str, Any]: ...


class HybridRetriever:
    """Adapter over `retrieval.hybrid_search`."""

    def __init__(self, store: Store, embedder: Embedder, **kw: Any) -> None:
        self.store, self.embedder, self.kw = store, embedder, kw

    def search(self, query: str, limit: int) -> list[Hit]:
        return hybrid_search(self.store, self.embedder, query, limit=limit, **self.kw)
