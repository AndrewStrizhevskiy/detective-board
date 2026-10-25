import pytest

from detective_board.agent.linking import link_person
from detective_board.agent.router import extract_names, parse_time_window
from detective_board.extract.schema import Entity, Extraction
from detective_board.graph import ChunkRef, GraphStore


def _chunk(cid: str, story: str, text: str) -> ChunkRef:
    return ChunkRef(cid, story, 0, len(text), text)


def _p(name, quote, *aliases):
    return Entity(name=name, type="person", aliases=list(aliases), quote=quote)


@pytest.fixture(scope="module")
def g():
    s = GraphStore()
    bv = "Mr. Charles McCarthy and his son James McCarthy met Mr. John Turner and Turner's girl."
    s.ingest(
        _chunk("bv-0001", "bv", bv),
        Extraction(
            entities=[
                _p("Charles McCarthy", "Mr. Charles McCarthy", "McCarthy"),
                _p("James McCarthy", "James McCarthy", "McCarthy"),
                _p("John Turner", "Mr. John Turner", "Turner"),
                Entity(name="Boscombe Pool", type="place", quote="met"),
            ]
        ),
    )
    other = "Alice Turner sat with Garcia."
    s.ingest(
        _chunk("ot-0001", "ot", other),
        Extraction(entities=[_p("Alice Turner", "Alice Turner", "Turner"), _p("Garcia", "Garcia")]),
    )
    return s


def test_extract_names_keeps_mc_names_whole():
    q = "Does James McCarthy's testimony contradict what the gamekeeper William Crowder saw?"
    assert extract_names(q) == ["James McCarthy", "William Crowder"]
    assert extract_names("Was MacDonald at the inn?") == ["MacDonald"]


def test_time_window_uses_night_and_morning_words():
    w, note = parse_time_window("Where was Garcia at about one o'clock on the night he died?")
    assert w["start_min"] == 60 and "a.m. (night)" in note
    assert parse_time_window("Where was he at nine o'clock at night?")[0]["start_min"] == 21 * 60
    assert parse_time_window("Where was he at seven in the morning?")[0]["start_min"] == 7 * 60
    assert parse_time_window("Where was he at nine?")[0]["start_min"] == 21 * 60


def test_exact_name_and_title_are_linked(g):
    link = link_person(g, extract_names("Did Mr. James McCarthy contradict himself?"))
    assert (link.status, link.person_id, link.story) == ("ok", "p:bv:james-mccarthy", "bv")
    assert "exact name/alias" in link.reason


def test_alias_shared_by_two_people_is_ambiguous(g):
    link = link_person(g, ["McCarthy"])
    assert link.status == "ambiguous" and link.person_id is None
    assert [c.id for c in link.candidates] == ["p:bv:charles-mccarthy", "p:bv:james-mccarthy"]
    assert "ambiguous" in link.note() and "Charles McCarthy" in link.note()


def test_story_from_retrieval_breaks_a_cross_story_tie(g):
    assert link_person(g, ["Turner"]).status == "ambiguous"
    link = link_person(g, ["Turner"], stories=["ot", "bv"])
    assert (link.status, link.person_id) == ("ok", "p:ot:alice-turner")
    link = link_person(g, ["Mr. Turner"], stories=["bv"])
    assert link.person_id == "p:bv:john-turner"


def test_surname_fallback_and_not_found(g):
    link = link_person(g, ["Aloysius Garcia"])
    assert link.person_id == "p:ot:garcia" and "surname 'Garcia'" in link.reason
    assert link_person(g, ["Moriarty"]).status == "not_found"
    assert link_person(g, []).status == "no_names"


def test_place_names_are_not_persons(g):
    link = link_person(g, ["Boscombe Pool", "John Turner"])
    assert link.person_id == "p:bv:john-turner"


def test_ambiguity_stops_the_search(g):
    link = link_person(g, ["McCarthy", "John Turner"])
    assert link.status == "ambiguous"  # the first person mentioned is not silently replaced
