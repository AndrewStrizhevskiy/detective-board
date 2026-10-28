"""`presence_table`: rows, speakers, denials, R1 conflicts, cap, errors (hand-built FactBase)."""

import pytest

from detective_board.mcp import tools
from detective_board.mcp.errors import ToolError
from detective_board.symbolic.api import Anchor, ClaimRec, EventRec, FactBase, PlaceRec, TimeSpec


def anc(q, start, chunk="c1"):
    return Anchor(story="s", chunk_id=chunk, char_start=start, char_end=start + len(q), quote=q)


class Src:
    def __init__(self, fb):
        self.fb = fb

    def load(self, story):
        if story != "s":
            raise ToolError("not_found", "unknown story")
        return self.fb


def t(lo, text):
    return TimeSpec(day=1, lo=lo, hi=lo, exact=True, confidence="high", time_text=text)


def make(n_extra=0):
    q1, q2, q3 = "G sat in the hall", "Eccles saw G at the door", "G was at the mill"
    events = [
        EventRec(
            id="e1",
            description="G at hall, noon",
            time=t(720, "noon"),
            place_ref="hall",
            participants=["G"],
            anchors=[anc(q1, 10)],
        ),
        EventRec(
            id="e2",
            description="G at door, noon",
            time=t(720, "noon"),
            place_ref="door",
            participants=["G"],
            anchors=[anc(q2, 100)],
            narrator=False,
        ),
        EventRec(id="e3", description="G somewhere", participants=["G"], anchors=[anc(q3, 200)]),
        EventRec(
            id="e4",
            description="G at mill",
            place_ref="mill",
            participants=["G"],
            anchors=[anc(q3, 300)],
            curated=True,
        ),
    ]
    claims = [
        ClaimRec(
            id="c1",
            speaker_id="Eccles",
            content="G at door, noon".replace("G at", "G was at"),
            anchors=[anc(q2, 100)],
        ),
        ClaimRec(
            id="c2",
            speaker_id="G",
            content="Aloysius G was not at the hall, noon",
            anchors=[anc("I was not at the hall", 400)],
        ),
    ]
    for i in range(n_extra):
        events.append(
            EventRec(
                id=f"x{i}",
                description=f"G at spot{i}",
                place_ref=f"spot{i}",
                participants=["G"],
                anchors=[anc("filler quote text", 1000 + i * 50)],
            )
        )
    places = [PlaceRec(id="hall", name="the hall"), PlaceRec(id="door", name="the door")]
    return Src(FactBase(story="s", places=places, events=events, claims=claims))


def test_rows_speakers_denials_and_conflict():
    out = tools.presence_table(make(), story="s", person_id="G", names=["Aloysius G"])
    assert out["status"] == "ok" and out["person_id"] == "G" and out["provenance"] == "derived"
    by = {r["row_id"]: r for r in out["rows"]}
    assert set(by) == {"e1", "e2", "e4", "c2"}  # e3 has no place; it is only counted
    assert out["events_without_place"] == 1 and out["total_rows"] == 4
    assert by["e1"]["narrator"] and by["e1"]["speaker_id"] is None
    assert by["e1"]["place"] == "the hall" and by["e1"]["time_text"] == "noon"
    assert by["e2"]["speaker_id"] == "Eccles" and not by["e2"]["narrator"]
    assert by["e4"]["curated"] is True and by["e4"]["place"] == "mill"  # unknown id: surface form
    assert by["c2"]["polarity"] == "deny" and by["c2"]["speaker_id"] == "G"
    assert by["c2"]["place"] == "the hall" and by["c2"]["time_text"] == "noon"
    assert [r["row_id"] for r in out["rows"]] == ["e1", "e2", "e4", "c2"]  # narration order
    (conf,) = out["conflicts"]
    assert conf["rule"] == "R1" and set(conf["row_ids"]) == {"e1", "e2"}
    assert conf["provenance"] in ("derived", "conditional")


def test_denial_needs_the_person_names():
    out = tools.presence_table(make(), story="s", person_id="G")
    assert {r["row_id"] for r in out["rows"]} == {"e1", "e2", "e4"}


def test_cap_keeps_conflict_rows_and_reports_the_total():
    out = tools.presence_table(make(20), story="s", person_id="G", limit=3)
    ids = [r["row_id"] for r in out["rows"]]
    assert len(ids) == 3 and {"e1", "e2"} <= set(ids)
    assert out["truncated"] and out["total_rows"] == 23


def test_errors():
    with pytest.raises(ToolError) as e:
        tools.presence_table(make(), story="s", person_id="nobody")
    assert e.value.code == "not_found"
    with pytest.raises(ToolError) as e:
        tools.presence_table(make(), story="s", person_id="G", limit=0)
    assert e.value.code == "invalid_input"
