from conftest import C2, C3, STORY, boscombe_extractions, build_boscombe, synth

from detective_board.extract.schema import Event, Extraction
from detective_board.graph import ALL_STORIES, GraphStore, SqliteFactSource
from detective_board.symbolic.api import (
    PresenceProp,
    TimeSpec,
    Verdict,
    check_claim,
    load_facts,
    run_all,
)

P = f"p:{STORY}:"
EV3, EV2 = f"e:{C3}:0", f"e:{C2}:0"
CL = f"c:{STORY}-0007:0"
HATH, POOL = f"pl:{STORY}:hatherley", f"pl:{STORY}:boscombe-pool"


def _prop(place: str) -> PresenceProp:
    t = TimeSpec(day=1, lo=945, hi=945, exact=True, confidence="high")
    return PresenceProp(person_id=P + "james-mccarthy", place_ref=place, time=t)


def _ready(bv):
    bv.set_event_day(EV3, 1, confidence="high")
    bv.set_claim_prop(CL, _prop(HATH), confidence="high")
    return bv


def test_factbase_shape(bv):
    fb = load_facts(SqliteFactSource(bv), STORY)
    assert fb.story == STORY
    assert [p.id for p in fb.places] == [POOL, HATH]
    assert fb.places[1].aliases == ["Hatherley"]
    ev = fb.event(EV3)
    assert ev.participants == sorted(
        [P + "patience-moran", P + "charles-mccarthy", P + "james-mccarthy"]
    )
    assert ev.place_ref == POOL and ev.narrator and ev.confidence == "high"
    assert ev.time.lo == ev.time.hi == 945 and ev.time.exact and ev.time.day is None
    assert ev.anchors[0].quote.startswith("she saw")
    assert fb.claim(CL).speaker_id == P + "james-mccarthy" and fb.claim(CL).prop is None
    assert fb.event(EV2).time.lo == 900


def test_digest_is_reproducible(bv, chunks):
    a = SqliteFactSource(_ready(bv)).load(STORY).digest()
    assert a == SqliteFactSource(bv).load(STORY).digest()
    assert a == SqliteFactSource(_ready(build_boscombe(chunks))).load(STORY).digest()


def test_round_trip_r3_violated_with_both_quotes(bv):
    fb = SqliteFactSource(_ready(bv)).load(STORY)
    f = check_claim(fb, CL)
    assert (f.rule_id, f.verdict, f.conditional) == ("R3", Verdict.VIOLATED, False)
    assert f.reason_code == "CLAIM_INCOMPATIBLE_WITH_FACT"
    assert {a.chunk_id for a in f.explanation.anchors} == {C3, f"{STORY}-0007"}
    assert all(a.quote for a in f.explanation.anchors)
    reports = run_all(fb)
    assert [r.rule_id for r in reports] == ["R1", "R2", "R3"]
    assert reports[2].findings[0].verdict is Verdict.VIOLATED


def test_round_trip_corroborated(bv):
    bv.set_event_day(EV3, 1, confidence="high")
    bv.set_claim_prop(CL, _prop(POOL), confidence="high")
    f = check_claim(SqliteFactSource(bv).load(STORY), CL)
    assert f.verdict is Verdict.CONSISTENT


def test_unstructured_claim_and_missing_day_are_unknown(bv):
    fb = SqliteFactSource(bv).load(STORY)
    assert check_claim(fb, CL).reason_code == "UNSTRUCTURED_CLAIM"
    bv.set_claim_prop(CL, _prop(HATH), confidence="high")  # event day still unknown
    assert check_claim(SqliteFactSource(bv).load(STORY), CL).verdict is Verdict.UNKNOWN


def test_low_confidence_inputs_make_findings_conditional(bv):
    bv.set_event_day(EV3, 1, confidence="low")
    bv.set_claim_prop(CL, _prop(HATH), confidence="high")
    f = check_claim(SqliteFactSource(bv).load(STORY), CL)
    assert f.verdict is Verdict.VIOLATED and f.conditional
    assert f.reason_code == "CLAIM_VS_EXTRACTED_EVENT"
    # opt-in single-day assumption is always low confidence
    bv.conn.execute("DELETE FROM g_overlay WHERE key='story_day'")
    fb = SqliteFactSource(bv, assume_day=1).load(STORY)
    assert fb.event(EV3).time.day == 1 and fb.event(EV3).time.confidence == "low"
    assert check_claim(fb, CL).conditional


def test_bare_clock_hour_is_low(chunks):
    s = GraphStore()
    t = "He arrived at nine o'clock and left."
    s.ingest(
        synth("t-0", t),
        Extraction(
            events=[
                Event(
                    description="arrival",
                    time_text="nine o'clock",
                    participants=["He"],
                    quote="He arrived at nine o'clock",
                )
            ]
        ),
    )
    ev = SqliteFactSource(s).load("syn").events[0]
    assert ev.time.confidence == "low" and ev.time.lo == 540
    assert ev.confidence == "low"  # "He" is an unnamed, implicit person


def test_reported_event_inside_claim_is_not_narrator(chunks):
    s = GraphStore()
    exs = boscombe_extractions()
    ex7 = exs[f"{STORY}-0007"].model_copy(
        update={
            "events": [
                Event(
                    description="James left his father",
                    place="Hatherley Farm",
                    participants=["James McCarthy"],
                    quote="I left him and returned towards Hatherley Farm",
                )
            ]
        }
    )
    s.ingest(chunks[f"{STORY}-0007"], ex7)
    fb = SqliteFactSource(s).load(STORY)
    assert fb.events[0].narrator is False


def test_whole_corpus_load_and_story_filter(bv):
    bv.ingest(
        synth("o-0", "Anna met Bob.", "other"),
        Extraction(
            events=[
                Event(description="meeting", participants=["Anna", "Bob"], quote="Anna met Bob")
            ]
        ),
    )
    src = SqliteFactSource(bv)
    assert len(src.load("other").events) == 1
    assert {e.id.split(":")[1].split("-0")[0] for e in src.load(ALL_STORIES).events} == {STORY, "o"}
    assert src.load("missing-story").events == []
