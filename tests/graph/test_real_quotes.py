"""Regressions on real passages (verbatim chunk text and offsets from data/chunks.jsonl):
extraction-shaped v2 input -> graph -> normaliser -> FactBase -> rules."""

import json
from functools import cache
from pathlib import Path

from detective_board.extract import normalise
from detective_board.extract.schema_v2 import Claim, Entity, Event, Extraction
from detective_board.graph import ChunkRef, GraphStore, SqliteFactSource
from detective_board.symbolic.api import PresenceProp, TimeSpec, Verdict, check_claim, run_all

ROOT = Path(__file__).resolve().parents[2]
BV, WL = "boscombe-valley-mystery", "wisteria-lodge"


@cache
def _records() -> dict[str, dict]:
    with open(ROOT / "data" / "chunks.jsonl", encoding="utf-8") as f:
        return {r["chunk_id"]: r for r in map(json.loads, f)}


def chunk(cid: str) -> ChunkRef:
    rec = _records()[cid]
    clean = (ROOT / "data" / "clean" / f"{rec['story']}.txt").read_text(encoding="utf-8")
    ref = ChunkRef.from_record(rec, clean)
    assert ref.contiguous  # offsets are real offsets into the clean story text
    return ref


def ent(name, kind, quote, *aliases):
    return Entity(name=name, type=kind, aliases=list(aliases), quote=quote)


def boscombe() -> GraphStore:
    """Gold c042 (consistent control): the game-keeper saw James go the same way a few minutes
    after his father; James denies that he was *following* him."""
    g = GraphStore()
    cm, jm, wc = "Charles McCarthy", "James McCarthy", "William Crowder"
    g.ingest_many(
        [
            (
                chunk(f"{BV}-0003"),
                Extraction(
                    entities=[
                        ent(wc, "person", "William Crowder", "the game-keeper"),
                        ent(cm, "person", "Mr. McCarthy", "McCarthy"),
                        ent(jm, "person", "Mr. James McCarthy"),
                    ],
                    events=[
                        Event(
                            description="Crowder sees Charles McCarthy pass",
                            participants=[wc, cm],
                            quote="his seeing Mr. McCarthy pass",
                        ),
                        Event(
                            description="Crowder sees James McCarthy going the same way with a gun",
                            time_text="within a few minutes",
                            participants=[wc, jm],
                            quote="he had seen his son, Mr. James McCarthy, going the same way "
                            "with a gun under his arm",
                        ),
                    ],
                ),
            ),
            (
                chunk(f"{BV}-0007"),
                Extraction(
                    entities=[ent(wc, "person", "William Crowder")],
                    claims=[
                        Claim(
                            speaker=jm,
                            content="he was not following his father",
                            about=cm,
                            about_person=jm,
                            polarity="deny",
                            quote="he is mistaken in thinking that I was following my father",
                        )
                    ],
                ),
            ),
        ]
    )
    return g


def test_boscombe_following_claim_is_not_a_violation():
    g = boscombe()
    rep = normalise.apply(g, BV)
    assert rep.claim_reasons == {"DENIAL_NOT_MODELLED": 1}
    fb = SqliteFactSource(g).load(BV)
    claim = fb.claims[0]
    assert claim.anchors[0].quote == "he is mistaken in thinking that I was following my father"
    assert claim.anchors[0].char_start == 12084 + _records()[f"{BV}-0007"]["text"].index(
        "he is mistaken"
    )
    f = check_claim(fb, claim.id)
    assert (f.verdict, f.reason_code) == (Verdict.UNKNOWN, "UNSTRUCTURED_CLAIM")
    assert f.explanation.missing == ["structured_proposition"]
    assert all(x.verdict is not Verdict.VIOLATED for r in run_all(fb) for x in r.findings)


def wisteria() -> GraphStore:
    """Gold c001: Eccles says Garcia looked in at nearly one o'clock; the police say Garcia lay
    dead on Oxshott Common since one o'clock."""
    g = GraphStore()
    ga = "Garcia"
    g.ingest_many(
        [
            (
                chunk(f"{WL}-0006"),
                Extraction(
                    entities=[
                        ent(ga, "person", "Garcia"),
                        ent("Wisteria Lodge", "place", "Wisteria Lodge"),
                    ],
                    events=[
                        Event(
                            description="Garcia looks in at Eccles's bedroom door",
                            time_text="nearly one o’clock",
                            place="Wisteria Lodge",
                            participants=[ga],
                            in_speech=True,
                            quote="Some time later Garcia looked in at my door",
                        )
                    ],
                ),
            ),
            (
                chunk(f"{WL}-0009"),
                Extraction(
                    entities=[
                        ent(ga, "person", "Mr. Garcia"),
                        ent("Oxshott Common", "place", "Oxshott Common"),
                    ],
                    events=[
                        Event(
                            description="Garcia is found dead on Oxshott Common",
                            time_text="this morning",
                            place="Oxshott Common",
                            participants=[ga],
                            in_speech=True,
                            quote="He was found dead this morning upon Oxshott Common",
                        )
                    ],
                ),
            ),
            (
                chunk(f"{WL}-0010"),
                Extraction(
                    entities=[
                        ent("Scott Eccles", "person", "Mr. Scott Eccles"),
                        ent("Wisteria Lodge", "place", "Wisteria Lodge"),
                    ],
                    events=[
                        Event(
                            description="Garcia lies dead on Oxshott Common",
                            time_text="since one o’clock",
                            place="Oxshott Common",
                            participants=[ga],
                            in_speech=True,
                            quote="He had been there since one o’clock",
                        )
                    ],
                    claims=[
                        Claim(
                            speaker="Scott Eccles",
                            content="Garcia addressed him in his bedroom at that hour",
                            about=ga,
                            about_person=ga,
                            about_place="Wisteria Lodge",
                            about_time_text="that very hour",
                            quote="I could swear to it that it was he who addressed me in my "
                            "bedroom at that very hour",
                        )
                    ],
                ),
            ),
        ]
    )
    return g


LOOK_IN, DEAD_SINCE = f"e:{WL}-0006:0", f"e:{WL}-0010:0"


def test_wisteria_without_a_day_stays_unknown():
    g = wisteria()
    rep = normalise.apply(g, WL)
    assert rep.events_timed == 3 and rep.events_dated == 0
    assert rep.claim_reasons == {"TIME_UNPARSED": 1}  # "that very hour" is anaphoric
    fb = SqliteFactSource(g).load(WL)
    t = fb.event(LOOK_IN).time
    assert (t.lo, t.hi, t.exact, t.confidence, t.day) == (60, 60, True, "low", None)
    assert fb.event(LOOK_IN).narrator is False  # in_speech
    r1 = run_all(fb, ("R1",))[0]
    assert r1.findings == [] and (r1.stats["unknown"], r1.stats["consistent"]) == (2, 1)


def test_wisteria_with_curated_day_is_a_conditional_r1_violation():
    g = wisteria()
    for eid in (LOOK_IN, DEAD_SINCE):  # curation: "on the night of his death" (chunk 0010)
        g.set_event_day(eid, 1, confidence="low")
    normalise.apply(g, WL)
    fb = SqliteFactSource(g).load(WL)
    (f,) = run_all(fb, ("R1",))[0].findings
    assert (f.verdict, f.reason_code, f.conditional) == (
        Verdict.VIOLATED,
        "OVERLAP_DIFFERENT_PLACES",
        True,
    )
    assert sorted(f.explanation.weak) == [LOOK_IN, DEAD_SINCE]
    quotes = [a.quote for a in f.explanation.anchors]
    assert quotes == [
        "Some time later Garcia looked in at my door",
        "He had been there since one o’clock",
    ]
    clean = (ROOT / "data" / "clean" / f"{WL}.txt").read_text(encoding="utf-8")
    assert all(clean[a.char_start : a.char_end] == a.quote for a in f.explanation.anchors)


def test_curated_prop_and_time_survive_the_normaliser():
    g = wisteria()
    claim = f"c:{WL}-0010:0"
    t = TimeSpec(day=5, lo=60, hi=60, exact=True, confidence="high")
    prop = PresenceProp(person_id=f"p:{WL}:garcia", place_ref=f"pl:{WL}:wisteria-lodge", time=t)
    g.set_claim_prop(claim, prop, confidence="high")
    g.set_overlay(LOOK_IN, "time", t.model_copy(update={"day": 99}), confidence="high")
    normalise.apply(g, WL)
    fb = SqliteFactSource(g).load(WL)
    assert fb.claim(claim).prop == prop
    assert fb.event(LOOK_IN).time.day == 99
    keys = {(r[0], r[1]) for r in g.conn.execute("SELECT node_id, key FROM g_overlay")}
    assert (LOOK_IN, "story_day") not in keys


def test_normalise_cli_on_a_graph_file(tmp_path, capsys):
    path = str(tmp_path / "g.sqlite")
    g = GraphStore(path)
    g.ingest_many([(chunk(f"{WL}-0006"), Extraction(entities=[ent("Garcia", "person", "Garcia")]))])
    g.close()
    normalise.main([path, "--story", WL])
    assert capsys.readouterr().out.startswith(f"{WL}: events timed 0")


def test_normalise_is_deterministic_and_idempotent():
    a, b = wisteria(), wisteria()
    for g in (a, b):
        g.set_event_day(LOOK_IN, 1, confidence="low")
        normalise.apply(g, WL)
    normalise.apply(b, WL)
    dump = [r.model_dump_json() for r in run_all(SqliteFactSource(a).load(WL))]
    assert dump == [r.model_dump_json() for r in run_all(SqliteFactSource(b).load(WL))]
    rows = "SELECT node_id,key,value_json,confidence,source FROM g_overlay ORDER BY 1,2"
    assert a.conn.execute(rows).fetchall() == b.conn.execute(rows).fetchall()
    assert ("e:" + WL + "-0006:0", "story_day", "1", "low", "manual") in [
        tuple(r) for r in a.conn.execute(rows)
    ]
