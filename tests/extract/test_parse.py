import json

import pytest

from detective_board.extract.parse import parse_output, repair_truncated, validate_items
from detective_board.extract.schema_v2 import Extraction, to_v1

from .conftest import good_output

FULL = good_output()


def test_strict_ok():
    p = parse_output(FULL)
    assert p.status == "ok" and len(p.data["entities"]) == 2


@pytest.mark.parametrize("cut", range(1, len(FULL) - 1, 7))
def test_every_truncation_point_gives_valid_json(cut):
    p = parse_output(FULL[:cut])
    assert p.status in ("repaired", "failed")
    if p.status == "repaired":
        assert isinstance(p.data, dict)
        for v in p.data.values():
            assert isinstance(v, list)
        # repaired content is a prefix of the full content
        full = json.loads(FULL)
        for k, items in p.data.items():
            assert items == full[k][: len(items)]


def test_truncated_mid_item_drops_last_incomplete():
    s = FULL[: FULL.index('"claims"')] + '"claims": [{"speaker": "James McC'
    p = parse_output(s)
    assert p.status == "repaired"
    assert len(p.data["events"]) == 1 and p.data["claims"] == []


def test_truncated_inside_string_after_complete_item():
    s = '{"entities": [{"name":"A","type":"person","quote":"A"}, {"name":"B","ty'
    p = parse_output(s)
    assert [e["name"] for e in p.data["entities"]] == ["A"]


def test_truncated_with_escaped_quote_and_braces_in_string():
    s = '{"claims":[{"speaker":"A","content":"x } ] \\" y","quote":"q"},{"speaker":"B","con'
    p = parse_output(s)
    assert p.status == "repaired" and len(p.data["claims"]) == 1
    assert p.data["claims"][0]["content"] == 'x } ] " y'


def test_fenced_and_garbage_prefix():
    assert parse_output("```json\n" + FULL + "\n```").status in ("ok", "repaired")
    assert parse_output("Sure! " + FULL).data is not None


def test_no_json_fails():
    assert parse_output("").status == "failed"
    assert parse_output("no braces here").status == "failed"
    assert parse_output("[1,2]").status == "failed"


def test_repair_is_deterministic():
    assert repair_truncated(FULL[:150]) == repair_truncated(FULL[:150])


def test_per_item_validation_keeps_valid_drops_invalid():
    data = {
        "entities": [
            {"name": "A", "type": "person", "quote": "A"},
            {"name": "B", "type": "dragon", "quote": "B"},  # bad enum
            {"type": "place", "quote": "x"},  # missing name
            {"name": "C", "type": "item", "quote": "  "},  # empty quote
            {"name": "A", "type": "person", "quote": "A"},  # duplicate
            "junk",
        ],
        "events": "oops",
        "claims": [{"speaker": "A", "content": "c", "quote": "q", "extra_key": 1}],
    }
    rep = validate_items(data)
    assert [e["name"] for e in rep.items["entities"]] == ["A"]
    assert len(rep.items["claims"]) == 1  # unknown key stripped, item kept
    reasons = sorted(d["reason"] for d in rep.dropped)
    assert "not_a_list" in reasons and "duplicate" in reasons and "empty_quote" in reasons
    assert "not_an_object" in reasons and len(rep.dropped) == 6


def test_v2_is_superset_of_v1_and_converts_down():
    from detective_board.extract.schema import Extraction as V1

    v1 = V1.model_validate({"entities": [{"name": "A", "type": "person", "quote": "A"}]})
    v2 = Extraction.model_validate(v1.model_dump())
    assert v2.entities[0].unnamed is False
    v2 = Extraction.model_validate(json.loads(FULL))
    assert v2.claims[0].polarity == "deny"
    down = to_v1(v2)
    assert isinstance(down, V1) and not hasattr(down.claims[0], "polarity")
    assert down.events[0].time_text == "nine o'clock"
