"""Round-trip and shape checks for scripts/corpus/ingest.py (needs data/chunks.jsonl)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("ingest", ROOT / "scripts" / "corpus" / "ingest.py")
ingest = importlib.util.module_from_spec(_spec)
sys.modules["ingest"] = ingest
_spec.loader.exec_module(ingest)

CHUNKS = ROOT / "data" / "chunks.jsonl"
CLEAN = ROOT / "data" / "clean"
FIELDS = {"chunk_id", "story", "section", "para_start", "para_end", "char_start", "char_end", "text"}


def test_synthetic_roundtrip():
    clean = "I.\n\n" + "\n\n".join(" ".join(f"w{i}x{j}" for j in range(40)) for i in range(30)) + "\n"
    rows = ingest.build_chunks("demo", clean)
    assert len(rows) > 1
    for r in rows:
        assert r["text"] == clean[r["char_start"]:r["char_end"]]
        assert r["section"] == "I"
    assert [r["para_start"] for r in rows[1:]] == [r["para_end"] + 1 for r in rows[:-1]]


def test_clean_story_unwraps_and_strips_trailing_numeral():
    assert ingest.clean_story("  a b\n  c d\n\n\n\n  e\n\nII\n") == "a b c d\n\ne\n"


@pytest.mark.skipif(not CHUNKS.exists(), reason="run scripts/corpus/ingest.py first")
def test_chunks_file_roundtrip():
    rows = [json.loads(line) for line in CHUNKS.read_text(encoding="utf-8").splitlines()]
    assert rows
    cache: dict[str, str] = {}
    ids = set()
    for r in rows:
        assert set(r) == FIELDS
        assert r["chunk_id"] not in ids
        ids.add(r["chunk_id"])
        clean = cache.setdefault(
            r["story"], (CLEAN / f"{r['story']}.txt").read_text(encoding="utf-8")
        )
        assert r["text"] == clean[r["char_start"]:r["char_end"]]
        assert r["para_start"] <= r["para_end"]
    assert 15 <= len(cache) <= 25
