"""Shared helpers: real chunks from data/chunks.jsonl and a canned-JSON fake LLM client."""

import json
from functools import cache
from pathlib import Path

import pytest

from detective_board.extract.llm import FakeClient

ROOT = Path(__file__).resolve().parents[2]
BV, WL = "boscombe-valley-mystery", "wisteria-lodge"


@cache
def records() -> dict[str, dict]:
    path = ROOT / "data" / "chunks.jsonl"
    if not path.exists():
        pytest.skip("data/chunks.jsonl not available")
    with open(path, encoding="utf-8") as f:
        return {r["chunk_id"]: r for r in map(json.loads, f)}


def rec(chunk_id: str) -> dict:
    return records()[chunk_id]


def write_chunks(path: Path, *chunk_ids: str) -> Path:
    path.write_text("\n".join(json.dumps(rec(c)) for c in chunk_ids) + "\n", encoding="utf-8")
    return path


def fact(**kw) -> dict:
    base = {"polarity": "affirm", "source": "narrator", "day_text": None, "speaker": None}
    return {**base, **kw}


def fake_by_passage(table: dict[str, list[dict]]) -> FakeClient:
    """A FakeClient answering with the canned facts whose key occurs in the prompt's passage."""

    def answer(prompt: str) -> str:
        passage = prompt.rsplit("Passage:\n", 1)[1]
        for key, facts in table.items():
            if key in passage:
                return json.dumps({"facts": facts}, ensure_ascii=False)
        return json.dumps({"facts": []})

    return FakeClient(answer)
