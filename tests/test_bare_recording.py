"""scripts/bare_recording.py: bare-model answers copied from an eval run for the split view (#13)."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "bare_recording", ROOT / "scripts" / "bare_recording.py"
)
assert _spec and _spec.loader
br = importlib.util.module_from_spec(_spec)
sys.modules["bare_recording"] = br
_spec.loader.exec_module(br)

META = {
    "date": "2026-10-28",
    "generator": "qwen3:4b-instruct",
    "machine": "laptop / x86_64 / Linux",
    "git_sha": "ab945e8ff16c60b22f560e0762b850c374ba41f6",
    "config_hash": "78b3bbb3f2a6",
    "split": "dev",
}


def _run(tmp_path, rows):
    src = tmp_path / "eval.json"
    src.write_text(json.dumps({"meta": META, "rows": rows}))
    out = tmp_path / "bare"
    return src, out


def test_the_answer_is_copied_unchanged_with_its_run(tmp_path):
    answer = "He was *not* killed by a snake.\n\nWait — correction:"
    rows = [
        {"id": "g001", "config": "bare", "answer": answer, "ttft_s": 0.8, "total_s": 39.0},
        {"id": "g001", "config": "hybrid+graph", "answer": "agent", "ttft_s": 1, "total_s": 2},
    ]
    src, out = _run(tmp_path, rows)
    assert br.main(["--eval", str(src), "--ids", "g001", "--out", str(out)]) == 0
    rec = json.loads((out / "g001.json").read_text(encoding="utf-8"))
    assert rec["answer"] == answer
    m = rec["meta"]
    assert m["label"] == "RECORDING" and m["kind"] == "bare model, no sources"
    assert m["question"] == "What kind of snake killed Dr. Grimesby Roylott?"
    assert (m["model"], m["git_sha"], m["ttft_s"], m["seconds"]) == (
        "qwen3:4b-instruct",
        "ab945e8",
        0.8,
        39.0,
    )
    assert "temperature 0" in m["call"] and "300-token" in m["call"]


@pytest.mark.parametrize("answer", [None, "   "])
def test_a_missing_or_empty_bare_answer_stops(tmp_path, answer):
    rows = (
        []
        if answer is None
        else [{"id": "g001", "config": "bare", "answer": answer, "ttft_s": 1, "total_s": 2}]
    )
    src, out = _run(tmp_path, rows)
    with pytest.raises(SystemExit):
        br.main(["--eval", str(src), "--ids", "g001", "--out", str(out)])
    assert not (out / "g001.json").exists()


def test_the_committed_recordings_match_their_eval_runs():
    for path in sorted((ROOT / "web" / "replay" / "bare").glob("*.json")):
        rec = json.loads(path.read_text(encoding="utf-8"))
        run = json.loads((ROOT / rec["meta"]["source"]).read_text(encoding="utf-8"))
        questions = {
            q["id"]: q["question"]
            for q in map(json.loads, (ROOT / "eval/golden/questions.jsonl").open())
        }
        assert br.recording(run, rec["meta"]["qid"], rec["meta"]["source"], questions) == rec, (
            path.name
        )


def test_the_recorded_call_settings_are_those_of_run_bare():
    """CALL is written into every recording; it must say what eval/run_eval.py run_bare() does."""
    src = (ROOT / "eval" / "run_eval.py").read_text(encoding="utf-8")
    body = src[src.index("def run_bare(") : src.index("def run_agent(")]
    assert "temperature=0.0" in body and "seed=42" in body and "num_predict=BARE_MAX_TOKENS" in body
    assert "BARE_MAX_TOKENS = 300" in src
    assert '[{"role": "user", "content": q["question"]}]' in body, "question only, no system prompt"
    assert "temperature 0, seed 42, 300-token cap" in br.CALL and "no system prompt" in br.CALL


def test_an_unknown_question_id_stops_with_a_message(tmp_path):
    rows = [{"id": "g999", "config": "bare", "answer": "x", "ttft_s": 1, "total_s": 2}]
    src, out = _run(tmp_path, rows)
    with pytest.raises(SystemExit, match="not in eval/golden"):
        br.main(["--eval", str(src), "--ids", "g999", "--out", str(out)])
