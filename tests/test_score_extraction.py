import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
_spec = importlib.util.spec_from_file_location(
    "score_extraction", ROOT / "scripts" / "spike" / "score_extraction.py"
)
se = importlib.util.module_from_spec(_spec)
sys.modules["score_extraction"] = se
_spec.loader.exec_module(se)

from detective_board.extract.schema import Extraction, ollama_format_schema  # noqa: E402

TEXT = "Holmes said, “I saw Mr. Smith at nine o’clock near the mill.” Smith denied it."


def gold(tmp_path=None):
    ex = Extraction.model_validate(
        {
            "entities": [
                {"name": "Sherlock Holmes", "type": "person", "aliases": ["Holmes"], "quote": "Holmes said"},
                {"name": "Smith", "type": "person", "quote": "Mr. Smith"},
                {"name": "the mill", "type": "place", "quote": "the mill"},
            ],
            "claims": [
                {"speaker": "Holmes", "content": "saw Smith at nine", "quote": "I saw Mr. Smith at nine o’clock"}
            ],
            "relations": [
                {"subject": "Smith", "predicate": "near", "object": "the mill", "quote": "Mr. Smith at nine o’clock near the mill"}
            ],
        }
    )
    return {"c1": {"text": TEXT, "gold": ex}}


def pred(extraction=None, output=None):
    rec = {"chunk_id": "c1"}
    if extraction is not None:
        rec["extraction"] = extraction
    if output is not None:
        rec["output"] = output
    return {"c1": rec}


def test_norm_strips_titles_and_possessive():
    assert se.norm("Mr. Sherlock Holmes") == "sherlock holmes"
    assert se.norm("Smith’s") == "smith"


def test_token_f1():
    assert se.token_f1("a b c", "a b c") == 1.0
    assert se.token_f1("a b", "c d") == 0.0
    assert 0.5 < se.token_f1("a b c d", "a b c") < 1.0


def test_quote_grounding_substring_and_whitespace():
    assert se.quote_grounded("Smith  denied\nit", TEXT)
    assert not se.quote_grounded("Smith confessed", TEXT)
    assert not se.quote_grounded("", TEXT)


def test_perfect_prediction():
    g = gold()
    res = se.score(g, pred(extraction=g["c1"]["gold"].model_dump()))
    assert res["json_validity_rate"] == 1.0
    assert res["quote_grounding_rate"] == 1.0
    for k in ("entities", "claims", "relations"):
        assert res[k]["f1"] == 1.0


def test_invalid_json_and_missing_chunk_count_as_misses():
    g = gold()
    res = se.score(g, pred(output="{not json"))
    assert res["json_validity_rate"] == 0.0
    assert res["entities"]["recall"] == 0.0
    assert se.score(g, {})["json_validity_rate"] == 0.0


def test_schema_violation_is_invalid():
    res = se.score(gold(), pred(extraction={"entities": [{"name": "x", "type": "dragon", "quote": "x"}]}))
    assert res["json_validity_rate"] == 0.0


def test_entity_alias_match_and_precision():
    out = {
        "entities": [
            {"name": "Holmes", "type": "person", "quote": "Holmes said"},  # matches alias
            {"name": "Watson", "type": "person", "quote": "Holmes said"},  # spurious
        ]
    }
    res = se.score(gold(), pred(output=json.dumps(out)))
    e = res["entities"]
    assert e["tp"] == 1 and e["n_pred"] == 2 and e["n_gold"] == 3
    assert e["precision"] == 0.5


def test_claim_requires_speaker_and_quote_overlap():
    base = {"speaker": "Holmes", "content": "x", "quote": "I saw Mr. Smith at nine o’clock"}
    ok = se.score(gold(), pred(extraction={"claims": [base]}))
    assert ok["claims"]["tp"] == 1
    wrong_speaker = dict(base, speaker="Smith")
    assert se.score(gold(), pred(extraction={"claims": [wrong_speaker]}))["claims"]["tp"] == 0
    wrong_quote = dict(base, quote="near the mill")
    assert se.score(gold(), pred(extraction={"claims": [wrong_quote]}))["claims"]["tp"] == 0


def test_relation_match_via_alias_subject():
    r = {"subject": "Mr. Smith", "predicate": "x", "object": "y", "quote": "Mr. Smith at nine o’clock near the mill"}
    assert se.score(gold(), pred(extraction={"relations": [r]}))["relations"]["tp"] == 1


def test_ungrounded_quote_lowers_grounding_rate():
    out = {
        "entities": [
            {"name": "Smith", "type": "person", "quote": "Mr. Smith"},
            {"name": "Jones", "type": "person", "quote": "Mr. Jones never existed"},
        ]
    }
    res = se.score(gold(), pred(extraction=out))
    assert res["quote_grounding_rate"] == 0.5 and res["n_quotes"] == 2


def test_ollama_schema_inlined():
    s = json.dumps(ollama_format_schema())
    assert "$ref" not in s and "$defs" not in s
    assert ollama_format_schema()["properties"].keys() == {"entities", "events", "claims", "relations"}


def test_real_gold_files_are_valid_and_grounded():
    g = se.load_gold(ROOT / "eval" / "extraction_gold")
    assert len(g) == 12
    for cid, d in g.items():
        x = d["gold"]
        for item in (*x.entities, *x.events, *x.claims, *x.relations):
            assert item.quote in d["text"], (cid, item.quote)
    # gold scored against itself is perfect
    preds = {cid: {"chunk_id": cid, "extraction": d["gold"].model_dump()} for cid, d in g.items()}
    res = se.score(g, preds)
    assert res["quote_grounding_rate"] == 1.0 and res["claims"]["f1"] == 1.0
