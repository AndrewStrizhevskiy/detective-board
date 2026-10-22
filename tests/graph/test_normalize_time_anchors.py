import pytest

from detective_board.graph import derive_time_norm, normalize_name, resolve_quote
from detective_board.graph.normalize import is_unnamed_person


@pytest.mark.parametrize(
    "raw,key",
    [
        ("Mr. Sherlock Holmes", "sherlock holmes"),
        ("Dr. Watson", "watson"),
        ("Mrs. Hudson", "hudson"),
        ("Holmes's", "holmes"),
        ("Holmes’s", "holmes"),
        ("Holmes'", "holmes"),
        ("McCarthy's", "mccarthy"),
        ("Inspector  Lestrade", "lestrade"),
        ("Dr.", "dr"),  # a bare title is not emptied
        ("O'Brien", "o'brien"),
    ],
)
def test_person_keys(raw, key):
    assert normalize_name(raw) == key


def test_unnamed_persons_keep_descriptor():
    assert is_unnamed_person("the deceased") and is_unnamed_person("His son")
    assert normalize_name("The Deceased") == "the deceased"
    assert not is_unnamed_person("Sherlock Holmes")


def test_place_drops_article():
    assert normalize_name("The Boscombe Pool", "place") == "boscombe pool"
    assert normalize_name("Baker St.", "place") == "baker st"


@pytest.mark.parametrize(
    "text,lo,conf",
    [
        ("nine o'clock", 540, "low"),
        ("nine o'clock at night", 1260, "high"),
        ("a quarter to nine", 525, "low"),
        ("a quarter to nine in the evening", 1245, "high"),
        ("a quarter past nine", 555, "low"),
        ("half-past ten", 630, "low"),
        ("half past ten in the morning", 630, "high"),
        ("eleven at night", 1380, "high"),
        ("about three in the afternoon", 900, "high"),
        ("ten minutes to nine", 530, "low"),
        ("twenty minutes past eleven at night", 1400, "high"),
        ("9:30 p.m.", 1290, "high"),
        ("21:15", 1275, "high"),
        ("noon", 720, "high"),
        ("midnight", 0, "low"),
        ("five minutes to twelve at night", 1435, "low"),
    ],
)
def test_clock_patterns(text, lo, conf):
    t = derive_time_norm(text)
    assert (t.method, t.lo, t.hi, t.exact, t.confidence) == (
        "noon" if text == "noon" else "midnight" if text == "midnight" else "clock",
        lo,
        lo,
        True,
        conf,
    )


def test_day_parts_are_fuzzy_and_low():
    t = derive_time_norm("that evening")
    assert (t.method, t.lo, t.hi, t.exact, t.confidence) == ("day_part", 1080, 1320, False, "low")


@pytest.mark.parametrize(
    "text", [None, "", "late", "a few minutes before", "the next morning", "soon"]
)
def test_unknown(text):
    t = derive_time_norm(text)
    assert (t.method, t.lo, t.hi, t.confidence) == ("unknown", None, None, "low")


def test_quote_exact_ambiguous_missing_ws():
    text = "He saw Smith. Later Smith left.   The  end"
    one = resolve_quote(text, "Later Smith")
    assert (one.status, one.rel_start, one.n_matches) == ("exact", 14, 1)
    assert text[one.rel_start : one.rel_end] == "Later Smith"
    two = resolve_quote(text, "Smith")
    assert (two.status, two.rel_start, two.n_matches) == ("ambiguous", 7, 2)
    assert resolve_quote(text, "Jones").status == "missing"
    assert resolve_quote(text, "").status == "missing"
    ws = resolve_quote(text, "The end")
    assert ws.status == "ws_normalised" and ws.quote == "The  end"
    assert text[ws.rel_start : ws.rel_end] == ws.quote
