"""Curated presence facts for the demo cases (docs/symbolic-layer.md 11.4).

The facts are human-checked (AI-assisted); these tests prove the loader and what the rules do with
the facts, not that any model produces them.
"""

import json
from pathlib import Path

import pytest

from detective_board.agent.rule_first import ToolOutcome, build_answer, coverage_for
from detective_board.agent.rules_client import InProcessRulesClient
from detective_board.extract import curated, normalise
from detective_board.extract.curated_schema import (
    CURATED_MARK,
    CURATED_REVIEW,
    CuratedFact,
    curated_day,
)
from detective_board.extract.schema import Entity, Extraction
from detective_board.graph import ChunkRef, GraphStore, SqliteFactSource
from detective_board.mcp import tools as mcp_tools

ROOT = Path(__file__).resolve().parents[2]
FACTS = ROOT / curated.DEFAULT_FILE
WL, BV, AG = "wisteria-lodge", "boscombe-valley-mystery", "abbey-grange"
GARCIA_Q = (
    "Is there a conflict about where Aloysius Garcia was at about one o'clock on the night he died?"
)


@pytest.fixture(scope="module")
def facts() -> list[CuratedFact]:
    if not FACTS.exists():
        pytest.skip("curated facts not available")
    return curated.load_file(FACTS)


@pytest.fixture(scope="module")
def clean() -> dict[str, str]:
    out = {}
    for story in (WL, BV, AG):
        p = ROOT / "data" / "clean" / f"{story}.txt"
        if not p.exists():
            pytest.skip("data/clean not available")
        out[story] = p.read_text(encoding="utf-8")
    return out


@pytest.fixture(scope="module")
def chunks(facts) -> list[ChunkRef]:
    p = ROOT / "data" / "chunks.jsonl"
    if not p.exists():
        pytest.skip("data/chunks.jsonl not available")
    return curated.load_chunks(p, {f.story for f in facts}, ROOT / "data" / "clean")


@pytest.fixture
def graph(tmp_path, facts, chunks, clean):
    g = GraphStore(str(tmp_path / "graph.sqlite"))
    curated.ingest_facts(g, facts, chunks, clean)
    yield g
    g.close()


def findings(g, story, **kw):
    return mcp_tools.find_contradictions(SqliteFactSource(g), story=story, **kw)["findings"]


# ---- the data file -----------------------------------------------------------------------
def test_file_has_the_demo_cases_and_every_fact_is_labelled(facts):
    ids = {f.id for f in facts}
    assert len(ids) == len(facts) >= 7
    assert {f.story for f in facts} == {WL, BV, AG}
    assert all(f.curated_by == "team (AI-assisted, to be re-checked by a human)" for f in facts)
    assert all(f.note.strip() and (f.day_key or f.time_ref) for f in facts)
    assert {"c001-eccles-garcia-bedroom", "c001-baynes-garcia-common"} <= ids


def test_quotes_are_verbatim_in_the_clean_text_and_slots_are_honest(facts, clean):
    for f in facts:
        assert curated.problems(f, clean[f.story]) == [], f.id
        assert curated.locate_quote(clean[f.story], f.quote) is not None


def test_quote_check_ignores_whitespace_and_quote_marks_but_nothing_else(facts, clean):
    f = facts[0]
    text = clean[f.story]
    assert curated.locate_quote(text, f.quote.replace("’", "'").replace(" ", "\n")) is not None
    assert curated.locate_quote(text, f.quote + " and then he left") is None
    bad = f.model_copy(update={"quote": f.quote.replace("Garcia", "Baynes")})
    assert curated.problems(bad, text) == [
        f"{f.id}: quote is not a verbatim span of the story text"
    ]


def test_a_slot_missing_from_the_quote_must_be_declared_inferred(facts, clean):
    f = next(x for x in facts if x.id == "c001-baynes-garcia-common")
    undeclared = f.model_copy(update={"inferred": []})
    msgs = curated.problems(undeclared, clean[f.story])
    assert any("person" in m for m in msgs) and any("place" in m for m in msgs)


def test_c001_pronoun_facts_are_marked_inferred_and_low(facts):
    by = {f.id: f for f in facts}
    assert by["c001-baynes-garcia-common"].inferred == ["person", "place"]
    assert by["c001-eccles-garcia-bedroom"].inferred == ["place"]
    assert all(by[i].confidence == "low" for i in ("c001-baynes-garcia-common",))


def test_day_keys_are_shared_and_stable():
    assert curated_day(WL, "night-of-the-murder") == curated_day(WL, "night-of-the-murder")
    assert curated_day(WL, "night-of-the-murder") != curated_day(WL, "the-day-after")
    assert 20_000 <= curated_day(WL, "x") < 30_000


# ---- loader round trip --------------------------------------------------------------------
def test_round_trip_events_claims_overlays_and_the_curated_mark(graph, facts):
    q = graph.conn.execute
    ev = q("SELECT * FROM g_node WHERE kind='event' ORDER BY id").fetchall()
    cl = q("SELECT * FROM g_node WHERE kind='claim' ORDER BY id").fetchall()
    assert len(ev) == len(cl) == len(facts)  # every curated fact is a speech fact here
    for r in ev + cl:
        p = json.loads(r["props_json"])
        assert p["curated"] is True and p["pass"] == "curated" and p["note"]
        assert p["curated_by"].startswith("team (AI-assisted")
    garcia = graph.resolve("Aloysius Garcia", story=WL, kinds=("person",))
    assert len(garcia) == 1
    parts = [
        r[0] for r in q("SELECT dst FROM g_edge WHERE src=? AND rel='PARTICIPATED_IN'", garcia)
    ]
    assert len(parts) == 2
    places = {
        r["name"]
        for r in q(
            "SELECT p.name FROM g_edge e JOIN g_node p ON p.id=e.dst WHERE e.rel='OCCURRED_AT'"
            " AND e.src IN (?,?)",
            parts,
        )
    }
    assert places == {"Wisteria Lodge", "Oxshott Common"}
    ov = {
        (r["node_id"], r["key"]): r
        for r in q("SELECT * FROM g_overlay WHERE source='curated'").fetchall()
    }
    days = {k[0]: json.loads(v["value_json"]) for k, v in ov.items() if k[1] == "story_day"}
    assert days[parts[0]] == days[parts[1]] == curated_day(WL, "night-of-the-murder")
    t = json.loads(ov[(parts[0], "time")]["value_json"])
    assert t["day"] == days[parts[0]] and t["confidence"] == "low"  # 'nearly one o'clock'
    props = [k for k in ov if k[1] == "prop"]
    assert len(props) == len(facts)  # every claim has a presence proposition


def test_event_confidence_follows_inference_and_the_normaliser(graph):
    fb = SqliteFactSource(graph).load(WL)
    assert all(e.curated and e.confidence == "low" for e in fb.events)  # inferred slots
    assert all(c.curated for c in fb.claims)
    # an explicit, exact clock time without inference is HIGH
    g = GraphStore()
    text = "Ann Hale was at the Rose Inn at nine o'clock on Monday evening."
    c = ChunkRef("syn-0001", "syn", 0, len(text), text)
    f = CuratedFact(
        id="exact",
        story="syn",
        person="Ann Hale",
        place="Rose Inn",
        time_text="nine o'clock",
        day_key="monday",
        source="narrator",
        quote=text,
        curated_by="test",
        note="explicit",
    )
    g.ingest_curated(c, [f])
    (e,) = SqliteFactSource(g).load("syn").events
    assert e.confidence == "high" and e.time and e.time.confidence == "high" and e.time.exact
    assert e.narrator is True and e.curated is True
    approx = f.model_copy(update={"id": "approx", "time_text": "about nine o'clock", "quote": text})
    approx = approx.model_copy(update={"quote": text.replace("at nine", "at about nine")})
    c2 = ChunkRef("syn-0002", "syn", 0, len(approx.quote), approx.quote)
    g.ingest_curated(c2, [approx])
    ev = {e.id: e for e in SqliteFactSource(g).load("syn").events}
    assert ev["e:syn-0002:cur-approx"].time.confidence == "low"  # approximate stays LOW


def test_loading_twice_is_idempotent(graph, facts, chunks, clean):
    snap = [tuple(r)[1:] for r in graph.conn.execute("SELECT * FROM g_edge ORDER BY src,dst,rel")]
    nodes = [tuple(r) for r in graph.conn.execute("SELECT * FROM g_node ORDER BY id")]
    ov = [tuple(r) for r in graph.conn.execute("SELECT * FROM g_overlay ORDER BY node_id,key")]
    rep = curated.ingest_facts(graph, facts, chunks, clean)
    assert (rep.loaded, rep.unchanged) == (0, len(facts))
    assert snap == [
        tuple(r)[1:] for r in graph.conn.execute("SELECT * FROM g_edge ORDER BY src,dst,rel")
    ]
    assert nodes == [tuple(r) for r in graph.conn.execute("SELECT * FROM g_node ORDER BY id")]
    assert ov == [
        tuple(r) for r in graph.conn.execute("SELECT * FROM g_overlay ORDER BY node_id,key")
    ]
    # a forced reload replaces without leftovers
    by_chunk = {c.chunk_id: c for c in chunks}
    for f in facts:
        chunk = by_chunk[rep.by_fact[f.id]]
        span = curated.locate_quote(chunk.text, f.quote)
        assert span is not None
        exact = chunk.text[span[0] : span[1]]
        graph.ingest_curated(chunk, [f.model_copy(update={"quote": exact})], force=True)
    assert nodes == [tuple(r) for r in graph.conn.execute("SELECT * FROM g_node ORDER BY id")]


def test_a_bad_fact_loads_nothing_and_names_every_problem(tmp_path, facts, chunks, clean):
    g = GraphStore(str(tmp_path / "g.sqlite"))
    bad = facts[0].model_copy(update={"id": "bad1", "quote": "He never said any of this."})
    bad2 = facts[1].model_copy(update={"id": "bad2", "time_text": "at dawn"})
    with pytest.raises(ValueError, match="bad1.*\n.*bad2"):
        curated.ingest_facts(g, [facts[2], bad, bad2], chunks, clean)
    assert g.stats() == {"chunks": 0, "edges": 0}


def test_cli_loads_a_graph_file_and_reports(tmp_path, capsys):
    db = tmp_path / "graph.sqlite"
    args = ["--graph-db", str(db), "--file", str(FACTS)]
    args += ["--chunks", str(ROOT / "data/chunks.jsonl"), "--clean-dir", str(ROOT / "data/clean")]
    assert curated.main(args) == 0
    assert "8 loaded, 0 unchanged" in capsys.readouterr().out
    assert curated.main(args) == 0
    assert "0 loaded, 8 unchanged" in capsys.readouterr().out


# ---- the rules on curated facts --------------------------------------------------------------
def test_c001_gives_an_r1_finding_with_both_verbatim_quotes_and_is_conditional(graph, facts, clean):
    (f,) = [x for x in findings(graph, WL) if x["rule"] == "R1"]
    assert f["reason_code"] == "OVERLAP_DIFFERENT_PLACES"
    # derived, but conditional: 'nearly one o'clock', 'since one o'clock' and the inferred slots are low
    assert f["provenance"] == "conditional"
    quotes = {a["quote"] for a in f["anchors"]}
    by = {x.id: x for x in facts}
    for fid in ("c001-eccles-garcia-bedroom", "c001-baynes-garcia-common"):
        assert " ".join(by[fid].quote.split()) in {" ".join(q.split()) for q in quotes}
        assert curated.locate_quote(clean[WL], by[fid].quote) is not None
    exp = f["explanation"]
    assert all(x["curated"] for x in exp["facts"])
    assert all(CURATED_MARK in x["summary"] for x in exp["facts"])
    assert exp["conditional"] and len(exp["weak"]) == 2


@pytest.mark.parametrize("drop", ["c001-eccles-garcia-bedroom", "c001-baynes-garcia-common"])
def test_c001_needs_both_sides(tmp_path, facts, chunks, clean, drop):
    g = GraphStore(str(tmp_path / "g.sqlite"))
    curated.ingest_facts(g, [f for f in facts if f.id != drop], chunks, clean)
    assert [x for x in findings(g, WL) if x["rule"] == "R1"] == []


def test_c042_control_has_no_violation_and_pairs_are_decided_as_consistent(graph):
    assert findings(graph, BV) == []
    fb = SqliteFactSource(graph).load(BV)
    assert len(fb.events) == 3
    from detective_board.symbolic.api import scan_presence_conflicts

    rep = scan_presence_conflicts(fb, include_consistent=True)
    assert rep.stats["violated"] == 0 and rep.stats["pairs_examined"] == 3
    assert {f.reason_code for f in rep.findings} == {"TIME_DISJOINT", "PLACE_COMPATIBLE"}


# ---- survival --------------------------------------------------------------------------------
def test_curated_nodes_survive_generic_and_presence_reingest(tmp_path, facts, chunks, clean):
    g = GraphStore(str(tmp_path / "g.sqlite"))
    wl = [c for c in chunks if c.story == WL]
    ex = Extraction(
        entities=[Entity(name="Garcia", type="person", quote="Garcia looked in at my door")]
    )
    target = next(c for c in wl if "Garcia looked in at my door" in c.text)
    g.ingest(target, ex)
    curated.ingest_facts(g, facts, chunks, clean)
    before = findings(g, WL)
    assert len(before) == 1
    n_curated = g.conn.execute(
        "SELECT COUNT(*) FROM g_node WHERE props_json LIKE '%\"curated\":true%'"
    ).fetchone()[0]
    assert n_curated == 2 * len(facts)
    # a generic re-ingest of the chunk with another extraction purges generic nodes only
    ex2 = Extraction(entities=[Entity(name="Garcia", type="person", quote="Garcia")])
    assert g.ingest(target, ex2, force=True).status == "replaced"
    # and so does a presence re-ingest (an empty result clears the chunk's presence nodes)
    assert g.ingest_presence(target, [], force=True).status in {"inserted", "replaced"}
    after = g.conn.execute(
        "SELECT COUNT(*) FROM g_node WHERE props_json LIKE '%\"curated\":true%'"
    ).fetchone()[0]
    assert after == n_curated
    assert findings(g, WL) == before
    # re-normalising keeps the curated overlays (they win)
    normalise.apply(g, WL)
    assert findings(g, WL) == before
    assert g.conn.execute("SELECT COUNT(*) FROM g_overlay WHERE source='curated'").fetchone()[0] > 0
    # the loader still reports everything as unchanged afterwards
    rep = curated.ingest_facts(g, facts, chunks, clean)
    assert rep.unchanged == len(facts)


# ---- the rule-first answer ----------------------------------------------------------------------
def test_rule_first_answer_for_the_garcia_question_says_curated(graph):
    tools = InProcessRulesClient(graph)
    payload = tools.call("find_contradictions", {"story": WL}, timeout=1)
    ans = build_answer(
        question=GARCIA_Q,
        story=WL,
        outcomes=[ToolOutcome("find_contradictions", payload)],
        link=None,
        notes=[],
        hits=[],
        coverage=coverage_for(tools, graph, WL),
    )
    assert ans.kind == "findings"
    text = ans.text
    assert text.count("(curated)") >= 2 and "Curated: 2 of the facts" in text
    assert "label conditional" in text and CURATED_REVIEW in text
    assert 'nearly one o’clock."' in text and "He had been there since one o’clock." in text
    assert "no conflict" not in text.lower()


def test_without_curated_facts_the_answer_does_not_mention_them():
    from tests.agent.test_graph_route import _graph

    g = _graph()
    payload = InProcessRulesClient(g).call("find_contradictions", {"story": "wl"}, timeout=1)
    ans = build_answer(
        question=GARCIA_Q,
        story="wl",
        outcomes=[ToolOutcome("find_contradictions", payload)],
        link=None,
        notes=[],
        hits=[],
        coverage=None,
    )
    assert "curated" not in ans.text.lower()


# ---- human day labels in user-visible text ------------------------------------------------------
def test_answer_shows_the_day_key_not_a_synthetic_day_id(graph):
    import re

    tools = InProcessRulesClient(graph)
    payload = tools.call("find_contradictions", {"story": WL}, timeout=1)
    text = build_answer(
        question=GARCIA_Q,
        story=WL,
        outcomes=[ToolOutcome("find_contradictions", payload)],
        link=None,
        notes=[],
        hits=[],
        coverage=None,
    ).text
    assert "same day: night of the murder, 01:00" in text
    assert not re.search(r"\bd\d+\b", text)
    # the machine ids in the explanation are unchanged
    (f,) = payload["findings"]
    assert all(x["fact_id"].startswith("e:wisteria-lodge-") for x in f["explanation"]["facts"])
    fb = SqliteFactSource(graph).load(WL)
    assert {e.time.day for e in fb.events} == {curated_day(WL, "night-of-the-murder")}


def test_human_time_labels_for_automatic_and_assumed_days():
    from detective_board.symbolic.model import TimeSpec
    from detective_board.symbolic.time import fmt_human

    t = TimeSpec(lo=60, hi=60, exact=True)
    assert fmt_human(t) == "01:00, day unknown"
    assert fmt_human(t.model_copy(update={"day": 3}), "day 3 (assumed)") == "day 3 (assumed), 01:00"
    assert fmt_human(t.model_copy(update={"day": 10001})) == "01:00, day set from the text"
    assert fmt_human(TimeSpec(lo=360, hi=720)) == "06:00-12:00 (fuzzy), day unknown"


def test_assumed_day_is_labelled_and_automatic_days_are_not(tmp_path):
    g = GraphStore()
    text = "Ann Hale was at the Rose Inn at nine o'clock."
    g.ingest(
        ChunkRef("syn-0001", "syn", 0, len(text), text),
        Extraction(
            entities=[Entity(name="Ann Hale", type="person", quote="Ann Hale")],
        ),
    )
    c = ChunkRef("syn-0001", "syn", 0, len(text), text)
    from detective_board.extract.presence_schema import GroundedFact

    g.ingest_presence(
        c,
        [
            GroundedFact(
                person="Ann Hale", place="Rose Inn", time_text="nine o'clock", quote=text[:-1]
            )
        ],
    )
    (plain,) = SqliteFactSource(g).load("syn").events
    (assumed,) = SqliteFactSource(g, assume_day=5).load("syn").events
    assert plain.day_label is None and assumed.day_label == "day 5 (assumed)"


# ---- relative time: c002 Abbey Grange (docs/symbolic-layer.md 11.4) ------------------------------
C002 = ("c002-lady-chair-at-entry", "c002-crocker-window-at-entry")
MOMENT_Q = "Where was Lady Brackenstall when Sir Eustace entered the dining-room?"


def _base(**kw):
    d = dict(
        id="x1", story=AG, person="Lady Brackenstall", place="window", time_text=None,
        source="speech", speaker="Captain Crocker", quote="q", curated_by="team", note="n",
    )  # fmt: skip
    return d | kw


def test_schema_accepts_time_ref_with_or_without_day_key():
    f = CuratedFact(**_base(time_ref="sir-eustace-entered", time_ref_text="q"))
    assert f.time_ref == "sir-eustace-entered" and f.time_text is None
    CuratedFact(**_base(time_ref="sir-eustace-entered", day_key="the-night"))


def test_schema_rejects_day_key_without_time_text_and_without_time_ref():
    with pytest.raises(ValueError, match="day_key without time_text or time_ref"):
        CuratedFact(**_base(day_key="the-night"))


@pytest.mark.parametrize(
    "extra, msg",
    [
        ({"time_ref": "a", "time_text": "at nine"}, "exclusive"),
        ({"time_ref_text": "when he came"}, "without time_ref"),
        ({"time_ref": "Not A Slug"}, "kebab-case"),
    ],
)
def test_schema_rejects_inconsistent_time_ref_fields(extra, msg):
    with pytest.raises(ValueError, match=msg):
        CuratedFact(**_base(**extra))


def test_c002_facts_are_in_the_file_and_honest(facts, clean):
    by = {f.id: f for f in facts}
    assert set(C002) <= set(by)
    for fid in C002:
        f = by[fid]
        assert curated.problems(f, clean[AG]) == []
        assert f.time_ref == "sir-eustace-entered" and f.time_text is None
        assert f.time_ref_text and f.confidence == "low" and "person" in f.inferred
    assert by[C002[0]].speaker == "Lady Brackenstall" and by[C002[1]].speaker == "Captain Crocker"


def test_time_ref_text_must_be_in_the_quote_or_time_declared_inferred(facts, clean):
    f = next(x for x in facts if x.id == C002[0])
    off = f.model_copy(update={"time_ref_text": "at midnight"})
    assert any("time_ref_text" in m for m in curated.problems(off, clean[AG]))
    none = f.model_copy(update={"time_ref_text": None})
    assert any("declare time inferred" in m for m in curated.problems(none, clean[AG]))
    ok = none.model_copy(update={"inferred": ["person", "time"]})
    assert curated.problems(ok, clean[AG]) == []
    both = f.model_copy(update={"inferred": ["person", "time"]})
    assert any("declared inferred" in m for m in curated.problems(both, clean[AG]))


def test_c002_gives_a_conditional_r1_finding_with_both_quotes(graph, facts):
    (f,) = [x for x in findings(graph, AG) if x["rule"] == "R1"]
    assert f["reason_code"] == "OVERLAP_DIFFERENT_PLACES" and f["provenance"] == "conditional"
    by = {x.id: x for x in facts}
    quotes = {" ".join(a["quote"].split()) for a in f["anchors"]}
    assert quotes == {" ".join(by[i].quote.split()) for i in C002}
    exp = f["explanation"]
    assert exp["conditional"] and len(exp["weak"]) == 2 and all(x["curated"] for x in exp["facts"])
    assert all(
        "relative time" in x["summary"] and CURATED_MARK in x["summary"] for x in exp["facts"]
    )
    assert (
        exp["derivation"][0]["output"]
        == "same moment: sir eustace entered (relative time, curated)"
    )
    assert [x for x in findings(graph, AG) if x["rule"] != "R1"] == []


def test_the_relative_facts_carry_no_clock_and_no_day(graph):
    fb = SqliteFactSource(graph).load(AG)
    evs = [e for e in fb.events if e.curated]
    assert len(evs) == 2
    for e in evs:
        t = e.time
        assert t is not None and (t.day, t.lo, t.hi) == (None, None, None)
        assert t.rel == "at" and t.confidence == "low" and e.eff_confidence == "low"
    assert not graph.conn.execute(
        "SELECT 1 FROM g_overlay WHERE source='curated' AND key='story_day' AND node_id LIKE ?",
        ("%c002%",),
    ).fetchone()


@pytest.mark.parametrize("drop", C002)
def test_c002_needs_both_sides(tmp_path, facts, chunks, clean, drop):
    g = GraphStore(str(tmp_path / "g.sqlite"))
    curated.ingest_facts(g, [f for f in facts if f.id != drop], chunks, clean)
    assert findings(g, AG) == []


def test_c002_other_stories_and_the_controls_are_unchanged(tmp_path, facts, chunks, clean):
    g = GraphStore(str(tmp_path / "g.sqlite"))
    old = [f for f in facts if f.id not in C002]
    curated.ingest_facts(g, old, chunks, clean)
    before = {s: findings(g, s) for s in (WL, BV)}
    curated.ingest_facts(g, facts, chunks, clean)
    assert {s: findings(g, s) for s in (WL, BV)} == before
    assert findings(g, BV) == [] and len(before[WL]) == 1


def test_loader_is_idempotent_for_relative_facts(graph, facts, chunks, clean):
    rows = [tuple(r) for r in graph.conn.execute("SELECT * FROM g_node ORDER BY id")]
    ov = [tuple(r) for r in graph.conn.execute("SELECT * FROM g_overlay ORDER BY node_id, key")]
    rep = curated.ingest_facts(graph, facts, chunks, clean)
    assert rep.unchanged == len(facts) and rep.loaded == 0
    assert rows == [tuple(r) for r in graph.conn.execute("SELECT * FROM g_node ORDER BY id")]
    assert ov == [
        tuple(r) for r in graph.conn.execute("SELECT * FROM g_overlay ORDER BY node_id, key")
    ]


def test_rule_first_answer_says_the_time_is_relative_and_curated(graph):
    tools = InProcessRulesClient(graph)
    payload = tools.call("find_contradictions", {"story": AG}, timeout=1)
    ans = build_answer(
        question=MOMENT_Q,
        story=AG,
        outcomes=[ToolOutcome("find_contradictions", payload)],
        link=None,
        notes=[],
        hits=[],
        coverage=coverage_for(tools, graph, AG),
    )
    text = ans.text
    assert ans.kind == "findings"
    assert "relative time" in text and text.count("(curated)") >= 2
    assert "label conditional" in text and CURATED_REVIEW in text
    assert "oaken chair" in text and "just inside the window" in text
    assert "no conflict" not in text.lower()
