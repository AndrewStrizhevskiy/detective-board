"""`scene_board`: alibi-exclusion board per person, composed from `check_alibi` (hand-built
FactBase, no model, no graph file)."""

import pytest

from detective_board.mcp import tools
from detective_board.mcp.errors import ToolError
from detective_board.symbolic.api import Anchor, ClaimRec, EventRec, FactBase, PlaceRec, TimeSpec

DAY = 20_001
WINDOW = tools.Window(story_day=DAY, start_min=60, end_min=60)


def anc(q, start, chunk="c1"):
    return Anchor(story="s", chunk_id=chunk, char_start=start, char_end=start + len(q), quote=q)


def at(lo, text, day=DAY, exact=True, conf="high"):
    return TimeSpec(day=day, lo=lo, hi=lo, exact=exact, confidence=conf, time_text=text)


class Src:
    def __init__(self, fb):
        self.fb = fb

    def load(self, story):
        if story != "s":
            raise ToolError("not_found", "unknown story")
        return self.fb


def ev(eid, who, place, time, quote, start, **kw):
    return EventRec(
        id=eid,
        description=f"{who} at {place}",
        time=time,
        place_ref=place,
        participants=[who],
        anchors=[anc(quote, start)],
        **kw,
    )


def fixture(extra_events=(), extra_claims=()):
    events = [
        ev("e-vic", "Victim", "common", at(60, "since one"), "Victim lay on the Common", 10),
        ev("e-ex", "Eccles", "lodge", at(60, "at one"), "Eccles slept at the Lodge", 100),
        ev(
            "e-pl",
            "Baynes",
            "common",
            at(60, "since one", conf="low"),
            "Baynes waited on the Common",
            200,
            narrator=False,
        ),
        # a placed event with no day: it cannot place or exclude anyone
        ev("e-nd", "Hudson", "lodge", at(60, "at one", day=None), "Hudson was at the Lodge", 300),
        # a different time of the same day: disjoint
        ev("e-late", "Gregson", "lodge", at(600, "at ten"), "Gregson was at the Lodge", 400),
        EventRec(id="e-np", description="Lopez talks", participants=["Lopez"], anchors=[]),
        *extra_events,
    ]
    claims = [
        ClaimRec(
            id="c-pl",
            speaker_id="Narrator-1",
            content="Baynes was at common",
            anchors=[anc("Baynes waited on the Common", 200)],
        ),
        *extra_claims,
    ]
    places = [
        PlaceRec(id="common", name="Oxshott Common", aliases=["the Common"]),
        PlaceRec(id="lodge", name="Wisteria Lodge"),
    ]
    return Src(FactBase(story="s", places=places, events=events, claims=claims))


def board(src=None, **kw):
    kw.setdefault("place", "Oxshott Common")
    kw.setdefault("window", WINDOW)
    return tools.scene_board(src or fixture(), story="s", **kw)


def by(out):
    return {p["person_id"]: p for p in out["persons"]}


def test_excluded_placed_and_not_excluded_statuses():
    out = board(victim_ids=["Victim"])
    persons = by(out)
    assert persons["Eccles"]["status"] == "excluded"
    assert persons["Eccles"]["alibi_status"] == "contradicted"
    assert persons["Baynes"]["status"] == "placed"
    for quiet in ("Hudson", "Gregson", "Lopez"):
        assert persons[quiet]["status"] == "not_excluded", quiet
    assert out["counts"] == {"excluded": 1, "placed": 1, "not_excluded": 4}
    assert out["total_persons"] == 6 and not out["truncated"]
    assert out["status"] == "ok" and out["rule_id"] == "R1"
    # decisive persons first, then those with a placed event first
    assert [p["person_id"] for p in out["persons"]][:2] == ["Eccles", "Baynes"]


def test_each_status_is_what_check_alibi_says():
    out = board(victim_ids=["Victim"])
    src = fixture()
    for p in out["persons"]:
        alibi = tools.check_alibi(
            src, story="s", person_id=p["person_id"], window=WINDOW, claimed_place_id="common"
        )
        assert p["alibi_status"] == alibi["status"], p["person_id"]
        assert p["reason_code"] == alibi["reason_code"]
        assert p["provenance"] == alibi["provenance"]
        if p["status"] != "not_excluded":
            assert p["explanation"] == alibi["explanation"]


def test_evidence_has_anchor_where_and_who_says_so():
    out = board(victim_ids=["Victim"])
    ex = by(out)["Eccles"]
    (e,) = ex["evidence"]
    assert e["kind"] == "places_person_elsewhere" and e["at_scene"] is False
    assert e["place"] == "Wisteria Lodge" and e["narrator"] is True and e["speaker_id"] is None
    assert e["anchors"][0]["quote"] == "Eccles slept at the Lodge"
    assert ex["provenance"] == "derived" and ex["also_at_scene"] is False
    pl = by(out)["Baynes"]
    (p,) = pl["evidence"]
    assert p["kind"] == "places_person_at_claimed" and p["at_scene"] is True
    assert p["narrator"] is False and p["speaker_id"] == "Narrator-1"
    assert pl["provenance"] == "conditional"  # the placing event is low confidence
    assert out["provenance"] == "conditional"


def test_events_without_a_day_are_counted_and_never_decide():
    hudson = by(board(victim_ids=["Victim"]))["Hudson"]
    assert hudson["status"] == "not_excluded" and hudson["reason_code"] == "NO_DECISIVE_EVIDENCE"
    assert hudson["placed_events"] == 1 and hudson["events_without_day"] == 1
    assert hudson["evidence"] == [] and "explanation" not in hudson
    lopez = by(board())["Lopez"]
    assert lopez["placed_events"] == 0 and lopez["events_without_day"] == 0


def test_a_person_with_two_accounts_is_excluded_and_also_at_scene():
    both = fixture(
        [
            ev("e-b1", "Twin", "common", at(60, "at one"), "Twin was on the Common", 500),
            ev("e-b2", "Twin", "lodge", at(60, "at one"), "Twin was at the Lodge", 600),
        ]
    )
    twin = by(board(both, victim_ids=["Victim"]))["Twin"]
    assert twin["status"] == "excluded" and twin["also_at_scene"] is True
    assert {e["at_scene"] for e in twin["evidence"]} == {True, False}


def test_victims_are_checked_apart_and_not_on_the_board():
    out = board(victim_ids=["Victim", "Nobody"])
    assert "Victim" not in by(out) and out["total_persons"] == 6
    (v,) = out["victims"]  # an id the story does not know is skipped
    assert v["person_id"] == "Victim" and v["status"] == "placed"
    assert board()["victims"] == []


def test_person_ids_limit_and_counts_over_all_persons():
    out = board(person_ids=["Eccles", "Lopez", "Unknown"], victim_ids=["Victim"])
    assert [p["person_id"] for p in out["persons"]] == ["Eccles", "Lopez"]
    assert out["total_persons"] == 2
    small = board(victim_ids=["Victim"], limit=3)
    assert len(small["persons"]) == 3 and small["truncated"] is True
    assert small["counts"]["not_excluded"] == 4  # counts cover every person, not the cut
    assert [p["person_id"] for p in small["persons"]][:2] == ["Eccles", "Baynes"]


def test_place_can_be_given_as_id_name_or_alias():
    for ref in ("common", "Oxshott Common", "the Common", "oxshott common"):
        assert board(place=ref, victim_ids=["Victim"])["place_id"] == "common"
    assert board()["place"] == "Oxshott Common"


def test_window_in_another_day_or_time_places_nobody():
    other_day = board(window=tools.Window(story_day=DAY + 1, start_min=60, end_min=60))
    assert other_day["counts"] == {"excluded": 0, "placed": 0, "not_excluded": 7}
    other_time = board(window=tools.Window(story_day=DAY, start_min=300, end_min=300))
    assert other_time["counts"]["excluded"] == other_time["counts"]["placed"] == 0


def test_no_persons_is_insufficient_evidence():
    empty = Src(FactBase(story="s", places=[PlaceRec(id="common", name="Oxshott Common")]))
    out = tools.scene_board(empty, story="s", place="common", window=WINDOW)
    assert out["status"] == "insufficient_evidence" and out["persons"] == []
    assert out["counts"] == {"excluded": 0, "placed": 0, "not_excluded": 0}


@pytest.mark.parametrize(
    "kw,code",
    [
        ({"place": "Atlantis"}, "not_found"),
        ({"limit": 0}, "invalid_input"),
        ({"limit": 51}, "invalid_input"),
        ({"place": ""}, "invalid_input"),
    ],
)
def test_errors(kw, code):
    with pytest.raises(ToolError) as e:
        board(**kw)
    assert e.value.code == code


def test_unknown_story_is_not_found():
    with pytest.raises(ToolError) as e:
        tools.scene_board(fixture(), story="nope", place="common", window=WINDOW)
    assert e.value.code == "not_found"


def test_check_alibi_is_unchanged():
    """The refactor behind `scene_board` must not change `check_alibi`."""
    out = tools.check_alibi(
        fixture(), story="s", person_id="Eccles", window=WINDOW, claimed_place_id="common"
    )
    assert out["status"] == "contradicted" and out["explanation"]["rule_id"] == "R1"
    with pytest.raises(ToolError):
        tools.check_alibi(fixture(), story="s", person_id="Zed", window=WINDOW)
