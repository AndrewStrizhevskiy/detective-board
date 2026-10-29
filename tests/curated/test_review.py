"""Human re-check of the curated files (issue #22): the fields, and the phrase the answers use."""

from pathlib import Path

import pytest

from detective_board.extract import curated_schema
from detective_board.extract.curated import load_file as load_facts
from detective_board.extract.curated_schema import (
    CURATED_REVIEW,
    REVIEW_PENDING,
    CuratedFact,
    review_phrase,
    review_status,
)
from detective_board.extract.scenes import SCENE_MARK, Scene
from detective_board.extract.scenes import load_file as load_scenes

ROOT = Path(__file__).resolve().parents[2]


def test_the_shown_phrase_matches_the_data_files():
    facts = load_facts(ROOT / "data" / "curated" / "presence_demo.jsonl")
    scenes = load_scenes(ROOT / "data" / "curated" / "scenes.jsonl")
    pairs = [(r.reviewed_by, r.reviewed_on) for r in [*facts, *scenes]]
    assert CURATED_REVIEW == review_status(pairs)
    assert SCENE_MARK.endswith(CURATED_REVIEW)


def test_review_status():
    assert review_status([]) == REVIEW_PENDING
    assert review_status([("a", "2026-10-29"), (None, None)]) == REVIEW_PENDING
    done = review_status([("a", "2026-10-29"), ("a", "2026-10-29")])
    assert done == review_phrase("a", "2026-10-29") == "human re-check done by a on 2026-10-29"
    two = review_status([("b", "2026-10-29"), ("a", "2026-10-30")])
    assert two == "human re-check done by a and b on 2026-10-29 and 2026-10-30"


FACT = {
    "id": "x",
    "story": "s",
    "person": "P",
    "place": "Q",
    "time_text": "at one o'clock",
    "source": "narrator",
    "quote": "q",
    "curated_by": "team",
    "note": "n",
}


@pytest.mark.parametrize(
    "extra",
    [
        {"reviewed_by": "LitrumCoder"},
        {"reviewed_on": "2026-10-29"},
        {"reviewed_by": "not a login!", "reviewed_on": "2026-10-29"},
        {"reviewed_by": "LitrumCoder", "reviewed_on": "29.10.2026"},
    ],
)
def test_bad_review_fields_are_rejected(extra):
    with pytest.raises(ValueError):
        CuratedFact.model_validate(FACT | extra)


def test_review_fields_on_facts_and_scenes():
    ok = {"reviewed_by": "LitrumCoder", "reviewed_on": "2026-10-29"}
    assert CuratedFact.model_validate(FACT | ok).reviewed_by == "LitrumCoder"
    scene = Scene.model_validate(
        {
            "id": "s1",
            "story": "s",
            "place": "Q",
            "day_key": "d",
            "time_text": "one o'clock",
            "start_min": 60,
            "end_min": 60,
            "victim": "V",
            "titles": ["T"],
            "quote": "q",
            "curated_by": "team",
            "note": "n",
        }
        | ok
    )
    assert scene.reviewed_on == "2026-10-29"
    with pytest.raises(ValueError):
        Scene.model_validate(scene.model_dump() | {"reviewed_on": None})


def test_pending_is_the_default_until_the_files_are_checked():
    assert curated_schema.REVIEW_PENDING == "human re-check pending"
