"""Shared helpers: the case file, the pre-cut text, a tiny SQLite response cache."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import threading
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CASES = ROOT / "eval" / "suspects" / "cases.jsonl"
SPLIT = ROOT / "eval" / "suspects" / "split.json"
CLEAN = ROOT / "data" / "clean"
CHUNKS = ROOT / "data" / "chunks.jsonl"

_SENT_END = re.compile(r"(?<=[.!?])[\"'”’)]*\s+")


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    char_start: int
    char_end: int
    text: str


def load_cases(path: Path = CASES) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def load_split(path: Path = SPLIT) -> dict:
    return json.loads(path.read_text())


def story_text(story: str, clean_dir: Path = CLEAN) -> str:
    return (clean_dir / f"{story}.txt").read_text()


def pre_cut_chunks(story: str, cut_char: int, chunks_path: Path = CHUNKS) -> list[Chunk]:
    """Chunks that end at or before the cut; a chunk that straddles the cut is dropped (as in
    eval/pre_reveal.py)."""
    out = []
    for line in chunks_path.read_text().splitlines():
        if not line.strip():
            continue
        c = json.loads(line)
        if c["story"] == story and c["char_end"] <= cut_char:
            out.append(Chunk(c["chunk_id"], c["char_start"], c["char_end"], c["text"]))
    return sorted(out, key=lambda c: c.char_start)


def sentences(text: str) -> list[tuple[int, int]]:
    """Sentence spans [(start, end)) of `text`."""
    spans, pos = [], 0
    for m in _SENT_END.finditer(text):
        spans.append((pos, m.start() + 1))
        pos = m.end()
    if pos < len(text):
        spans.append((pos, len(text)))
    return spans


def window_around(text: str, a: int, b: int, *, around: int = 1) -> str:
    """The sentences containing [a, b) plus `around` sentences on each side."""
    sp = sentences(text)
    hit = [i for i, (s, e) in enumerate(sp) if s < b and e > a] or [0]
    lo, hi = max(0, hit[0] - around), min(len(sp) - 1, hit[-1] + around)
    return text[sp[lo][0] : sp[hi][1]]


class KV:
    """A thread-safe key -> text cache in one SQLite file."""

    def __init__(self, path: Path | str) -> None:
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.execute("create table if not exists kv (k text primary key, v text not null)")
        self._lock = threading.Lock()

    def get(self, key: str) -> str | None:
        with self._lock:
            row = self._db.execute("select v from kv where k=?", (key,)).fetchone()
        return row[0] if row else None

    def put(self, key: str, value: str) -> None:
        with self._lock:
            self._db.execute("insert or replace into kv values (?, ?)", (key, value))
            self._db.commit()


def digest(*parts: object) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(json.dumps(p, sort_keys=True, default=str).encode())
    return h.hexdigest()[:32]


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    r = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5)
    return (round(max(0.0, (c - r) / d), 3), round(min(1.0, (c + r) / d), 3))


def first(it: Iterable):
    for x in it:
        return x
    return None
