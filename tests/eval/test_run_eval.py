import json
import os
from types import SimpleNamespace

import pytest

from .conftest import load

R = load("run_eval")


def _short(out):
    assert R.main(["--short", "--quiet", "--out", str(out)]) == 0
    return json.loads(next(out.glob("*.json")).read_text())


def test_short_mode_runs_offline_and_writes_the_report(tmp_path):
    result = _short(tmp_path)
    files = sorted(p.name for p in tmp_path.iterdir())
    assert [f.rsplit(".", 1)[1] for f in files] == ["json", "md", "svg"]
    meta = result["meta"]
    assert meta["short"] and meta["split"] == "dev" and len(meta["config_hash"]) == 12
    assert f"-{meta['git_sha'][:7]}-{meta['config_hash']}-" in files[0], (
        "commit and config in the name"
    )
    assert "AI-written" in meta["gold_note"]
    assert meta["presence"]["fixture"] == "demo" and meta["presence"]["rule_tools"]
    s = result["summary"]
    assert s["vector+rerank"]["status"] == "not run"
    for cfg in ("bare", "vector", "hybrid+graph"):
        assert s[cfg]["n"] == len(R.SHORT_IDS)
        assert s[cfg]["errors"] == 0
        assert s[cfg]["behaviour_correct"]["n"] == len(R.SHORT_IDS)
    assert "answers_all_citations_correct" in s["hybrid+graph"]
    assert "citation_correct_per_citation" in s["hybrid+graph"]
    assert "citation_correct_per_citation" not in s["bare"]
    assert s["hybrid+graph"]["sentence_recall"].startswith("not computed"), (
        "no sentence index in the fixture"
    )
    assert set(s["paired_behaviour_correct"]) == {
        "bare vs vector",
        "bare vs hybrid+graph",
        "vector vs hybrid+graph",
    }
    md = (tmp_path / files[1]).read_text()
    for text in (
        "not run",
        "Wilson",
        "issue #9",
        "not computed",
        "0 by construction",
        "vector gate min_score",
    ):
        assert text in md, text
    rows = result["rows"]
    assert {r["config"] for r in rows} == {"bare", "vector", "hybrid+graph"}
    vector_k = [r for r in rows if r["config"] == "vector"]
    assert all(r["recall@6"] is None for r in vector_k), "a 4-chunk run says nothing about @6"
    c = result["contradictions"]
    counted = sum(c["all"][k] for k in ("tp", "fp", "fn", "tn"))
    assert counted + c["skipped"] == meta["n_contradictions"]


def test_the_vector_arm_has_its_own_gate_threshold():
    stack = R.build_stack(True, 0.0)
    try:
        gates = [
            ev.gate
            for ev in stack.agents["vector"].ask("What kind of snake killed Dr. Grimesby Roylott?")
            if ev.type == "retrieval_results"
        ]
    finally:
        stack.close()
    assert gates and gates[0].passed, "one RRF arm tops out at 1/61, below the two-arm 0.018"
    assert gates[0].threshold == 0.0
    assert gates[0].best_score < 0.018


def test_the_fixture_flavour_is_pinned_and_restored():
    before = os.environ.get("DETECTIVE_BOARD_FIXTURE")
    stack = R.build_stack(True, 0.0)
    stack.close()
    assert os.environ.get("DETECTIVE_BOARD_FIXTURE") == before
    assert type(stack.tools).__name__ == "InProcessRulesClient", (
        "the demo flavour runs the real rules"
    )


def test_sentence_recall_overlap_and_missing_index():
    gold = {"spans": [("s", 100, 140)], "chunks": ["s-0001"]}
    hits = [
        SimpleNamespace(chunk_id="s-0001", story="s", start=0, end=10),
        SimpleNamespace(chunk_id="s-0001", story="s", start=45, end=60),
    ]
    res = SimpleNamespace(hits=hits, chunks={"s-0001": SimpleNamespace(char_start=60)})
    retr = SimpleNamespace(sentence_search=lambda q, k: res)
    out = R.sentence_recall(retr, {"question": "q"}, gold)
    assert out == {
        "sentence_recall@1": False,
        "sentence_recall@5": True,
        "sentence_recall@20": True,
    }
    none = R.sentence_recall(
        SimpleNamespace(sentence_search=lambda q, k: None), {"question": "q"}, gold
    )
    assert set(none.values()) == {None}


def test_test_split_needs_a_clean_tree(monkeypatch):
    monkeypatch.setattr(R, "git_state", lambda: ("abc", True))
    with pytest.raises(SystemExit, match="frozen"):
        R.main(["--split", "test", "--quiet"])


def test_split_all_follows_the_test_protocol(monkeypatch, tmp_path):
    monkeypatch.setattr(R, "git_state", lambda: ("abc", True))
    with pytest.raises(SystemExit, match="frozen"):
        R.main(["--split", "all", "--quiet"])
    (tmp_path / "eval-2026-10-28-all-abcdef0-0123456789ab-120000.json").write_text("{}")
    assert R.previous_test_runs(tmp_path, "abcdef0123", "0123456789ab")


def test_a_test_run_is_recorded_once_and_never_overwritten(tmp_path):
    meta = {
        "date": "2026-10-28",
        "time": "120000",
        "split": "test",
        "short": False,
        "git_sha": "abcdef0123",
        "config_hash": "0123456789ab",
    }
    stem = R.result_stem(tmp_path, meta)
    assert stem.name == "eval-2026-10-28-test-abcdef0-0123456789ab-120000"
    stem.with_suffix(".json").write_text("{}")
    assert R.previous_test_runs(tmp_path, "abcdef0123", "0123456789ab") == [
        stem.with_suffix(".json")
    ]
    assert R.previous_test_runs(tmp_path, "abcdef0123", "ffffffffffff") == []
    result = {"meta": meta, "summary": {}, "contradictions": {}}
    with pytest.raises(SystemExit, match="overwrite"):
        R.write(result, tmp_path)


def test_short_mode_uses_only_dev_questions():
    split = json.loads(R.SPLIT.read_text())["content"]["golden"]
    assert set(R.SHORT_IDS) <= set(split["dev"])


def test_short_mode_is_deterministic(tmp_path):
    def rows(out):
        result = _short(out)
        timeless = [
            {k: v for k, v in r.items() if k not in ("ttft_s", "total_s")} for r in result["rows"]
        ]
        return timeless, result["contradiction_rows"], result["meta"]["config_hash"]

    assert rows(tmp_path / "a") == rows(tmp_path / "b")
