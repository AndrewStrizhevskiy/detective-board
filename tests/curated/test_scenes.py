"""Curated crime scenes (docs/symbolic-layer.md 11.6): schema, loader, validation, matching."""

import json
from pathlib import Path

import pytest

from detective_board.extract import scenes
from detective_board.extract.curated_schema import curated_day
from detective_board.extract.scenes import SCENE_CURATED_BY, Scene

ROOT = Path(__file__).resolve().parents[2]
FILE = ROOT / scenes.DEFAULT_FILE
WL = "wisteria-lodge"

CLEAN = (
    "Gregson said that Garcia was found dead on the Common.\n\n"
    "“He had been there since one o’clock. There was rain about that time.”\n"
)
BASE = {
    "id": "t-common-one",
    "story": "wl",
    "place": "Oxshott Common",
    "day_key": "the-night",
    "time_text": "since one o’clock",
    "start_min": 60,
    "end_min": 60,
    "victim": "Aloysius Garcia",
    "victim_aliases": ["Garcia"],
    "titles": ["Wisteria Lodge"],
    "quote": "He had been there since one o’clock.",
    "curated_by": SCENE_CURATED_BY,
    "note": "place and victim are resolved from the context of the preceding line",
    "inferred": ["place", "victim"],
}


def make(**kw) -> Scene:
    return Scene.model_validate(BASE | kw)


# ---- the data file ---------------------------------------------------------
@pytest.fixture(scope="module")
def real():
    if not FILE.exists():
        pytest.skip("scenes file not available")
    return scenes.load_file(FILE)


def test_file_is_valid_labelled_and_wisteria_is_there(real):
    assert {s.id for s in real} >= {"wisteria-oxshott-one-oclock"}
    assert len({s.id for s in real}) == len(real)
    assert all(s.curated_by == SCENE_CURATED_BY and s.note.strip() for s in real)
    wl = next(s for s in real if s.story == WL)
    assert (wl.place, wl.start_min, wl.end_min, wl.victim) == (
        "Oxshott Common",
        60,
        60,
        "Aloysius Garcia",
    )
    assert wl.quote == "He had been there since one o’clock."
    assert wl.story_day == curated_day(WL, "night-of-the-murder")  # same day as the c001 facts


def test_real_scenes_are_grounded_in_the_clean_text_and_the_graph_places(real):
    clean = {s.story: (ROOT / "data" / "clean" / f"{s.story}.txt").read_text("utf-8") for s in real}
    assert scenes.validate(real, clean) == []
    for s in real:
        assert scenes.locate_quote(clean[s.story], s.quote) is not None


def test_real_scene_day_key_is_one_the_curated_presence_facts_use(real):
    from detective_board.extract import curated

    keys = {(f.story, f.day_key) for f in curated.load_file(ROOT / curated.DEFAULT_FILE)}
    for s in real:
        assert (s.story, s.day_key) in keys, s.id


def test_load_index_anchors_the_quote_and_is_idempotent(real):
    a = scenes.load_index(FILE)
    b = scenes.load_index(FILE)
    assert a == b and a.scenes == tuple(real)
    anchor = a.anchor(a.scenes[0])
    assert anchor is not None and anchor.story == WL and anchor.quote == a.scenes[0].quote
    text = (ROOT / "data" / "clean" / f"{WL}.txt").read_text("utf-8")
    assert text[anchor.char_start : anchor.char_end] == anchor.quote  # absolute offsets


def test_cli_validates(real, capsys):
    assert scenes.main(["--file", str(FILE), "--clean-dir", str(ROOT / "data" / "clean")]) == 0
    assert "valid" in capsys.readouterr().out


# ---- validation ------------------------------------------------------------
def test_sound_scene_has_no_problems():
    assert scenes.problems(make(), CLEAN) == []
    assert make().story_day == curated_day("wl", "the-night")


def test_quote_must_be_verbatim():
    assert scenes.problems(make(quote="He had been there since two o’clock."), CLEAN) == [
        "t-common-one: quote is not a verbatim span of the story text"
    ]
    # whitespace and quotation-mark variants are the same text
    assert scenes.problems(make(quote="He had been  there since one o'clock."), CLEAN) == []


def test_time_must_be_in_the_quote_exact_and_equal_to_the_window():
    out = scenes.problems(make(time_text="at midnight"), CLEAN)
    assert any("not in the quote" in p for p in out)
    out = scenes.problems(make(start_min=120, end_min=120), CLEAN)
    assert any("differs from the time_text" in p for p in out)
    vague = CLEAN.replace("since one o’clock", "in the morning")
    out = scenes.problems(
        make(quote="He had been there in the morning.", time_text="in the morning"), vague
    )
    assert any("not an exact clock time" in p for p in out)


def test_place_and_victim_must_be_in_the_quote_or_inferred():
    out = scenes.problems(make(inferred=[]), CLEAN)
    assert any("place 'Oxshott Common' is not in the quote" in p for p in out)
    assert any("victim 'Aloysius Garcia' is not in the quote" in p for p in out)
    clean = CLEAN.replace("He had been there", "Garcia lay dead on Oxshott Common")
    q = "Garcia lay dead on Oxshott Common since one o’clock."
    assert scenes.problems(make(quote=q, inferred=[]), clean) == []
    out = scenes.problems(make(quote=q, inferred=["place"]), clean)
    assert any("is in the quote but declared inferred" in p for p in out)


def test_inferred_slots_need_a_note_that_says_why():
    out = scenes.problems(make(note="checked"), CLEAN)
    assert any("need a note" in p for p in out)


def test_curated_by_label_is_enforced():
    out = scenes.problems(make(curated_by="somebody"), CLEAN)
    assert any("curated_by must be" in p for p in out)


def test_place_must_exist_in_the_graph_or_be_declared():
    assert scenes.problems(make(), CLEAN, {"The Oxshott Common", "Wisteria Lodge"}) == []
    out = scenes.problems(make(), CLEAN, {"Wisteria Lodge"})
    assert any("not in the graph; set place_declared" in p for p in out)
    assert scenes.problems(make(place_declared=True), CLEAN, {"Wisteria Lodge"}) == []


def test_validate_reports_a_missing_story_text():
    assert scenes.validate([make()], {}) == ["t-common-one: no clean text for story 'wl'"]


# ---- schema ----------------------------------------------------------------
@pytest.mark.parametrize(
    "kw",
    [
        {"start_min": 90, "end_min": 60},
        {"id": "Bad Id"},
        {"day_key": "Not Kebab"},
        {"titles": []},
        {"quote": "  "},
        {"extra_field": 1},
        {"inferred": ["time"]},
    ],
)
def test_schema_rejects(kw):
    with pytest.raises(ValueError):
        make(**kw)


def test_load_file_rejects_duplicates_and_reports_the_line(tmp_path):
    f = tmp_path / "scenes.jsonl"
    f.write_text(
        "# a comment\n\n" + json.dumps(BASE) + "\n" + json.dumps(BASE) + "\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match=r"scenes.jsonl:4: duplicate id"):
        scenes.load_file(f)
    f.write_text(json.dumps(BASE | {"start_min": 99}) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match=r"scenes.jsonl:1:"):
        scenes.load_file(f)


def data_dir(tmp_path, scene=BASE, clean=CLEAN):
    d = tmp_path / "data"
    (d / "curated").mkdir(parents=True)
    (d / "clean").mkdir()
    (d / "clean" / "wl.txt").write_text(clean, encoding="utf-8")
    rec = {
        "chunk_id": "wl-0000",
        "story": "wl",
        "char_start": 0,
        "char_end": len(clean),
        "text": clean,
    }
    (d / "chunks.jsonl").write_text(json.dumps(rec) + "\n", encoding="utf-8")
    (d / "curated" / "scenes.jsonl").write_text(json.dumps(scene) + "\n", encoding="utf-8")
    return d / "curated" / "scenes.jsonl"


def test_load_index_refuses_an_ungrounded_scene(tmp_path):
    ok = scenes.load_index(data_dir(tmp_path))
    assert ok.scenes[0].id == "t-common-one" and ok.anchor(ok.scenes[0]).chunk_id == "wl-0000"
    bad = tmp_path / "bad"
    bad.mkdir()
    path = data_dir(bad, BASE | {"quote": "He had been there since two o’clock."})
    with pytest.raises(ValueError, match="not a verbatim span"):
        scenes.load_index(path)


# ---- matching ----------------------------------------------------------------
def two():
    return [
        make(),
        make(
            id="t-pool",
            story="bv",
            place="Boscombe Pool",
            titles=["Boscombe Valley"],
            victim="Charles McCarthy",
            victim_aliases=[],
        ),
    ]


@pytest.mark.parametrize(
    "q,want",
    [
        ("Who could have been at Oxshott Common at one o'clock?", "t-common-one"),
        ("Who are the suspects in Wisteria Lodge?", "t-common-one"),
        ("Who are the suspects in the case of Garcia?", "t-common-one"),
        ("Who can be excluded by alibi in the Boscombe Valley case?", "t-pool"),
        ("who was at the boscombe pool", "t-pool"),
        ("Who are the suspects in Silver Blaze?", None),
        ("Who are the suspects?", None),
        # two stories named: a tie is ambiguous, never a guess
        ("Who could have been at Oxshott Common or at Boscombe Pool?", None),
        # more terms win
        ("Who could have been at Boscombe Pool and Boscombe Valley, not Wisteria Lodge?", "t-pool"),
    ],
)
def test_match_scene(q, want):
    got = scenes.match_scene(two(), q)
    assert (got.id if got else None) == want


def test_a_term_is_a_whole_word():
    assert scenes.match_scene(two(), "Who are the suspects in Garcias?") is None
    assert scenes.match_scene([], "Who could have been at Oxshott Common?") is None
    assert not scenes.SceneIndex() and scenes.SceneIndex().match("Oxshott Common") is None
