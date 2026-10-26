import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts" / "spike"))
_spec = importlib.util.spec_from_file_location(
    "score_pipeline", ROOT / "scripts" / "spike" / "score_pipeline.py"
)
sp = importlib.util.module_from_spec(_spec)
sys.modules["score_pipeline"] = sp
_spec.loader.exec_module(sp)

TEXT = "Holmes said, “I saw Mr. Smith at nine o’clock near the mill.” Smith denied it."


def make_gold(tmp_path):
    g = {
        "chunk_id": "c1",
        "story": "s",
        "text": TEXT,
        "gold": {
            "entities": [{"name": "Smith", "type": "person", "quote": "Mr. Smith"}],
            "claims": [
                {
                    "speaker": "Holmes",
                    "content": "saw Smith at nine",
                    "quote": "I saw Mr. Smith at nine o’clock",
                }
            ],
            "relations": [],
        },
    }
    d = tmp_path / "gold"
    d.mkdir()
    (d / "c1.json").write_text(json.dumps(g), encoding="utf-8")
    return d


def rec(status="ok", **extra):
    base = {
        "chunk_id": "c1", "story": "s", "status": status, "truncated": False, "cached": False,
        "wall_s": 4.0, "grounding": {"exact": 2, "fuzzy": 0, "none": 0}, "dropped": [],
        "extraction": {
            "entities": [
                {"name": "Smith", "type": "person", "quote": "Mr. Smith", "grounded": "exact"},
                {"name": "mill", "type": "place", "quote": "the mill", "grounded": "exact"},
            ],
            "events": [
                {"description": "meeting", "quote": "I saw Mr. Smith", "in_speech": True,
                 "grounded": "exact"},
            ],
            "claims": [
                {"speaker": "Holmes", "content": "saw Smith at nine", "about_person": "Smith",
                 "about_time_text": "nine o’clock", "polarity": "affirm", "grounded": "exact",
                 "quote": "I saw Mr. Smith at nine o’clock"},
            ],
        },
    }  # fmt: skip
    base.update(extra)
    return base


def write(tmp_path, *recs):
    p = tmp_path / "out.jsonl"
    p.write_text("".join(json.dumps(r) + "\n" for r in recs), encoding="utf-8")
    return p


def test_scores_v2_output(tmp_path):
    r = sp.score_file(write(tmp_path, rec()), make_gold(tmp_path))
    assert r["json_validity_rate"] == 1.0 and r["status_ok_rate"] == 1.0
    assert r["quote_grounding_rate"] == 1.0
    assert r["claims"]["tp"] == 1 and r["claims"]["f1"] == 1.0
    assert r["entities"]["precision"] == 0.5 and r["entities"]["recall"] == 1.0
    assert r["overlap"]["claims"]["recall"] == 1.0
    fill = r["fill"]
    assert fill["claim_about_person"] == 1.0 and fill["claim_about_place"] == 0.0
    assert fill["claim_about_time_text"] == 1.0 and fill["claim_polarity_deny"] == 0.0
    assert fill["event_in_speech"] == 1.0 and fill["event_transit"] == 0.0
    assert r["sec_per_chunk"] == 4.0


def test_failed_and_missing_chunks_count_as_invalid(tmp_path):
    gold = make_gold(tmp_path)
    failed = sp.score_file(write(tmp_path, rec("failed", extraction={})), gold)
    assert failed["json_validity_rate"] == 0.0 and failed["claims"]["recall"] == 0.0
    missing = sp.score_file(write(tmp_path), gold)
    assert missing["n_missing"] == 1 and missing["fill"]["event_transit"] is None
    assert missing["sec_per_chunk"] is None


def test_repaired_is_usable_but_not_ok(tmp_path):
    r = sp.score_file(write(tmp_path, rec("repaired")), make_gold(tmp_path))
    assert r["json_validity_rate"] == 1.0 and r["status_ok_rate"] == 0.0


def test_cli_table_and_markdown(tmp_path, capsys):
    gold, out = make_gold(tmp_path), write(tmp_path, rec())
    md = tmp_path / "t.md"
    assert sp.main([str(out), "--gold", str(gold), "--markdown", str(md)]) == 0
    printed = capsys.readouterr().out
    assert "out" in printed and "100%" in printed
    assert md.read_text().startswith("| run |")
