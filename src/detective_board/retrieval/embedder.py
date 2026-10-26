"""Embedder protocol, Ollama HTTP implementation (/api/embed) and a fake for tests."""

from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import struct
import urllib.request
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from .config import EmbeddingConfig


class Embedder(Protocol):
    cfg: EmbeddingConfig

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...
    def embed_query(self, text: str) -> list[float]: ...


def _pack(v: Sequence[float]) -> bytes:
    return struct.pack(f"{len(v)}f", *v)


def _unpack(b: bytes) -> list[float]:
    return list(struct.unpack(f"{len(b) // 4}f", b))


class EmbeddingCache:
    """On-disk cache keyed by sha256(model, prefix, text); makes embedding resumable."""

    def __init__(self, path: str | Path):
        self.db = sqlite3.connect(str(path))
        self.db.execute("CREATE TABLE IF NOT EXISTS emb (key TEXT PRIMARY KEY, vec BLOB NOT NULL)")

    @staticmethod
    def key(model: str, prefix: str, text: str) -> str:
        return hashlib.sha256(f"{model}\0{prefix}\0{text}".encode()).hexdigest()

    def get(self, key: str) -> list[float] | None:
        r = self.db.execute("SELECT vec FROM emb WHERE key=?", (key,)).fetchone()
        return _unpack(r[0]) if r else None

    def put_many(self, items: dict[str, list[float]]) -> None:
        with self.db:
            self.db.executemany(
                "INSERT OR REPLACE INTO emb(key, vec) VALUES (?, ?)",
                [(k, _pack(v)) for k, v in items.items()],
            )

    def close(self) -> None:
        self.db.close()


class OllamaEmbedder:
    def __init__(
        self,
        cfg: EmbeddingConfig,
        base_url: str = "http://localhost:11434",
        batch_size: int = 16,
        cache: EmbeddingCache | None = None,
        timeout: float = 120.0,
        keep_alive: str | None = None,
    ):
        self.cfg, self.base_url, self.batch_size = cfg, base_url.rstrip("/"), batch_size
        self.cache, self.timeout, self.keep_alive = cache, timeout, keep_alive

    def _post(self, inputs: list[str]) -> list[list[float]]:
        payload: dict[str, object] = {"model": self.cfg.model, "input": inputs}
        if self.keep_alive:
            payload["keep_alive"] = self.keep_alive
        req = urllib.request.Request(
            f"{self.base_url}/api/embed",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # noqa: S310
            out = json.load(resp)["embeddings"]
        if len(out) != len(inputs) or any(len(v) != self.cfg.dim for v in out):
            raise ValueError(
                f"unexpected embedding shape from {self.cfg.model} (want dim {self.cfg.dim})"
            )
        return out

    def _embed(self, texts: Sequence[str], prefix: str) -> list[list[float]]:
        keys = [EmbeddingCache.key(self.cfg.model, prefix, t) for t in texts]
        result: dict[int, list[float]] = {}
        todo: list[int] = []
        for i, k in enumerate(keys):
            hit = self.cache.get(k) if self.cache else None
            if hit is None:
                todo.append(i)
            else:
                result[i] = hit
        for s in range(0, len(todo), self.batch_size):
            idx = todo[s : s + self.batch_size]
            vecs = self._post([prefix + texts[i] for i in idx])
            for i, v in zip(idx, vecs, strict=True):
                result[i] = v
            if self.cache:  # persist per batch: a crash loses at most one batch
                self.cache.put_many({keys[i]: v for i, v in zip(idx, vecs, strict=True)})
        return [result[i] for i in range(len(texts))]

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return self._embed(texts, self.cfg.doc_prefix)

    def embed_query(self, text: str) -> list[float]:
        return self._embed([text], self.cfg.query_prefix)[0]


class HashEmbedder:
    """Deterministic fake: L2-normalised hashed bag of words (lexical overlap => similarity)."""

    def __init__(self, cfg: EmbeddingConfig):
        self.cfg = cfg

    def _vec(self, text: str) -> list[float]:
        v = [0.0] * self.cfg.dim
        for w in re.findall(r"\w+", text.lower()):
            h = int.from_bytes(hashlib.blake2b(w.encode(), digest_size=8).digest(), "big")
            v[h % self.cfg.dim] += 1.0 if (h >> 63) & 1 else -1.0
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / n for x in v]

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._vec(self.cfg.doc_prefix + t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vec(self.cfg.query_prefix + text)
