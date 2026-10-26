import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts" / "spike"))
import symbolic_readiness as sr  # noqa: E402

TEXT = "Mrs. Hale came to the inn at six o’clock. The cook said, “I never saw the doctor.”"


def gold_dir(tmp_path):
    g = {
        "chunk_id": "c1",
        "story": "s",
        "text": TEXT,
        "gold": {
            "entities": [],
            "events": [
                {
                    "description": "Hale came",
                    "participants": ["Mrs. Hale"],
                    "time_text": "six o’clock",
                    "quote": "Mrs. Hale came to the inn at six o’clock",
                }
            ],
            "claims": [],
            "relations": [],
        },
    }
    d = tmp_path / "gold"
    d.mkdir()
    (d / "c1.json").write_text(json.dumps(g), encoding="utf-8")
    return d


def rec(events, claims, wall_s=10.0):
    return {
        "chunk_id": "c1", "story": "s", "status": "ok", "truncated": False, "cached": False,
        "wall_s": wall_s, "grounding": {"exact": 2, "fuzzy": 0, "none": 0}, "dropped": [],
        "extraction": {"entities": [], "events": events, "claims": claims},
    }  # fmt: skip


GOOD_EV = {
    "description": "Hale came", "participants": ["Hale", "the cook"], "time_text": "six o’clock",
    "place": "the inn", "in_speech": False, "quote": "Mrs. Hale came to the inn at six o’clock",
}  # fmt: skip
BAD_EV = {
    "description": "x", "participants": [], "time_text": "six o’clock", "place": "the mill",
    "in_speech": True, "quote": "The cook said",
}  # fmt: skip
GOOD_CL = {
    "speaker": "the cook", "content": "never saw the doctor", "about_person": "the doctor",
    "polarity": "deny", "quote": "I never saw the doctor",
}  # fmt: skip
BAD_CL = {
    "speaker": "the cook", "content": "x", "about_person": "Moriarty", "about_place": "Paris",
    "polarity": "affirm", "quote": "I never saw the doctor",
}  # fmt: skip


def run(tmp_path, *recs):
    p = tmp_path / "out.jsonl"
    p.write_text("".join(json.dumps(r) + "\n" for r in recs), encoding="utf-8")
    gd = gold_dir(tmp_path)
    return sr.score_run(sr.sp.se.load_gold(gd), sr.sp.load_results(p), gd)


def test_helpers():
    assert sr.contains("at six o’clock sharp", "Six o'clock")
    assert not sr.contains("at six", "")
    assert sr.same_person("Hale", "Mrs. Hale") and not sr.same_person("Hale", "Smith")
    assert sr.quote_overlap("a b c d", "a b") == 1.0


def test_good_run(tmp_path):
    r = run(tmp_path, rec([GOOD_EV], [GOOD_CL]))
    assert r["ev_participants_nonempty"] == 1.0
    assert r["ev_participants_P"] == 0.5 and r["ev_participants_R"] == 1.0
    assert r["ev_time_in_quote"] == 1.0 and r["ev_place_in_quote"] == 1.0
    assert r["cl_deny"] == 1.0 and r["cl_about_person_grounded"] == 1.0
    assert r["json_validity"] == 1.0 and r["sec_per_chunk"] == 10.0


def test_bad_run_is_penalised(tmp_path):
    r = run(tmp_path, rec([BAD_EV], [BAD_CL]))
    assert r["ev_participants_nonempty"] == 0.0 and r["ev_participants_P"] is None
    assert r["ev_matched_gold"] == 0.0 and r["ev_participants_R"] is None
    assert r["ev_time_in_quote"] == 0.0 and r["ev_place_in_quote"] == 0.0
    assert r["ev_in_speech"] == 1.0 and r["cl_deny"] == 0.0
    assert r["cl_about_person_grounded"] == 0.0 and r["cl_about_place_grounded"] == 0.0


def test_failed_chunk_gives_none_rates(tmp_path):
    bad = rec([], [])
    bad["status"] = "failed"
    r = run(tmp_path, bad)
    assert r["json_validity"] == 0.0 and r["ev_participants_nonempty"] is None


def test_cli_writes_markdown(tmp_path, capsys):
    out = tmp_path / "v22.jsonl"
    out.write_text(json.dumps(rec([GOOD_EV], [GOOD_CL])) + "\n", encoding="utf-8")
    md_dir = tmp_path / "md"
    argv = [str(out), "--gold", str(gold_dir(tmp_path)), "--stamp", "t", "--md-dir", str(md_dir)]
    assert sr.main(argv) == 0
    text = (md_dir / "prompt-v2-2-t.md").read_text()
    assert "| metric | v22 |" in text and "Caveats" in text
    assert "event participants non-empty" in capsys.readouterr().out
