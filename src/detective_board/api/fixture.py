"""Tiny deterministic fixture for `--fake` mode, UI development and tests.

Own short paraphrase sentences (not corpus text), three chunks of one story, a hash embedder,
a scripted FakeLLM. The graph quotes are verbatim substrings of the chunk texts."""

from __future__ import annotations

import json
import os
import tempfile

from detective_board.agent import FakeLLM
from detective_board.extract.schema import Entity, Extraction, Relation
from detective_board.graph import ChunkRef, GraphStore
from detective_board.retrieval import (
    EmbeddingConfig,
    HashEmbedder,
    Store,
    embed_missing,
    load_chunks,
)

STORY = "speckled-band"
EMBED_CFG = EmbeddingConfig(model="fake-hash", dim=64, doc_prefix="doc: ", query_prefix="q: ")
FAKE_ANSWER = 'The band was a snake. [1: "a deadly snake from India"]'

CHUNKS = [
    (1, 1000, "Holmes said the speckled band was a swamp adder, a deadly snake from India."),
    (
        2,
        2000,
        "Dr. Grimesby Roylott kept a cheetah and a baboon in the grounds of Stoke Moran. "
        "Helen Stoner was his stepdaughter.",
    ),
    (
        3,
        3000,
        "Julia Stoner died at Stoke Moran two years ago, and Helen Stoner feared the same fate.",
    ),
]


def chunk_id(n: int) -> str:
    return f"{STORY}-{n:04d}"


def records() -> list[dict]:
    return [
        {
            "chunk_id": chunk_id(n),
            "story": STORY,
            "section": "I",
            "para_start": n,
            "para_end": n,
            "char_start": start,
            "char_end": start + len(text),
            "text": text,
        }
        for n, start, text in CHUNKS
    ]


def build_store(path: str = ":memory:") -> tuple[Store, HashEmbedder]:
    store = Store(path, EMBED_CFG)
    emb = HashEmbedder(EMBED_CFG)
    fd, name = tempfile.mkstemp(suffix=".jsonl")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write("\n".join(json.dumps(r) for r in records()) + "\n")
        load_chunks(store, name)
    finally:
        os.unlink(name)
    embed_missing(store, emb)
    return store, emb


def _person(name: str, quote: str, aliases: tuple[str, ...] = ()) -> Entity:
    return Entity(name=name, type="person", aliases=list(aliases), quote=quote)


def build_graph(path: str = ":memory:") -> GraphStore:
    g = GraphStore(path)
    refs = {n: ChunkRef(chunk_id(n), STORY, s, s + len(t), t) for n, s, t in CHUNKS}
    g.ingest_many(
        [
            (
                refs[1],
                Extraction(entities=[_person("Sherlock Holmes", "Holmes", ("Holmes",))]),
            ),
            (
                refs[2],
                Extraction(
                    entities=[
                        _person("Dr. Grimesby Roylott", "Dr. Grimesby Roylott"),
                        _person("Helen Stoner", "Helen Stoner"),
                        Entity(
                            name="Stoke Moran", type="place", quote="the grounds of Stoke Moran"
                        ),
                    ],
                    relations=[
                        Relation(
                            subject="Helen Stoner",
                            predicate="stepdaughter of",
                            object="Dr. Grimesby Roylott",
                            quote="Helen Stoner was his stepdaughter",
                        )
                    ],
                ),
            ),
            (
                refs[3],
                Extraction(
                    entities=[
                        _person("Julia Stoner", "Julia Stoner"),
                        Entity(name="Stoke Moran", type="place", quote="Stoke Moran"),
                        _person("Helen Stoner", "Helen Stoner"),
                    ]
                ),
            ),
        ]
    )
    return g


def build_llm() -> FakeLLM:
    return FakeLLM(FAKE_ANSWER)
