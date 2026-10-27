"""What the agent needs from other zones, as protocols (adapters for GraphStore and MCP)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from detective_board.graph.results import GraphResult, PathResult
from detective_board.retrieval import Embedder, Hit, Store, hybrid_search
from detective_board.retrieval.sentences import SentenceHit, SentenceStore, sentence_search


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


@dataclass
class SentenceResult:
    """Sentence-index hits (best first) and the chunks they belong to (full text, absolute
    offsets), so the agent can show and verify the quote against the chunk."""

    hits: list[SentenceHit]
    chunks: dict[str, Hit] = field(default_factory=dict)


class SentenceRetriever(Protocol):
    """Optional capability of a Retriever: `None` = no sentence index (fall back to chunks)."""

    def sentence_search(self, query: str, k: int) -> SentenceResult | None: ...


class _MemoEmbedder:
    """Remembers the last query vector: the chunk search and the sentence search of one question
    embed it once."""

    def __init__(self, inner: Embedder) -> None:
        self.inner, self.cfg = inner, inner.cfg
        self._last: tuple[str, list[float]] | None = None

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return self.inner.embed_documents(texts)

    def embed_query(self, text: str) -> list[float]:
        if self._last is None or self._last[0] != text:
            self._last = (text, self.inner.embed_query(text))
        return self._last[1]


class HybridRetriever:
    """Adapter over `retrieval.hybrid_search`; with a `SentenceStore` it also serves
    `sentence_search` (hybrid RRF over sentences, the query embedding shared with the chunk
    search)."""

    def __init__(
        self,
        store: Store,
        embedder: Embedder,
        sentences: SentenceStore | None = None,
        sentence_candidates: int = 50,
        **kw: Any,
    ) -> None:
        self.store, self.embedder, self.kw = store, _MemoEmbedder(embedder), kw
        self.sentences, self.sentence_candidates = sentences, sentence_candidates

    def search(self, query: str, limit: int) -> list[Hit]:
        return hybrid_search(self.store, self.embedder, query, limit=limit, **self.kw)

    def sentence_search(self, query: str, k: int) -> SentenceResult | None:
        if self.sentences is None:
            return None
        hits = sentence_search(
            self.sentences,
            query,
            self.embedder.embed_query(query),
            self.sentence_candidates,
            self.sentence_candidates,
            k,
        )
        chunks: dict[str, Hit] = {}
        for h in hits:
            if h.chunk_id in chunks:
                continue
            r = self.store.db.execute(
                "SELECT chunk_id, story, char_start, char_end, text FROM chunks WHERE chunk_id=?",
                (h.chunk_id,),
            ).fetchone()
            if r is not None:
                chunks[h.chunk_id] = Hit(
                    r["chunk_id"], r["story"], r["char_start"], r["char_end"], 0.0, text=r["text"]
                )
        return SentenceResult([h for h in hits if h.chunk_id in chunks], chunks)
