"""Deterministic fixture for `--fake` mode, UI development and tests.

Two flavours, chosen by `demo_mode()`:
- lean (under pytest, or `DETECTIVE_BOARD_FIXTURE=lean`): own short paraphrase sentences, three
  chunks of one story, a five-entity graph. Tests count these objects, so they never change.
- demo (a real `--fake` server, or `DETECTIVE_BOARD_FIXTURE=demo`): the lean data plus real
  passages of `data/clean` (verbatim, with the absolute offsets they have in that file) and a
  Boscombe Valley graph (persons, places, an item, events and claims, one rule-derived R3 edge
  with its Explanation) so the board is populated for the demo questions.
Both use a hash embedder and a scripted FakeLLM; every graph quote is a verbatim substring of
its chunk text."""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from collections.abc import Sequence
from typing import Any

from detective_board.agent import FakeLLM
from detective_board.extract.schema import Claim, Entity, Event, Extraction, Relation
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

# ---- demo flavour: verbatim passages of data/clean/*.txt with their real absolute offsets ----
S_ADDER_START = 48201
S_ADDER = (
    "\u201cThe band! the speckled band!\u201d whispered Holmes.\n\n"
    "I took a step forward. In an instant his strange headgear began to move, and there reared "
    "itself from among his hair the squat diamond-shaped head and puffed neck of a loathsome "
    "serpent.\n\n"
    "\u201cIt is a swamp adder!\u201d cried Holmes; \u201cthe deadliest snake in India. "
    "He has died within ten seconds of being bitten."
)
S_ADDER_QUOTE = "the deadliest snake in India"
B_DEMO_CHUNKS = [  # (chunk number, absolute start in boscombe-valley-mystery.txt, text)
    (
        3,
        2872,
        "The largest landed proprietor in that part is a Mr. John Turner, who made his money in "
        "Australia and returned some years ago to the old country. One of the farms which he "
        "held, that of Hatherley, was let to Mr. Charles McCarthy, who was also an ex-Australian.",
    ),
    (
        4,
        4004,
        "On June 3rd, that is, on Monday last, McCarthy left his house at Hatherley about three "
        "in the afternoon and walked down to the Boscombe Pool, which is a small lake formed by "
        "the spreading out of the stream which runs down the Boscombe Valley.",
    ),
    (
        5,
        4459,
        "From Hatherley Farmhouse to the Boscombe Pool is a quarter of a mile, and two people saw "
        "him as he passed over this ground. One was an old woman, whose name is not mentioned, "
        "and the other was William Crowder, a game-keeper in the employ of Mr. Turner. Both "
        "these witnesses depose that Mr. McCarthy was walking alone.",
    ),
    (
        6,
        5347,
        "A girl of fourteen, Patience Moran, who is the daughter of the lodge-keeper of the "
        "Boscombe Valley estate, was in one of the woods picking flowers. She states that while "
        "she was there she saw, at the border of the wood and close by the lake, Mr. McCarthy "
        "and his son, and that they appeared to be having a violent quarrel.",
    ),
    (
        7,
        12960,
        "I had no idea that he was in front of me. When about a hundred yards from the pool I "
        "heard a cry of \u201cCooee!\u201d which was a usual signal between my father and myself.",
    ),
]


def demo_mode() -> bool:
    """True for the rich demo dataset. `DETECTIVE_BOARD_FIXTURE=demo|lean` forces a flavour;
    otherwise tests (pytest loaded) get the lean one and a real server the demo one."""
    forced = os.environ.get("DETECTIVE_BOARD_FIXTURE", "").strip().lower()
    if forced in ("demo", "lean"):
        return forced == "demo"
    return "pytest" not in sys.modules


def _speckled_chunks() -> list[tuple[int, int, str]]:
    if not demo_mode():
        return CHUNKS
    return [(1, S_ADDER_START, S_ADDER), *CHUNKS[1:]]


def chunk_id(n: int, story: str = STORY) -> str:
    return f"{story}-{n:04d}"


def records() -> list[dict]:
    rows = [(STORY, n, start, text) for n, start, text in _speckled_chunks()]
    rows += [(B_STORY, n, start, text) for n, start, text in B_CHUNKS]
    if demo_mode():
        rows += [(B_STORY, n, start, text) for n, start, text in B_DEMO_CHUNKS]
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
    refs = {n: ChunkRef(chunk_id(n), STORY, s, s + len(t), t) for n, s, t in _speckled_chunks()}
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
    if demo_mode():
        _add_boscombe(g)
    return g


def _bref(n: int) -> ChunkRef:
    rows = {k: (st, tx) for k, st, tx in B_CHUNKS + B_DEMO_CHUNKS}
    start, text = rows[n]
    return ChunkRef(chunk_id(n, B_STORY), B_STORY, start, start + len(text), text)


def _ent(name: str, kind: str, quote: str, *aliases: str) -> Entity:
    return Entity(name=name, type=kind, aliases=list(aliases), quote=quote)  # type: ignore[arg-type]


def _add_boscombe(g: GraphStore) -> None:
    """Boscombe Valley sub-graph for the demo question about James McCarthy's account."""
    cm, jm, wc, pm = "Charles McCarthy", "James McCarthy", "William Crowder", "Patience Moran"
    pool = "Boscombe Pool"
    g.ingest_many(
        [
            (
                _bref(3),
                Extraction(
                    entities=[
                        _ent("John Turner", "person", "Mr. John Turner", "Turner"),
                        _ent(cm, "person", "Mr. Charles McCarthy"),
                        _ent("Hatherley", "place", "Hatherley"),
                    ],
                    relations=[
                        Relation(
                            subject=cm,
                            predicate="tenant of",
                            object="John Turner",
                            quote="One of the farms which he held, that of Hatherley, "
                            "was let to Mr. Charles McCarthy",
                        )
                    ],
                ),
            ),
            (
                _bref(4),
                Extraction(
                    entities=[_ent(cm, "person", "McCarthy"), _ent(pool, "place", pool)],
                    events=[
                        Event(
                            description="Charles McCarthy walks down to Boscombe Pool",
                            time_text="about three in the afternoon",
                            place=pool,
                            participants=[cm],
                            quote="McCarthy left his house at Hatherley about three in the "
                            "afternoon and walked down to the Boscombe Pool",
                        )
                    ],
                ),
            ),
            (
                _bref(5),
                Extraction(
                    entities=[
                        _ent(wc, "person", wc, "the game-keeper"),
                        _ent("an old woman", "person", "an old woman, whose name is not mentioned"),
                    ],
                    claims=[
                        Claim(
                            speaker=wc,
                            content="Charles McCarthy was walking alone",
                            about=cm,
                            quote="Both these witnesses depose that Mr. McCarthy was walking alone",
                        ),
                        Claim(
                            speaker="an old woman",
                            content="Charles McCarthy was walking alone",
                            about=cm,
                            quote="Both these witnesses depose that Mr. McCarthy was walking alone",
                        ),
                    ],
                ),
            ),
            (
                _bref(1),
                Extraction(
                    entities=[
                        _ent(jm, "person", "Mr. James McCarthy"),
                        _ent("a gun", "item", "a gun"),
                    ],
                    events=[
                        Event(
                            description="William Crowder sees Charles McCarthy pass",
                            participants=[wc, cm],
                            quote="his seeing Mr. McCarthy pass",
                        ),
                        Event(
                            description="William Crowder sees James McCarthy going the same way "
                            "with a gun",
                            participants=[wc, jm],
                            quote=B_FACT_QUOTE,
                        ),
                    ],
                    relations=[
                        Relation(
                            subject=jm,
                            predicate="carries",
                            object="a gun",
                            quote="Mr. James McCarthy, going the same way with a gun",
                        )
                    ],
                ),
            ),
            (
                _bref(6),
                Extraction(
                    entities=[_ent(pm, "person", pm)],
                    events=[
                        Event(
                            description="Charles and James McCarthy quarrel near the pool",
                            place=pool,
                            participants=[cm, jm],
                            quote="Mr. McCarthy and his son, and that they appeared to be "
                            "having a violent quarrel",
                        )
                    ],
                    claims=[
                        Claim(
                            speaker=pm,
                            content="the two McCarthys were quarrelling violently",
                            about=cm,
                            quote="she saw, at the border of the wood and close by the lake, "
                            "Mr. McCarthy and his son, and that they appeared to be having "
                            "a violent quarrel",
                        )
                    ],
                ),
            ),
            (
                _bref(2),
                Extraction(
                    entities=[_ent(wc, "person", wc)],
                    claims=[
                        Claim(
                            speaker=jm,
                            content="he was not following his father",
                            about=cm,
                            quote=B_CLAIM_QUOTE,
                        )
                    ],
                ),
            ),
            (
                _bref(7),
                Extraction(
                    entities=[_ent(pool, "place", "the pool")],
                    events=[
                        Event(
                            description="James McCarthy hears a cry of Cooee near the pool",
                            place=pool,
                            participants=[jm],
                            quote="When about a hundred yards from the pool I heard a cry of "
                            "\u201cCooee!\u201d",
                        )
                    ],
                    claims=[
                        Claim(
                            speaker=jm,
                            content="he did not know his father was ahead of him",
                            about=cm,
                            quote="I had no idea that he was in front of me",
                        )
                    ],
                ),
            ),
        ]
    )
    exp = boscombe_explanation()
    a = exp.anchors[1]  # the claim's anchor: the derived edge is justified by that quote
    g.conn.execute(
        "INSERT INTO g_edge(src,dst,rel,props_json,provenance,confidence,chunk_id,char_start,"
        "char_end,rel_start,rel_end,quote,ambiguous) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,0)",
        (
            exp.facts[0].fact_id,
            exp.facts[1].fact_id,
            "CONTRADICTS",
            json.dumps({"explanation": exp.model_dump(mode="json"), "rule": exp.rule_id}),
            "derived",
            "high",
            a.chunk_id,
            a.char_start,
            a.char_end,
            a.rel_start,
            a.rel_end,
            a.quote,
        ),
    )


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
        fact_id="c:boscombe-valley-mystery-0002:0",
        kind="claim",
        provenance="extracted",
        confidence="high",
        summary="James McCarthy: he was not following his father",
        anchors=[claim_a],
    )
    event = FactRef(
        fact_id="e:boscombe-valley-mystery-0001:1",
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
                edge_id="asserts:c:boscombe-valley-mystery-0002:0",
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
_VEC_SRC = re.compile(r"n=(\d+) [^>\n]*origin=vector[^>\n]*>>>\n(.*?)\n<<<END", re.S)


def _answer(messages: Sequence[dict[str, str]]) -> str:
    """Canned answer; when a rule result is in the prompt, cite its anchored quotes."""
    user = messages[-1]["content"]
    found = _TOOL_SRC.findall(user)
    if "RULE RESULT" in user and found:
        found.sort(key=lambda f: "mistaken" not in f[1])  # A = his account, B = what was seen
        cites = " ".join(f'[{n}: "{text}"]' for n, text in found)
        if demo_mode():
            return (
                "James McCarthy told the inquest that he was not following his father, yet the "
                f"game-keeper saw him going the same way with a gun. {cites}"
            )
        return (
            f"The rule engine finds James McCarthy going the same way with a gun, a "
            f"contradiction. {cites}"
        )
    if demo_mode():
        for n, text in _VEC_SRC.findall(user):
            if S_ADDER_QUOTE in text:
                return (
                    "Holmes says the speckled band is a swamp adder, "
                    f'"{S_ADDER_QUOTE}". [{n}: "{S_ADDER_QUOTE}"]'
                )
    return FAKE_ANSWER


def build_llm() -> FakeLLM:
    return FakeLLM(_answer)
