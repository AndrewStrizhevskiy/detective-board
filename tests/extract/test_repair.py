"""extract/repair.py: one test group per rule, on sentences from data/clean (Boscombe Valley,
Wisteria Lodge), plus idempotence, determinism and the graph/normaliser reading of the result."""

import copy
import json

import pytest

from detective_board.extract import normalise, schema_v2
from detective_board.extract.llm import FakeClient
from detective_board.extract.parse import validate_items
from detective_board.extract.pipeline import ExtractConfig, Extractor
from detective_board.extract.repair import (
    REPAIR_VERSION,
    has_negation,
    quotation_spans,
    repair_extraction,
    repair_items,
)
from detective_board.graph import ChunkRef, GraphStore, SqliteFactSource

from .conftest import CHUNK, good_output

# Boscombe Valley, chunk 0002 / 0005 (verbatim)
BV = (
    "McCarthy left his house at Hatherley about three in the afternoon and walked down to the "
    "Boscombe Pool. From that appointment he never came back alive. The game-keeper adds that "
    "within a few minutes of his seeing Mr. McCarthy pass he had seen his son, Mr. James "
    "McCarthy, going the same way with a gun under his arm."
)
# Wisteria Lodge, chunk 0000 (speech after narration)
WL = (
    "“There is surely something more than that,” said he; “some underlying suggestion of the "
    "tragic and the terrible. Think of that little affair of the red-headed men. The word puts "
    "me on the alert.”\n\nI shook my head.\n\n“Many men have been hanged,” I remarked."
)


def ent(name, kind="person", *aliases, unnamed=False):
    return {"name": name, "type": kind, "aliases": list(aliases), "quote": name, "unnamed": unnamed}


def ev(quote, **kw):
    d = {"description": "", "time_text": None, "place": None, "participants": [],
         "in_speech": False, "transit": False, "quote": quote}  # fmt: skip
    return d | kw


def cl(quote, **kw):
    d = {"speaker": "X", "content": quote, "about": None, "about_person": None,
         "about_place": None, "about_time_text": None, "polarity": "deny", "quote": quote}  # fmt: skip
    return d | kw


def one(kind, item, text, entities=()):
    out, rep = repair_items({"entities": list(entities), kind: [item]}, text)
    return out[kind][0], rep


# --- R1 participants


def test_participants_added_from_quote_and_description():
    ents = [ent("Charles McCarthy", "person", "McCarthy"), ent("James McCarthy")]
    q = "he had seen his son, Mr. James McCarthy, going the same way with a gun under his arm"
    e, rep = one("events", ev(q, description="Crowder saw James"), BV, ents)
    assert e["participants"] == ["James McCarthy"]  # 'McCarthy' alone is ambiguous: not added
    assert e["participants_model"] == [] and "PARTICIPANTS_ADDED" in e["repair"]
    assert rep.participants_added == 1


def test_unique_surname_and_alias_match_and_title_stripping():
    ents = [ent("Mr. Charles McCarthy", "person", "the old man"), ent("William Crowder")]
    e, _ = one("events", ev("Mr. McCarthy pass", description=""), BV, ents)
    assert e["participants"] == ["Mr. Charles McCarthy"]
    e, _ = one("events", ev("saw the old man go"), "saw the old man go", ents)
    assert e["participants"] == ["Mr. Charles McCarthy"]


def test_model_participants_kept_if_grounded_dropped_if_not():
    ents = [ent("James McCarthy"), ent("William Crowder")]
    q = "his son, Mr. James McCarthy, going the same way"
    e, rep = one("events", ev(q, participants=["James McCarthy", "William Crowder"]), BV, ents)
    assert e["participants"] == ["James McCarthy"]
    assert e["participants_model"] == ["James McCarthy", "William Crowder"]
    assert rep.participants_dropped == 1


def test_pronouns_and_unnamed_are_not_participants():
    ents = [ent("he", "person"), ent("Holmes", "person", "he")]
    e, _ = one("events", ev("he walked", participants=["he"]), "he walked", ents)
    assert e["participants"] == []


# --- R2 polarity


@pytest.mark.parametrize(
    ("quote", "deny"),
    [
        ("The word puts me on the alert.", False),
        ("I had no idea that he was in front of me", False),  # 'no' alone is not a cue
        ("I never touched the gun", True),
        ("I did not see him", True),
        ("I didn’t see him", True),
        ("I know nothing further of the matter.", True),
        ("I should prefer not to answer.", True),
        ("He denied it", True),
        ("they refused to speak", True),
        ("he left without a word", True),
        ("Nobody saw him", True),
        ("I saw William Crowder, the game-keeper", False),
    ],
)
def test_polarity_from_negation_cue(quote, deny):
    assert has_negation(quote) is deny
    c, _ = one("claims", cl(quote, polarity="deny" if not deny else "affirm"), quote)
    assert c["polarity"] == ("deny" if deny else "affirm")
    assert c["polarity_model"] == ("affirm" if deny else "deny")


# --- R3 in_speech


def test_quotation_spans_curly_and_multi_paragraph():
    t = "He said, “one two.”\n\n“three\n\n“four” and five."
    spans = [t[a:b] for a, b in quotation_spans(t)]
    assert spans == ["one two.", "three\n\n“four"]


def test_quotation_spans_chunk_starts_inside_a_quote():
    t = "and so on,” said he. “Then it ended.”"
    assert [t[a:b] for a, b in quotation_spans(t)] == ["and so on,", "Then it ended."]


def test_quotation_spans_straight_and_unbalanced():
    t = 'He said "yes" and left.\n\nNext paragraph "never closed\n\nPlain narration.'
    assert [t[a:b] for a, b in quotation_spans(t)] == ["yes", "never closed"]


def test_in_speech_inside_vs_narration():
    inside, _ = one("events", ev("The word puts me on the alert"), WL)
    assert inside["in_speech"] is True
    tag, _ = one("events", ev("said he", in_speech=True), WL)
    assert tag["in_speech"] is False and tag["in_speech_model"] is True
    narr, _ = one("events", ev("I shook my head"), WL)
    assert narr["in_speech"] is False


def test_in_speech_quote_not_in_chunk_is_false_with_code():
    e, rep = one("events", ev("not in the chunk at all", in_speech=True), WL)
    assert e["in_speech"] is False and "IN_SPEECH_QUOTE_NOT_LOCATED" in e["repair"]
    assert rep.in_speech_not_located == 1


# --- R4 time_text / place


def test_time_and_place_grounded_in_own_quote_are_kept():
    ents = [ent("Hatherley", "place")]
    q = "McCarthy left his house at Hatherley about three in the afternoon"
    e, _ = one(
        "events", ev(q, time_text="about three in the afternoon", place="Hatherley"), BV, ents
    )
    assert (e["time_text"], e["place"]) == ("about three in the afternoon", "Hatherley")
    assert e["time_text_inherited"] is None and e["place_inherited"] is None


def test_time_and_place_copied_from_chunk_start_become_inherited():
    ents = [ent("Hatherley", "place"), ent("Boscombe Pool", "place")]
    ev_ = ev("From that appointment he never came back alive",
             time_text="June 3rd, that is, on Monday last", place="Boscombe Pool")  # fmt: skip
    e, rep = one("events", ev_, BV, ents)
    assert e["time_text"] is None and e["place"] is None
    assert e["time_text_inherited"] == "June 3rd, that is, on Monday last"
    assert e["place_inherited"] == "Boscombe Pool"
    assert e["time_text_model"] == e["time_text_inherited"]
    assert rep.time_inherited == 1 and rep.place_inherited == 1


def test_time_that_is_not_a_time_and_place_that_is_not_a_place_are_dropped():
    q = "I shook my head"
    e, _ = one("events", ev(q, time_text=q, place="the chair"), WL)
    assert e["time_text"] is None and e["time_text_inherited"] is None
    assert e["place"] is None and e["place_inherited"] is None
    assert {"TIME_NOT_TEMPORAL", "PLACE_NOT_A_PLACE"} <= set(e["repair"])


# --- R5 claims


def test_claim_about_fields_kept_only_if_in_quote():
    q = "I had been away from home for three days at Bristol"
    c, rep = one(
        "claims",
        cl(
            q,
            speaker="James McCarthy",
            about_person="James McCarthy",
            about_place="Bristol",
            about_time_text="three days",
        ),  # fmt: skip
        q,
        [ent("Bristol", "place")],
    )
    assert (c["about_person"], c["about_place"], c["about_time_text"]) == (
        "James McCarthy", "Bristol", "three days"
    )  # fmt: skip
    assert c["repair"] == ["POLARITY_CHANGED"] and rep.about_person_nulled == 0


def test_claim_about_fields_nulled_with_audit():
    q = "It conveyed no meaning to me."
    c, rep = one(
        "claims",
        cl(
            q,
            speaker="Witness",
            about_person="Father",
            about_place="the open",
            about_time_text="before he died",
        ),  # fmt: skip
        q,
    )
    assert c["about_person"] is None and c["about_place"] is None and c["about_time_text"] is None
    assert c["about_person_model"] == "Father" and c["about_time_text_model"] == "before he died"
    assert {
        "ABOUT_PERSON_NOT_IN_QUOTE",
        "ABOUT_PLACE_NOT_IN_QUOTE",
        "ABOUT_TIME_NOT_IN_QUOTE",
    } <= set(c["repair"])
    assert rep.about_person_nulled == 1


def test_first_person_claim_keeps_speaker_as_about_person_pronoun_does_not():
    q = "I heard a cry of “Cooee!” which was a usual signal"
    c, _ = one("claims", cl(q, speaker="James McCarthy", about_person="James McCarthy"), q)
    assert c["about_person"] == "James McCarthy"
    third = "He had been out with his serving-man in the morning at Ross"
    c, _ = one("claims", cl(third, speaker="McCarthy", about_person="McCarthy"), third)
    assert c["about_person"] is None
    c, _ = one("claims", cl(third, speaker="McCarthy", about_person="He"), third)
    assert c["about_person"] is None


# --- properties


def _sample():
    ents = [ent("Charles McCarthy", "person", "McCarthy"), ent("James McCarthy"),
            ent("Hatherley", "place"), ent("Boscombe Pool", "place")]  # fmt: skip
    return {
        "entities": ents,
        "events": [
            ev("McCarthy left his house at Hatherley about three in the afternoon",
               time_text="about three in the afternoon", place="Hatherley"),
            ev("From that appointment he never came back alive",
               time_text="June 3rd", place="Boscombe Pool", in_speech=True),
        ],
        "claims": [cl("He never came back alive", about_person="Charles McCarthy")],
        "relations": [],
    }  # fmt: skip


def test_idempotent_deterministic_and_input_untouched():
    src = _sample()
    frozen = copy.deepcopy(src)
    once, r1 = repair_items(src, BV)
    assert src == frozen
    twice, r2 = repair_items(once, BV)
    assert twice == once and r1.to_dict() == r2.to_dict()
    assert repair_items(src, BV)[0] == once
    assert once["events"][0]["repair_version"] == REPAIR_VERSION
    assert json.dumps(once, sort_keys=True) == json.dumps(twice, sort_keys=True)


def test_repair_extraction_validated_model_roundtrip():
    ex = schema_v2.Extraction.model_validate(_sample())
    fixed, rep = repair_extraction(ex, BV)
    again, _ = repair_extraction(fixed, BV)
    assert again == fixed and rep.events == 2 and rep.claims == 1
    assert fixed.events[1].time_text is None and fixed.events[1].time_text_inherited == "June 3rd"


def test_repair_fields_are_hidden_from_the_model_schema_and_output():
    schema = json.dumps(schema_v2.ollama_format_schema())
    for fields in schema_v2.REPAIR_FIELDS.values():
        assert not any(f'"{f}"' in schema for f in fields)
    d = {"events": [{"description": "d", "quote": "q", "participants_model": ["x"],
                     "repair_version": "9"}]}  # fmt: skip
    kept = validate_items(d).items["events"][0]
    assert kept["participants_model"] is None and kept["repair_version"] is None


# --- pipeline and graph


def test_pipeline_repairs_on_cache_hit_and_config_can_disable():
    raw = good_output(
        claims=[
            {
                "speaker": "James McCarthy",
                "content": "c",
                "polarity": "deny",
                "quote": "The\tdeceased was found by the pool",
            }
        ]  # fmt: skip
    )
    r = Extractor(FakeClient([raw]), ExtractConfig("fake:1b")).extract_chunk("c1", "s", CHUNK)
    assert r.repair["version"] == REPAIR_VERSION
    assert r.extraction["claims"][0]["polarity"] == "affirm"
    # the event's own quote ("I left the house ...") does not name the model's participant
    assert r.extraction["events"][0]["participants"] == []
    assert r.extraction["events"][0]["participants_model"] == ["James McCarthy"]
    assert r.extraction["events"][0]["in_speech"] is False  # narration, the model said True
    off = ExtractConfig("fake:1b", repair=False)
    r2 = Extractor(FakeClient([raw]), off).extract_chunk("c1", "s", CHUNK)
    assert r2.repair == {} and r2.extraction["claims"][0]["polarity"] == "deny"


def test_ingest_repairs_unrepaired_results():
    from detective_board.extract.ingest import to_graph_input

    raw = good_output()
    cfg = ExtractConfig("fake:1b", repair=False)
    r = Extractor(FakeClient([raw]), cfg).extract_chunk("c1", "s", CHUNK)
    rec = {"chunk_id": "c1", "story": "s", "char_start": 0, "char_end": len(CHUNK), "text": CHUNK}
    _, ex = to_graph_input(r, rec, repair=False)
    assert ex.events[0].repair_version is None
    _, ex = to_graph_input(r, rec)
    assert ex.events[0].repair_version == REPAIR_VERSION and r.repair["version"] == REPAIR_VERSION


def _graph(events):
    text = BV
    ex = schema_v2.Extraction.model_validate(
        {
            "entities": [ent("McCarthy"), ent("Hatherley", "place"), ent("Boscombe Pool", "place")],
            "events": events,
        }  # fmt: skip
    )
    fixed, _ = repair_extraction(ex, text)
    g = GraphStore()
    g.ingest(ChunkRef("c1", "s", 0, len(text), text), fixed)
    normalise.apply(g, "s")
    facts = SqliteFactSource(g).load("s")
    g.close()
    return {e.description: e for e in facts.events}


def test_inherited_time_and_place_are_low_and_never_exact():
    own = ev("McCarthy left his house at Hatherley about three in the afternoon",
             description="own", time_text="three in the afternoon", place="Hatherley")  # fmt: skip
    inh = ev("walked down to the Boscombe Pool", description="inh",
             time_text="three in the afternoon", place="Hatherley")  # fmt: skip
    events = _graph([own, inh])
    assert events["inh"].time.exact is False and events["inh"].time.confidence == "low"
    assert events["inh"].time.lo is not None  # still usable by the rules, as a conditional input
    assert events["inh"].confidence == "low" and events["inh"].place_ref is not None
    assert events["own"].time.time_text == "three in the afternoon"


def test_inherited_date_never_gives_a_high_day():
    own = normalise.resolve_days([normalise.DayInput("a", "June 3rd", 0)])["a"]
    inh = normalise.resolve_days([normalise.DayInput("a", "June 3rd", 0, inherited=True)])["a"]
    assert own.confidence == "high" and inh.day == own.day and inh.confidence == "low"
    spec = normalise.normalise_time("nine o'clock", inherited=True)
    assert spec is not None and spec.exact is False and spec.confidence == "low"
