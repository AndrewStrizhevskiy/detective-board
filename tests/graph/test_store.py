import sqlite3

import pytest
from .conftest import C2, C3, C7, STORY, boscombe_extractions, build_boscombe, person, synth

from detective_board.extract.schema import Event, Extraction
from detective_board.graph import GraphStore, migrate
from detective_board.graph.schema import LATEST, schema_version


def _dump(store: GraphStore):
    q = store.conn.execute
    nodes = [
        tuple(r)
        for r in q(
            "SELECT id,kind,story,name,norm_name,unnamed,props_json,confidence,conf_reason,quote FROM g_node ORDER BY id"
        )
    ]
    edges = sorted(
        tuple(r)
        for r in q(
            "SELECT src,dst,rel,props_json,confidence,chunk_id,rel_start,rel_end,quote FROM g_edge"
        )
    )
    ments = sorted(
        tuple(r)
        for r in q("SELECT node_id,chunk_id,surface,role,rel_start,quote,ambiguous FROM g_mention")
    )
    return nodes, edges, ments


def test_migrations(tmp_path):
    p = str(tmp_path / "g.sqlite")
    s = GraphStore(p)
    assert schema_version(s.conn) == LATEST
    assert migrate(s.conn) == LATEST
    s.close()
    assert GraphStore(p).stats()["edges"] == 0
    c = sqlite3.connect(p)
    c.execute(f"PRAGMA user_version = {LATEST + 1}")
    c.commit()
    c.close()
    with pytest.raises(RuntimeError):
        GraphStore(p)


def test_dedup_and_alias_resolution(bv):
    p = f"p:{STORY}:"
    ids = {
        r["id"] for r in bv.conn.execute("SELECT id FROM g_node WHERE kind IN ('person','place')")
    }
    assert ids == {
        p + "charles-mccarthy", p + "john-turner", p + "william-crowder", p + "patience-moran",
        p + "james-mccarthy", p + "the-deceased",
        f"pl:{STORY}:hatherley", f"pl:{STORY}:boscombe-pool",
    }  # fmt: skip
    # "Mr. McCarthy" resolved via the alias "McCarthy"; "The Boscombe Pool" via the article-less key
    charles = bv.get_node(p + "charles-mccarthy")
    assert charles.aliases == ["McCarthy"]  # "Mr. McCarthy" folded into it by title stripping
    assert charles.anchor_total >= 2
    hath = bv.get_node(f"pl:{STORY}:hatherley")
    assert (hath.name, hath.aliases) == ("Hatherley Farm", ["Hatherley"])  # merged by alias
    james = bv.get_node(p + "james-mccarthy")
    assert james.anchor_total == 2 and james.confidence == "high"


def test_unnamed_person_story_scoped(bv):
    d = bv.get_node(f"p:{STORY}:the-deceased")
    assert d.confidence == "low"
    row = bv.conn.execute("SELECT unnamed, conf_reason FROM g_node WHERE id=?", (d.id,)).fetchone()
    assert (row["unnamed"], row["conf_reason"]) == (1, "unnamed")
    # a named entity listing it as alias does not absorb it, and other stories stay apart
    t1 = "Charles was found. The deceased lay still. The deceased was cold."
    bv.ingest(
        synth("syn-0", t1, STORY),
        Extraction(
            entities=[
                person("Charles", "Charles was found", ["the deceased"]),
                person("the deceased", "The deceased lay still"),
            ]
        ),
    )
    bv.ingest(
        synth("oth-0", t1, "other"),
        Extraction(entities=[person("the deceased", "The deceased lay still")]),
    )
    ids = [
        r["id"]
        for r in bv.conn.execute("SELECT id FROM g_node WHERE norm_name='the deceased' ORDER BY id")
    ]
    assert ids == [f"p:{STORY}:the-deceased", "p:other:the-deceased"]
    assert bv.resolve("Charles", story=STORY)  # named node exists separately


def test_alias_only_overlap_does_not_merge():
    s = GraphStore()
    t = "Sherlock Holmes spoke. Mycroft Holmes listened. Holmes nodded."
    s.ingest(
        synth("a-0", t),
        Extraction(
            entities=[
                person("Sherlock Holmes", "Sherlock Holmes spoke", ["Holmes"]),
                person("Mycroft Holmes", "Mycroft Holmes listened", ["Holmes"]),
            ]
        ),
    )
    assert len(s.resolve("Sherlock Holmes")) == 1 and len(s.resolve("Mycroft Holmes")) == 1
    assert len(s.resolve("Holmes")) == 2  # ambiguous alias
    rep = s.ingest(synth("a-1", t), Extraction(entities=[person("Holmes", "Holmes nodded")]))
    assert any("ambiguous" in w for w in rep.warnings)
    n = s.get_node("p:syn:holmes")
    assert n.confidence == "low" and n.props["ambiguous_resolution"]
    # an event naming the ambiguous alias does not pick a side
    rep = s.ingest(
        synth("a-2", t),
        Extraction(
            events=[
                Event(
                    description="x", participants=["Sherlock Holmes"], quote="Sherlock Holmes spoke"
                )
            ]
        ),
    )
    assert rep.events == 1


def test_ambiguous_missing_and_ws_anchors():
    s = GraphStore()
    t = "Smith came in.  Smith sat\n down. Jones left."
    rep = s.ingest(
        synth("x-0", t),
        Extraction(
            entities=[
                person("Smith", "Smith"),
                person("Jones", "Jones left."),
                person("Ghost", "Ghost appeared"),
            ],
            events=[
                Event(description="Smith sat", participants=["Smith"], quote="Smith sat down.")
            ],
        ),
    )
    assert rep.ambiguous_anchors == 1
    assert [(d.item_kind, d.reason) for d in rep.dropped] == [("entity", "quote_not_found")]
    assert s.conn.execute("SELECT COUNT(*) FROM g_dropped").fetchone()[0] == 1
    smith = s.get_node("p:syn:smith")
    assert smith.confidence == "low"  # its only mention is ambiguous
    ev = s.conn.execute("SELECT quote, ambiguous FROM g_node WHERE kind='event'").fetchone()
    assert ev["quote"] == "Smith sat\n down." and ev["ambiguous"] == 0  # whitespace-normalised
    assert s.get_node("p:syn:jones").confidence == "high"


def test_idempotent_reingest(bv, chunks):
    before = _dump(bv)
    exs = boscombe_extractions()
    reps = bv.ingest_many([(chunks[c], exs[c]) for c in (C2, C3, C7)])
    assert {r.status for r in reps} == {"unchanged"}
    assert _dump(bv) == before
    assert bv.ingest(chunks[C2], exs[C2], force=True).status == "replaced"
    assert _dump(bv) == before  # forced rebuild gives the same graph


def test_changed_extraction_replaces_chunk(chunks):
    exs = boscombe_extractions()
    a = build_boscombe(chunks)
    changed = exs[C3].model_copy(update={"events": []})
    assert a.ingest(chunks[C3], changed).status == "replaced"
    fresh = GraphStore()
    fresh.ingest_many([(chunks[C7], exs[C7]), (chunks[C2], exs[C2]), (chunks[C3], changed)])
    assert _dump(a) == _dump(fresh)
    assert a.stats().get("event") == 1


def test_anchor_invariants(bv, chunks):
    clean = (
        __import__("pathlib").Path(__file__).resolve().parents[2] / "data/clean" / f"{STORY}.txt"
    ).read_text()
    rows = [*bv.conn.execute("SELECT chunk_id, rel_start, rel_end, char_start, char_end, quote FROM g_edge"),
            *bv.conn.execute("SELECT chunk_id, rel_start, rel_end, char_start, char_end, quote FROM g_mention"),
            *bv.conn.execute("SELECT chunk_id, rel_start, rel_end, char_start, char_end, quote FROM g_node WHERE chunk_id IS NOT NULL")]  # fmt: skip
    assert len(rows) > 20
    for r in rows:
        c = chunks[r["chunk_id"]]
        assert c.text[r["rel_start"] : r["rel_end"]] == r["quote"]
        assert clean[r["char_start"] : r["char_end"]] == r["quote"]


def test_non_contiguous_chunk_uses_relative_anchors_and_low_confidence():
    s = GraphStore()
    t = "Watson wrote it."
    c = synth("n-0", t)
    c = type(c)(c.chunk_id, c.story, c.char_start, c.char_end, c.text, contiguous=False)
    s.ingest(c, Extraction(entities=[person("Watson", "Watson wrote")]))
    n = s.get_node("p:syn:watson")
    a = n.anchors[0]
    assert (a.char_start, a.rel_start, a.ambiguous) == (0, 0, True)
    assert n.confidence == "low"
