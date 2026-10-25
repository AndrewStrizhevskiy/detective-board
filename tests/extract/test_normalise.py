import pytest

from detective_board.extract.normalise import (
    DayInput,
    claim_prop,
    normalise_time,
    resolve_days,
)
from detective_board.extract.schema_v2 import Claim
from detective_board.symbolic.api import PresenceProp, TimeSpec


def test_clock_times():
    t = normalise_time("half past ten in the evening")
    assert (t.lo, t.hi, t.exact, t.confidence, t.day) == (1350, 1350, True, "high", None)
    assert normalise_time("nine o'clock").confidence == "low"  # bare hour: a guess
    assert normalise_time("a quarter to nine at night").lo == 20 * 60 + 45


@pytest.mark.parametrize(
    "text", ["about three in the afternoon", "nearly one o'clock", "shortly after 9:30 p.m."]
)
def test_approximate_clock_is_low(text):
    t = normalise_time(text)
    assert t.exact and t.lo is not None and t.confidence == "low"


def test_since_is_a_start_instant():
    t = normalise_time("since one o'clock")
    assert (t.lo, t.hi, t.exact, t.confidence) == (60, 60, True, "low")


def test_day_part_is_fuzzy():
    t = normalise_time("in the evening")
    assert (t.lo, t.hi, t.exact, t.confidence) == (1080, 1320, False, "low")


def test_unknown_and_empty():
    assert normalise_time(None) is None and normalise_time("  ") is None
    t = normalise_time("long ago")
    assert (t.lo, t.hi, t.day, t.rel) == (None, None, None, None) and t.time_text == "long ago"


def test_relative_day_with_known_reference():
    ref = TimeSpec(day=3, lo=900, hi=900, exact=True, confidence="high")
    t = normalise_time("the next morning", ref=ref, ref_event_id="e:1")
    assert (t.day, t.lo, t.hi, t.exact) == (4, 360, 720, False)
    assert (t.rel, t.ref_event_id, t.confidence) == ("after", "e:1", "low")
    t = normalise_time(
        "the following day at nine o'clock in the morning", ref=ref, ref_event_id="e:1"
    )
    assert (t.day, t.lo, t.exact) == (4, 540, True)
    t = normalise_time("the evening before", ref=ref, ref_event_id="e:1")
    assert (t.day, t.rel, t.lo) == (2, "before", 1080)
    t = normalise_time("that night", ref=ref, ref_event_id="e:1")
    assert (t.day, t.rel, t.ref_event_id, t.lo) == (3, None, "e:1", 1320)


def test_relative_day_with_unknown_reference():
    t = normalise_time("the next morning", ref=TimeSpec(lo=60, hi=60), ref_event_id="e:1")
    assert t.day is None and (t.rel, t.ref_event_id) == ("after", "e:1")
    t = normalise_time("the next morning")
    assert t.day is None and t.rel is None and t.ref_event_id is None


def _days(*items):
    return resolve_days([DayInput(f"e:{i}", text, i) for i, text in enumerate(items)])


def test_calendar_from_dates_and_linked_weekday():
    out = _days(
        "On June 3rd, that is, on Monday last",
        "about three in the afternoon",
        "on Wednesday",
        "June 4th",
        "the next morning",
    )
    jun3 = out["e:0"]
    assert jun3.confidence == "high" and jun3.method == "date"
    assert out["e:1"].day is None  # a clock time alone does not give a day
    assert out["e:2"].day == jun3.day + 2 and out["e:2"].confidence == "low"
    assert out["e:3"].day == jun3.day + 1 and out["e:3"].confidence == "high"
    assert out["e:4"].day == jun3.day + 2 and out["e:4"].ref_event_id == "e:3"
    assert out["e:4"].confidence == "low" and out["e:4"].method == "relative"


def test_weekdays_without_dates_and_unresolvable_relative():
    out = _days("the next morning", "on Monday", "Tuesday evening", "the same day")
    assert out["e:0"].day is None  # nothing before it has a day
    assert out["e:2"].day == out["e:1"].day + 1 and out["e:1"].confidence == "low"
    assert out["e:3"].day == out["e:2"].day and out["e:3"].ref_event_id == "e:2"


def test_resolve_days_is_order_independent():
    items = [DayInput("e:b", "June 4th", 20), DayInput("e:a", "June 3rd", 10)]
    assert resolve_days(items) == resolve_days(list(reversed(items)))


PEOPLE = {"garcia": ["p:s:garcia"], "mccarthy": ["p:s:charles", "p:s:james"]}
PLACES = {"wisteria lodge": ["pl:s:wisteria-lodge"]}


def person(name):
    return PEOPLE.get(name.lower().removeprefix("mr. "), [])


def place(name):
    return PLACES.get(name.lower().removeprefix("the "), [])


def _claim(**kw):
    base = {"speaker": "Scott Eccles", "content": "Garcia was in the house", "quote": "q"}
    return Claim(**(base | kw))


def test_presence_prop_from_v2_fields():
    c = _claim(
        about_person="Garcia", about_place="Wisteria Lodge", about_time_text="nearly one o'clock"
    )
    r = claim_prop(c, person, place, day=1, day_confidence="low")
    assert isinstance(r.prop, PresenceProp) and r.reason == "OK"
    assert (r.prop.person_id, r.prop.place_ref) == ("p:s:garcia", "pl:s:wisteria-lodge")
    assert (r.prop.time.day, r.prop.time.lo, r.prop.time.exact) == (1, 60, True)
    assert r.confidence == "low"


@pytest.mark.parametrize(
    ("kw", "reason"),
    [
        ({"polarity": "deny"}, "DENIAL_NOT_MODELLED"),
        ({"about_place": None}, "NO_PLACE"),
        ({"about_time_text": None}, "NO_TIME"),
        ({"about_time_text": "long ago"}, "TIME_UNPARSED"),
        ({"about_person": "McCarthy"}, "PERSON_AMBIGUOUS"),
        ({"about_person": "Moriarty"}, "PERSON_UNRESOLVED"),
        ({"about_place": "the club"}, "PLACE_UNRESOLVED"),
    ],
)
def test_claim_without_checkable_proposition(kw, reason):
    base = {
        "about_person": "Garcia",
        "about_place": "Wisteria Lodge",
        "about_time_text": "at one o'clock",
    }
    r = claim_prop(_claim(**(base | kw)), person, place, day=1, day_confidence="high")
    assert r.prop is None and r.reason == reason


def test_claim_person_is_never_guessed_from_the_speaker():
    PEOPLE["scott eccles"] = ["p:s:eccles"]
    try:
        c = _claim(about_place="Wisteria Lodge", about_time_text="half past ten in the evening")
        r = claim_prop(c, person, place, day=2, day_confidence="high")
    finally:
        del PEOPLE["scott eccles"]
    assert r.prop is None and r.reason == "PERSON_MISSING"


def test_claim_with_all_slots_and_a_known_day_is_high():
    c = _claim(
        about_person="Garcia",
        about_place="Wisteria Lodge",
        about_time_text="half past ten in the evening",
    )
    r = claim_prop(c, person, place, day=2, day_confidence="high")
    assert r.prop.person_id == "p:s:garcia" and r.confidence == "high"


def test_qualified_weekdays_get_no_day_and_curated_days_are_references():
    out = _days("on Monday", "the following Monday", "next Friday")
    assert out["e:0"].day == 0 and out["e:1"].day is None and out["e:2"].day is None
    out = resolve_days(
        [DayInput("a", "at nine o'clock", 0, known_day=7), DayInput("b", "the next morning", 1)]
    )
    assert (out["a"].day, out["a"].method) == (7, "curated")
    assert (out["b"].day, out["b"].ref_event_id) == (8, "a")


def test_claim_without_day_keeps_the_time_but_rules_will_say_unknown():
    c = _claim(about_person="Garcia", about_place="Wisteria Lodge", about_time_text="one o'clock")
    r = claim_prop(c, person, place, day=None, day_confidence="low")
    assert r.prop is not None and r.prop.time.day is None and r.confidence == "low"
