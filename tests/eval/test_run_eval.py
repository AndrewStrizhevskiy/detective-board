import json

from .conftest import load

R = load("run_eval")


def test_short_mode_runs_offline_and_writes_the_report(tmp_path):
    rc = R.main(["--short", "--quiet", "--out", str(tmp_path)])
    assert rc == 0
    files = sorted(p.name for p in tmp_path.iterdir())
    assert [f.rsplit(".", 1)[1] for f in files] == ["json", "md", "svg"]
    result = json.loads((tmp_path / files[0]).read_text())
    s = result["summary"]
    assert s["vector+rerank"]["status"] == "not run"
    for cfg in ("bare", "vector", "hybrid+graph"):
        assert s[cfg]["n"] == len(R.SHORT_IDS)
        assert s[cfg]["errors"] == 0
        assert s[cfg]["behaviour_correct"]["n"] == len(R.SHORT_IDS)
    assert "citation_correct" in s["hybrid+graph"] and "citation_correct" not in s["bare"]
    assert set(s["paired_behaviour_correct"]) == {
        "bare vs vector",
        "bare vs hybrid+graph",
        "vector vs hybrid+graph",
    }
    meta = result["meta"]
    assert meta["short"] and meta["split"] == "dev" and len(meta["config_hash"]) == 12
    assert "AI-written" in meta["gold_note"]
    md = (tmp_path / files[1]).read_text()
    assert "not run" in md and "Wilson" in md and "issue #9" in md
    rows = result["rows"]
    assert {r["config"] for r in rows} == {"bare", "vector", "hybrid+graph"}
    assert all(r["split"] == "dev" for r in rows)
    assert (
        result["contradictions"]["skipped"]
        + sum(
            v for k, v in result["contradictions"]["all"].items() if k in ("tp", "fp", "fn", "tn")
        )
        == meta["n_contradictions"]
    )


def test_test_split_needs_a_clean_tree(monkeypatch):
    monkeypatch.setattr(R, "git_state", lambda: ("abc", True))
    try:
        R.main(["--split", "test", "--quiet"])
    except SystemExit as e:
        assert "frozen" in str(e)
    else:
        raise AssertionError("a dirty test-split run must be refused")


def test_short_mode_uses_only_dev_questions():
    split = json.loads(R.SPLIT.read_text())["content"]["golden"]
    assert set(R.SHORT_IDS) <= set(split["dev"])


def test_short_mode_is_deterministic(tmp_path):
    def rows(out):
        R.main(["--short", "--quiet", "--out", str(out)])
        result = json.loads(next(out.glob("*.json")).read_text())
        timeless = [
            {k: v for k, v in r.items() if k not in ("ttft_s", "total_s")} for r in result["rows"]
        ]
        return timeless, result["contradiction_rows"], result["meta"]["config_hash"]

    assert rows(tmp_path / "a") == rows(tmp_path / "b")
