"""Tiny deterministic fixture for `--fake` mode, UI development and tests.

Own short paraphrase sentences (not corpus text), three chunks of one story, a hash embedder,
a scripted FakeLLM. The graph quotes are verbatim substrings of the chunk texts."""

from __future__ import annotations

import json
import os
import re
import tempfile
from collections.abc import Sequence
from typing import Any

from detective_board.agent import FakeLLM
from detective_board.extract.schema import Entity, Extraction, Relation
from detective_board.graph import ChunkRef, GraphStore
from detective_board.mcp.errors import error_payload
from detective_board.retrieval import (
    EmbeddingConfig,
    HashEmbedder,
    Store,
    embed_missing,
    load_chunks,
)
from detective_board.symbolic.api import Anchor as SymAnchor
from detective_board.symbolic.api import EdgeRef, Explanation, FactRef, Step, Verdict

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


# Two verbatim sentences of data/clean/boscombe-valley-mystery.txt (absolute offsets in that
# file) for the derived R3 finding of the fake tool; they are also indexed so /api/source works.
B_STORY = "boscombe-valley-mystery"
B_FACT = (
    "The game-keeper adds that within a few minutes of his seeing Mr. McCarthy pass he had seen "
    "his son, Mr. James McCarthy, going the same way with a gun under his arm."
)
B_CLAIM = (
    "On my way I saw William Crowder, the game-keeper, as he had stated in his evidence; but he "
    "is mistaken in thinking that I was following my father."
)
B_CHUNKS = [(1, 4777, B_FACT), (2, 12813, B_CLAIM)]
B_FACT_QUOTE = (
    "he had seen his son, Mr. James McCarthy, going the same way with a gun under his arm"
)
B_CLAIM_QUOTE = "he is mistaken in thinking that I was following my father"


def chunk_id(n: int, story: str = STORY) -> str:
    return f"{story}-{n:04d}"


def records() -> list[dict]:
    rows = [(STORY, n, start, text) for n, start, text in CHUNKS]
    rows += [(B_STORY, n, start, text) for n, start, text in B_CHUNKS]
    return [
        {
            "chunk_id": chunk_id(n, story),
            "story": story,
            "section": "I",
            "para_start": n,
            "para_end": n,
            "char_start": start,
            "char_end": start + len(text),
            "text": text,
        }
        for story, n, start, text in rows
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


def _anchor(chunk_n: int, start: int, text: str, quote: str) -> SymAnchor:
    rel = text.index(quote)
    return SymAnchor(
        story=B_STORY,
        chunk_id=chunk_id(chunk_n, B_STORY),
        char_start=start + rel,
        char_end=start + rel + len(quote),
        quote=quote,
        rel_start=rel,
        rel_end=rel + len(quote),
    )


def boscombe_explanation() -> Explanation:
    """R3 (witness claim vs established fact), shaped like the rule engine's output."""
    fact_a = _anchor(1, B_CHUNKS[0][1], B_FACT, B_FACT_QUOTE)
    claim_a = _anchor(2, B_CHUNKS[1][1], B_CLAIM, B_CLAIM_QUOTE)
    claim = FactRef(
        fact_id="c:boscombe-valley-mystery-0002:1",
        kind="claim",
        provenance="extracted",
        confidence="high",
        summary="James McCarthy: he was not following his father",
        anchors=[claim_a],
    )
    event = FactRef(
        fact_id="e:boscombe-valley-mystery-0001:2",
        kind="event",
        provenance="extracted",
        confidence="high",
        summary="Crowder saw James McCarthy going the same way, after his father",
        anchors=[fact_a],
    )
    return Explanation(
        rule_id="R3",
        rule_version="1",
        verdict=Verdict.VIOLATED,
        conditional=False,
        reason_code="CLAIM_INCOMPATIBLE_WITH_FACT",
        facts=[claim, event],
        edges=[
            EdgeRef(
                edge_id="asserts:c:boscombe-valley-mystery-0002:1",
                rel="ASSERTS",
                src="p:boscombe-valley-mystery:james-mccarthy",
                dst=claim.fact_id,
                anchors=[claim_a],
            )
        ],
        derivation=[
            Step(
                step=1,
                op="order_edge",
                inputs=[event.fact_id],
                output="father < son (narrator-stated order)",
            ),
            Step(
                step=2,
                op="claim_vs_fact",
                inputs=[claim.fact_id, event.fact_id],
                output="claim 'son not following father' contradicts the stated order",
            ),
        ],
        anchors=[fact_a, claim_a],
        depends_on_extracted=[claim, event],
        weak=[],
        missing=[],
        notes=[
            "fake-mode fixture: the witness is not called a liar; narrator voice may be partial"
        ],
        subject={
            "claim_id": claim.fact_id,
            "speaker_id": "p:boscombe-valley-mystery:james-mccarthy",
        },
    )


class FakeToolClient:
    """Stands in for the MCP client in `--fake` mode: one derived R3 finding, no I/O."""

    def call(self, tool: str, arguments: dict[str, Any], *, timeout: float) -> dict[str, Any]:
        if tool != "find_contradictions":
            return error_payload("not_found", f"fake mode has no data for {tool}")
        exp = boscombe_explanation()
        return {
            "status": "ok",
            "findings": [
                {
                    "rule": exp.rule_id,
                    "finding_id": "R3:fake-boscombe",
                    "reason_code": exp.reason_code,
                    "provenance": "derived",
                    "explanation": exp.model_dump(mode="json"),
                    "anchors": [a.model_dump(mode="json") for a in exp.anchors],
                }
            ],
            "truncated": False,
        }

    def close(self) -> None:
        pass


_TOOL_SRC = re.compile(r"n=(\d+) [^>\n]*origin=tool[^>\n]*>>>\n(.*?)\n<<<END", re.S)


def _answer(messages: Sequence[dict[str, str]]) -> str:
    """Canned answer; when a rule result is in the prompt, cite its anchored quotes."""
    user = messages[-1]["content"]
    found = _TOOL_SRC.findall(user)
    if "RULE RESULT" not in user or not found:
        return FAKE_ANSWER
    cites = " ".join(f'[{n}: "{text}"]' for n, text in found)
    return (
        f"The rule engine finds James McCarthy going the same way with a gun, a contradiction. "
        f"{cites}"
    )


def build_llm() -> FakeLLM:
    return FakeLLM(_answer)
