"""Optional reranker seam. No implementation yet; pass-through by default."""

from __future__ import annotations

from typing import Protocol

from .search import Hit


class Reranker(Protocol):
    def rerank(self, query: str, hits: list[Hit]) -> list[Hit]: ...


class PassThroughReranker:
    def rerank(self, query: str, hits: list[Hit]) -> list[Hit]:
        return hits
