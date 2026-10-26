"""Presence facts in the graph, the day heuristic, and two end-to-end runs with canned model output.

The canned outputs stand in for the model: they prove the plumbing (runner, grounding, ingest,
normaliser, rules, explanation), not that any model produces them. Quotes are verbatim chunks.
"""

import json

from detective_board.agent.rules_client import InProcessRulesClient
from detective_board.extract import normalise, presence
from detective_board.extract.presence import PROMPT_V1
from detective_board.extract.presence_schema import GroundedFact
from detective_board.extract.schema import Entity, Extraction
from detective_board.graph import ChunkRef, GraphStore, SqliteFactSource
from detective_board.symbolic.api import Verdict, run_all

from .helpers import BV, ROOT, WL, fact, fake_by_passage, write_chunks

QUOTE_MC = (
    "On June 3rd, that is, on Monday last, McCarthy left his house at Hatherley about three in "
    "the afternoon and walked down to the Boscombe Pool"
)
QUOTE_JAMES = (
    "Mr. James McCarthy, the only son of the deceased, was then called and gave evidence as "
    "follows: ‘I had been away from home for three days at Bristol, and had only just returned "
    "upon the morning of last Monday, the 3rd."
)
S1_QUOTE = "He apologised for having disturbed me so late, saying that it was nearly one o’clock."
S2_QUOTE = "He had been there since one o’clock."


def gf(**kw) -> GroundedFact:
    base = dict(person="Ann", place="the inn", time_text="nine o'clock", quote="Ann was at the inn")
    return GroundedFact(**{**base, **kw})


def synth(text="Ann was at the inn at nine o'clock. Bob was not.", story="syn") -> ChunkRef:
    return ChunkRef(
        chunk_id=f"{story}-0001", story=story, char_start=0, char_end=len(text), text=text
    )


def nodes(g: GraphStore, kind: str) -> list[str]:
    return [r[0] for r in g.conn.execute("SELECT id FROM g_node WHERE kind=? ORDER BY id", (kind,))]


# --- ingest


def test_narrator_fact_is_an_event_with_person_place_and_own_time():
    g, c = GraphStore(), synth()
    rep = g.ingest_presence(
        c, [gf(quote="Ann was at the inn at nine o'clock", day_text="that night")]
    )
    assert (rep.status, rep.events, rep.claims) == ("inserted", 1, 0)
    (ev,) = g.conn.execute("SELECT * FROM g_node WHERE kind='event'").fetchall()
    p = json.loads(ev["props_json"])
    assert p["narrator"] is True and p["time_text"] == "nine o'clock" and p["pass"] == "presence"
    assert p["time_norm"]["exact"] is True and (p["time_norm"]["lo"], p["time_norm"]["hi"]) == (
        540,
        540,
    )
    assert ev["confidence"] == "high" and ev["quote"] == "Ann was at the inn at nine o'clock"
    rels = {(r["rel"], r["src"][:2], r["dst"][:2]) for r in g.conn.execute("SELECT * FROM g_edge")}
    assert rels == {("PARTICIPATED_IN", "p:", "e:"), ("OCCURRED_AT", "e:", "pl")}
    assert g.events_by_person("Ann").nodes[1].props["time_text"] == "nine o'clock"


def test_speech_fact_adds_a_claim_and_denial_is_a_claim_only():
    g, c = GraphStore(), synth()
    say = gf(source="speech", speaker="Bob", quote="Ann was at the inn")
    deny = gf(source="speech", speaker="Bob", polarity="deny", quote="Bob was not")
    rep = g.ingest_presence(c, [say, deny])
    assert (rep.events, rep.claims) == (1, 2)
    ev = json.loads(
        g.conn.execute("SELECT props_json FROM g_node WHERE kind='event'").fetchone()[0]
    )
    assert ev["narrator"] is False
    claims = {
        r["id"]: json.loads(r["props_json"])
        for r in g.conn.execute("SELECT * FROM g_node WHERE kind='claim'")
    }
    assert claims["c:syn-0001:p1"]["polarity"] == "deny"
    assert (
        claims["c:syn-0001:p0"]["about_place"] == "the inn"
        and claims["c:syn-0001:p0"]["speaker"] == "Bob"
    )
    assert g.claims_by_speaker("Bob").nodes[0].kind == "person"
    rep = g.ingest_presence(c, [gf(polarity="deny", quote="Bob was not")])  # narrator denial
    assert [d.reason for d in rep.dropped] == ["denial_without_speaker"] and rep.events == 0


def test_reingest_is_idempotent_and_replaces_without_leftovers():
    g, c = GraphStore(), synth()
    facts = [gf(quote="Ann was at the inn")]
    g.ingest_presence(c, facts)
    snap = [tuple(r) for r in g.conn.execute("SELECT * FROM g_node ORDER BY id")]
    assert g.ingest_presence(c, facts).status == "unchanged"
    assert g.ingest_presence(c, facts, force=True).status == "replaced"
    assert snap == [tuple(r) for r in g.conn.execute("SELECT * FROM g_node ORDER BY id")]
    assert g.ingest_presence(c, []).status == "replaced"  # an empty result clears the chunk
    assert g.stats() == {"chunks": 1, "edges": 0}


def test_generic_ingest_is_untouched_and_a_generic_reingest_purges_presence():
    g, c = GraphStore(), synth()
    ex = Extraction(entities=[Entity(name="Ann", type="person", quote="Ann was at the inn")])
    g.ingest(c, ex)
    g.ingest_presence(c, [gf(quote="Ann was at the inn")])
    assert g.stats()["event"] == 1 and len(g.resolve("Ann")) == 1  # joined the generic Ann
    assert g.ingest(c, ex).status == "unchanged"
    assert g.stats()["event"] == 1
    g.ingest(c, Extraction(entities=[Entity(name="Ann", type="person", quote="Ann")]), force=True)
    assert "event" not in g.stats()
    assert g.ingest_presence(c, [gf(quote="Ann was at the inn")]).status == "inserted"


def test_surname_match_joins_an_existing_person_but_ambiguity_is_not_guessed():
    g, c = GraphStore(), synth("Ann Smith and Jo Smith met Mr. Smith at the inn at nine o'clock.")
    ex = Extraction(
        entities=[
            Entity(name="Ann Smith", type="person", quote="Ann Smith"),
            Entity(name="Jo Smith", type="person", quote="Jo Smith"),
        ]
    )
    g.ingest(c, ex)
    q = "Mr. Smith at the inn at nine o'clock"
    rep = g.ingest_presence(c, [gf(person="Smith", quote=q)])
    assert rep.events == 0 and rep.dropped[0].reason == "person_unresolved"
    g2 = GraphStore()
    g2.ingest(c, Extraction(entities=[Entity(name="Ann Smith", type="person", quote="Ann Smith")]))
    assert g2.ingest_presence(c, [gf(person="Smith", quote=q)]).events == 1
    assert g2.stats()["person"] == 1  # no second Smith
    ev = g2.conn.execute("SELECT confidence, conf_reason FROM g_node WHERE kind='event'").fetchone()
    assert tuple(ev) == ("low", "weak_reference")  # a surname match is a guess: LOW


def test_context_and_motion_make_the_event_low_and_time_not_exact():
    g, c = GraphStore(), synth()
    g.ingest_presence(c, [gf(quote="Ann was at the inn", context=["place", "time_text"])])
    ev = g.conn.execute("SELECT * FROM g_node WHERE kind='event'").fetchone()
    p = json.loads(ev["props_json"])
    assert (ev["confidence"], ev["conf_reason"]) == ("low", "inherited_context")
    assert p["time_text"] is None and p["time_text_inherited"] == "nine o'clock"
    assert p["time_norm"]["exact"] is False
    g2 = GraphStore()
    g2.ingest_presence(
        synth("Ann went to the inn at nine o'clock."), [gf(quote="Ann went to the inn")]
    )
    ev = g2.conn.execute("SELECT confidence, conf_reason FROM g_node WHERE kind='event'").fetchone()
    assert tuple(ev) == ("low", "transit_cue")


# --- day heuristic


def test_same_day_text_gives_the_same_low_day_and_explicit_dates_and_curation_win():
    g = GraphStore()
    text = "A at X at ten. B at Y at ten. C at Z at ten on Monday, June 3rd. D at W at ten."
    c = synth(text)
    facts = [
        gf(person="A", place="X", time_text="ten", day_text="That night", quote="A at X at ten"),
        gf(
            person="B",
            place="Y",
            time_text="ten",
            day_text="that very night",
            quote="B at Y at ten",
        ),
        gf(
            person="C",
            place="Z",
            time_text="ten",
            day_text="Monday, June 3rd",
            quote="C at Z at ten on Monday, June 3rd",
        ),
        gf(
            person="D", place="W", time_text="ten", day_text="the next night", quote="D at W at ten"
        ),
    ]
    g.ingest_presence(c, facts)
    g.set_event_day("e:syn-0001:p3", 77, confidence="high")  # curated
    normalise.apply(g, "syn")
    days = {
        r["node_id"][-2:]: (json.loads(r["value_json"]), r["confidence"], r["source"])
        for r in g.conn.execute("SELECT * FROM g_overlay WHERE key='story_day'")
    }
    assert days["p0"] == days["p1"] == (normalise.TEXT_DAY_BASE, "low", "normaliser")
    assert days["p2"][1] == "high" and days["p2"][0] > 700_000  # an explicit date stays a date
    assert days["p3"] == (77, "high", "manual")
    fb = SqliteFactSource(g).load("syn")
    d0 = fb.event("e:syn-0001:p0").time
    assert (d0.day, d0.confidence) == (normalise.TEXT_DAY_BASE, "low")


def test_day_key_and_assignment():
    assert normalise.day_key("On that very night.") == normalise.day_key("that night")
    assert normalise.day_key("that night") != normalise.day_key("the night")
    assert normalise.day_key("   ") == ""
    again = normalise.assign_text_days({}, {}, {})
    assert again == {}


# --- end to end


def test_wisteria_c001_with_canned_context_resolved_facts_is_a_conditional_r1_finding(tmp_path):
    """Gold c001. Neither sentence names person, place and time (see the strict test in
    test_presence_extract.py), so the canned model answer here relies on --lenient: the context
    fields are LOW. What this proves: runner, grounding, ingest, normaliser day heuristic, R1 and
    the explanation work together. What it does not: that any model finds these facts."""
    chunks = write_chunks(tmp_path / "chunks.jsonl", f"{WL}-0006", f"{WL}-0010")
    client = fake_by_passage(
        {
            "Some time later Garcia looked in": [
                fact(person="Garcia", place="Wisteria Lodge", time_text="nearly one o’clock",
                     day_text="that night", source="speech", speaker="Scott Eccles", quote=S1_QUOTE)
            ],
            "He had been there since one o’clock": [
                fact(person="Garcia", place="Oxshott Common", time_text="since one o’clock",
                     day_text="that night", source="speech", speaker="Inspector Baynes",
                     quote=S2_QUOTE)
            ],
        }
    )  # fmt: skip
    db = tmp_path / "g.sqlite"
    args = ["--model", "fake", "--chunks", str(chunks), "--cache", str(tmp_path / "c.sqlite"),
            "--graph-db", str(db), "--prompt", str(PROMPT_V1)]  # fmt: skip
    assert presence.main([*args, "--lenient"], client=client) == 0

    g = GraphStore(str(db))
    res = InProcessRulesClient(g).call("find_contradictions", {"story": WL}, timeout=1)
    assert res["status"] == "ok" and [f["rule"] for f in res["findings"]] == ["R1"]
    (f,) = res["findings"]
    assert f["provenance"] == "conditional" and f["reason_code"] == "OVERLAP_DIFFERENT_PLACES"
    quotes = sorted(a["quote"] for a in f["explanation"]["anchors"])
    assert quotes == sorted([S1_QUOTE, S2_QUOTE])
    clean = (ROOT / "data" / "clean" / f"{WL}.txt").read_text(encoding="utf-8")
    assert all(clean[a["char_start"] : a["char_end"]] == a["quote"] for a in f["anchors"])
    assert f["explanation"]["conditional"] is True and len(f["explanation"]["weak"]) == 2
    # the day is a heuristic: without it (no story_day/time overlays) there is no finding
    g.conn.execute("DELETE FROM g_overlay WHERE key IN ('story_day', 'time')")
    assert run_all(SqliteFactSource(g).load(WL), ("R1",))[0].findings == []
    # the same input without --lenient produces nothing (strict grounding)
    strict_db = tmp_path / "strict.sqlite"
    s_args = ["--model", "fake", "--chunks", str(chunks), "--cache", str(tmp_path / "c.sqlite"),
              "--graph-db", str(strict_db), "--prompt", str(PROMPT_V1)]  # fmt: skip
    assert presence.main(s_args, client=fake_by_passage({})) == 0
    gs = GraphStore(str(strict_db))
    assert (
        InProcessRulesClient(gs).call("find_contradictions", {"story": WL}, timeout=1)["findings"]
        == []
    )


def test_boscombe_mccarthy_control_c042_is_not_flagged(tmp_path):
    """Gold c042 is a consistent control. Facts: Charles McCarthy left Hatherley and walked to the
    Pool in ONE sentence (same occurrence: not a conflict), James McCarthy's testimony about
    Bristol, and a game-keeper fact whose place the model invented (dropped: not in the quote)."""
    ids = [f"{BV}-0002", f"{BV}-0003", f"{BV}-0007"]
    chunks = write_chunks(tmp_path / "chunks.jsonl", *ids)
    day = "On June 3rd, that is, on Monday last"
    at3 = "about three in the afternoon"
    client = fake_by_passage(
        {
            "McCarthy left his house at Hatherley": [
                fact(person="Charles McCarthy", place="Hatherley", time_text=at3, day_text=day,
                     quote=QUOTE_MC),
                fact(person="Charles McCarthy", place="the Boscombe Pool", time_text=at3,
                     day_text=day, quote=QUOTE_MC),
            ],
            "within a few minutes of his seeing": [
                fact(person="Mr. James McCarthy", place="the Boscombe Pool",
                     time_text="within a few minutes",
                     quote="within a few minutes of his seeing Mr. McCarthy pass he had seen his "
                     "son, Mr. James McCarthy, going the same way with a gun under his arm"),
            ],
            "I had been away from home for three days": [
                fact(person="Mr. James McCarthy", place="Bristol", source="speech",
                     time_text="the morning of last Monday, the 3rd", day_text="last Monday, the 3rd",
                     speaker="James McCarthy", quote=QUOTE_JAMES),
            ],
        }
    )  # fmt: skip
    db = tmp_path / "g.sqlite"
    rc = presence.main(["--model", "fake", "--chunks", str(chunks), "--cache", str(tmp_path / "c"),
                        "--graph-db", str(db), "--prompt", str(PROMPT_V1)], client=client)  # fmt: skip
    assert rc == 0
    g = GraphStore(str(db))
    assert len(nodes(g, "event")) == 3 and len(nodes(g, "claim")) == 1
    res = InProcessRulesClient(g).call("find_contradictions", {"story": BV}, timeout=1)
    assert res == {"status": "ok", "findings": [], "truncated": False}
    fb = SqliteFactSource(g).load(BV)
    r1 = run_all(fb, ("R1",))[0]
    assert r1.stats["skipped_same_occurrence"] == 1 and r1.stats["violated"] == 0
    assert all(x.verdict is not Verdict.VIOLATED for rep in run_all(fb) for x in rep.findings)
    mc = [e for e in fb.events if "Charles" in e.description]
    assert (
        len(mc) == 2
        and {e.occurrence_id for e in mc} != {None}
        and len({e.occurrence_id for e in mc}) == 1
    )
    # without the same-occurrence guard the two McCarthy events WOULD be an R1 violation
    unguarded = fb.model_copy(
        update={"events": [e.model_copy(update={"occurrence_id": None}) for e in fb.events]}
    )
    assert [x.verdict for x in run_all(unguarded, ("R1",))[0].findings] == [Verdict.VIOLATED]
