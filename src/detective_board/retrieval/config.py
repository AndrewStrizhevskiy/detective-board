"""Embedding configuration: model identity is data, not code."""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class EmbeddingConfig:
    model: str
    dim: int
    doc_prefix: str = ""
    query_prefix: str = ""
    metric: str = "cosine"  # vec0 distance_metric: cosine | l2

    def as_meta(self) -> dict[str, str]:
        return {k: str(v) for k, v in asdict(self).items()}
