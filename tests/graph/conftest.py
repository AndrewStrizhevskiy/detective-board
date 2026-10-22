import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from detective_board.extract.schema import Claim, Entity, Event, Extraction, Relation  # noqa: E402
from detective_board.graph import ChunkRef, GraphStore  # noqa: E402

STORY = "boscombe-valley-mystery"
C2, C3, C7 = (f"{STORY}-{n:04d}" for n in (2, 3, 7))


def _records() -> dict[str, dict]:
    path = ROOT / "data" / "chunks.jsonl"
    if not path.exists():
        pytest.skip("data/chunks.jsonl not available")
    return {r["chunk_id"]: r for r in map(json.loads, path.read_text().splitlines())}


@pytest.fixture(scope="session")
def chunks() -> dict[str, ChunkRef]:
    recs = _records()
    clean = (ROOT / "data" / "clean" / f"{STORY}.txt").read_text()
    return {cid: ChunkRef.from_record(recs[cid], clean) for cid in (C2, C3, C7)}


def synth(cid: str, text: str, story: str = "syn") -> ChunkRef:
    return ChunkRef(chunk_id=cid, story=story, char_start=100, char_end=100 + len(text), text=text)


def person(name, quote, aliases=()):
    return Entity(name=name, type="person", aliases=list(aliases), quote=quote)


def place(name, quote, aliases=()):
    return Entity(name=name, type="place", aliases=list(aliases), quote=quote)


def boscombe_extractions() -> dict[str, Extraction]:
    """Hand-built extractions with verbatim quotes from the real chunks."""
    e2 = Extraction(
        entities=[
            person("Charles McCarthy", "Mr. Charles McCarthy", ["McCarthy"]),
            person("John Turner", "Mr. John Turner", ["Turner"]),
            place("Hatherley", "that of Hatherley", ["Hatherley Farm"]),
            place("Boscombe Pool", "the Boscombe Pool, which is a small lake"),
        ],
        events=[
            Event(
                description="McCarthy walked down to the Boscombe Pool",
                time_text="about three in the afternoon",
                place="Boscombe Pool",
                participants=["Charles McCarthy"],
                quote="McCarthy left his house at Hatherley about three in the afternoon "
                "and walked down to the Boscombe Pool",
            )
        ],
        relations=[
            Relation(
                subject="Charles McCarthy",
                predicate="tenant of",
                object="John Turner",
                quote="McCarthy became his tenant",
            )
        ],
    )
    e3 = Extraction(
        entities=[
            person("William Crowder", "William Crowder, a game-keeper"),
            person("Patience Moran", "Patience Moran"),
            person("Mr. McCarthy", "Mr. McCarthy was walking alone"),
            person("James McCarthy", "Mr. James McCarthy", ["Mr. James McCarthy"]),
            place("The Boscombe Pool", "The Boscombe Pool is thickly wooded"),
        ],
        events=[
            Event(
                description="Patience Moran saw the two McCarthys quarrelling",
                time_text="a quarter to four in the afternoon",
                place="Boscombe Pool",
                participants=["Patience Moran", "Mr. McCarthy", "James McCarthy"],
                quote="she saw, at the border of the wood and close by the lake, "
                "Mr. McCarthy and his son",
            )
        ],
    )
    e7 = Extraction(
        entities=[
            person("James McCarthy", "Mr. James McCarthy, the only son of the deceased"),
            person("the deceased", "the deceased"),
            place("Hatherley Farm", "Hatherley Farm"),
        ],
        claims=[
            Claim(
                speaker="James McCarthy",
                content="I left my father and returned towards Hatherley Farm",
                about="Hatherley Farm",
                quote="I left him and returned towards Hatherley Farm",
            )
        ],
    )
    return {C2: e2, C3: e3, C7: e7}


def build_boscombe(chunks) -> GraphStore:
    store = GraphStore()
    exs = boscombe_extractions()
    store.ingest_many([(chunks[c], exs[c]) for c in (C7, C2, C3)])  # sorted by ingest_many
    return store


@pytest.fixture
def bv(chunks) -> GraphStore:
    return build_boscombe(chunks)
