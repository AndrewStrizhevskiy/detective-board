import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

CHUNK = (
    "I left the house at nine o’clock, said James McCarthy. “I never touched the gun,” "
    "he added.\nThe\tdeceased was found by the pool at Boscombe."
)


def good_output(**over) -> str:
    d = {
        "entities": [
            {"name": "James McCarthy", "type": "person", "aliases": [], "quote": "James McCarthy"},
            {"name": "the deceased", "type": "person", "unnamed": True,
             "quote": "The deceased was found"},
        ],
        "events": [
            {"description": "He left the house", "time_text": "nine o'clock",
             "participants": ["James McCarthy"], "in_speech": True,
             "quote": "I left the house at nine o'clock"}
        ],
        "claims": [
            {"speaker": "James McCarthy", "content": "He never touched the gun",
             "polarity": "deny", "quote": "I never touched the gun"}
        ],
        "relations": [],
    }  # fmt: skip
    d.update(over)
    return json.dumps(d)


@pytest.fixture
def chunk_text():
    return CHUNK


@pytest.fixture
def chunks_file(tmp_path):
    p = tmp_path / "chunks.jsonl"
    recs = [
        {"chunk_id": f"s{n}-000{i}", "story": f"s{n}", "char_start": 0, "char_end": len(CHUNK),
         "text": CHUNK + f" {n}{i}"}
        for n in (1, 2) for i in range(2)
    ]  # fmt: skip
    p.write_text("\n".join(json.dumps(r) for r in recs) + "\n", encoding="utf-8")
    return p
