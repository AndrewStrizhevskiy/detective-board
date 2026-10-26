import importlib.util
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
_spec = importlib.util.spec_from_file_location(
    "server_report", ROOT / "scripts" / "server_report.py"
)
sr = importlib.util.module_from_spec(_spec)
sys.modules["server_report"] = sr
_spec.loader.exec_module(sr)

LIST = """NAME                 ID              SIZE      MODIFIED
qwen3:4b             359d7dd4bcda    2.5 GB    2 days ago
qwen3:4b-instruct    0edcdef34593    2.5 GB    2 days ago
bge-m3:latest        000000000000    1.2 GB    2 days ago
"""


def test_parse_models_table_real_file():
    t = sr.parse_models_table((ROOT / "docs/team/models.md").read_text(encoding="utf-8"))
    assert t["qwen3:4b"] == "359d7dd4bcda"
    assert t["bge-m3:latest"] == "790764642607"
    assert len(t) >= 5


def test_parse_ollama_list_and_compare():
    exp = sr.parse_models_table((ROOT / "docs/team/models.md").read_text(encoding="utf-8"))
    act = sr.parse_ollama_list(LIST)
    lines, ok = sr.compare_models(exp, act, ["qwen3:4b", "qwen3:4b-instruct", "bge-m3", "qwen3:8b"])
    assert not ok
    text = "\n".join(lines)
    assert "OK       qwen3:4b 359d7dd4bcda" in text
    assert "MISMATCH bge-m3" in text
    assert "MISSING  qwen3:8b" in text
    _, ok2 = sr.compare_models(exp, {"qwen3:4b": "359d7dd4bcda"}, ["qwen3:4b"])
    assert ok2


def test_pick_streams():
    assert sr.pick_streams({1: 40.0, 2: 24.0, 4: 15.0}) == 4
    assert sr.pick_streams({1: 40.0, 2: 39.0, 4: 38.5}) == 1  # within 5%: fewer streams
    assert sr.pick_streams({1: 20.0, 2: 21.0, 4: 30.0}) == 1
    assert sr.pick_streams({1: 40.0, 2: 20.0, 4: 19.5}) == 2
    with pytest.raises(ValueError):
        sr.pick_streams({})


def test_progress_stats():
    st = sr.progress_stats(done=30, total=100, baseline=10, started=0, now=600)
    assert st["per_min"] == pytest.approx(2.0)
    assert st["eta_min"] == pytest.approx(35.0)
    assert sr.progress_stats(5, 100, 5, 0, 60)["eta_min"] is None
    assert sr._fmt_eta(95) == "1h35m"


def test_split_and_probe_story():
    recs = [{"chunk_id": f"c{i}"} for i in range(8)]
    parts = sr.split_round_robin(recs, 4)
    assert [len(p) for p in parts] == [2, 2, 2, 2]
    assert sorted(r["chunk_id"] for p in parts for r in p) == sorted(r["chunk_id"] for r in recs)
    assert sr.pick_probe_story(["a", "b", "c"], {"a"}, {"a": 9, "b": 3, "c": 9}, 8) == "c"
    with pytest.raises(ValueError):
        sr.pick_probe_story(["a"], {"a"}, {"a": 9}, 8)


def _graph(path: Path) -> None:
    from detective_board.graph.schema import migrate

    conn = sqlite3.connect(path)
    migrate(conn)
    for cid, story in [("a-0", "a"), ("b-0", "b")]:
        conn.execute("INSERT INTO g_chunk VALUES (?,?,0,10,1,'x','y')", (cid, story))

    def node(i, kind, story, props):
        conn.execute(
            "INSERT INTO g_node(id,kind,story,props_json) VALUES (?,?,?,?)",
            (i, kind, story, json.dumps(props)),
        )

    node("e1", "event", "a", {"time_text": "at night"})
    node("e2", "event", "a", {})
    node("c1", "claim", "a", {})
    node("c2", "claim", "a", {})
    node("p1", "person", "b", {})  # story b has no events
    conn.execute("INSERT INTO g_overlay VALUES ('e1','time','{}','low','normaliser')")
    conn.execute("INSERT INTO g_overlay VALUES ('e1','story_day','1','low','normaliser')")
    conn.execute("INSERT INTO g_overlay VALUES ('c1','prop','{}','low','normaliser')")
    conn.commit()
    conn.close()


def test_graph_and_extract_stats_and_report(tmp_path):
    db = tmp_path / "g.sqlite"
    _graph(db)
    g = sr.graph_stats(db)
    assert g["events"] == 2 and g["claims"] == 2
    assert g["events_with_time_text"] == 0.5
    assert g["events_with_time_norm"] == 0.5
    assert g["claims_with_prop"] == 0.5
    assert g["stories_zero_events"] == ["b"]

    out = tmp_path / "x.jsonl"
    rows = [
        {
            "status": "ok",
            "extraction": {"events": [1, 2], "claims": [3]},
            "dropped": [{"reason": "r"}],
            "cached": False,
            "wall_s": 10.0,
        },
        {
            "status": "repaired",
            "extraction": {"events": []},
            "dropped": [],
            "cached": True,
            "wall_s": 0.0,
        },
    ]
    out.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    ex = sr.extract_stats([out])
    assert (ex["chunks"], ex["kept"], ex["dropped"]) == (2, 3, 1)
    assert ex["live_sec_per_chunk"] == 10.0
    assert ex["dropped_by_reason"] == {"r": 1}

    md = sr.render_report(
        {
            "commit": "abc",
            "ollama": "0.35.0",
            "gpu": "RTX 4070, 12282 MiB, 570.1",
            "models": {"qwen3:4b": "359d7dd4bcda"},
            "determinism": {"compared": 3, "identical": 3, "different": 0, "sec_per_chunk": 12.5},
            "probe": {"results": {"1": 30.0, "2": 18.0}, "best": 2},
            "run": {"streams": 2, "effective_sec_per_chunk": 9.1},
            "extract": ex,
            "graph": g,
        }
    )
    for needle in (
        "abc",
        "0.35.0",
        "RTX 4070",
        "359d7dd4bcda",
        "byte-identical 3",
        "probe, 2 stream(s) | 18.0",
        "(chosen)",
        "total chunks: 2",
        "claims with a proposition: 0.5",
        "stories with zero events: ['b']",
    ):
        assert needle in md, needle


def test_cached_stories_with_synthetic_cache(tmp_path):
    mec = sr._load("merge_extract_cache")
    from detective_board.extract.cache import ExtractCache

    chunks = tmp_path / "c.jsonl"
    recs = [
        {"chunk_id": "a-0", "story": "a", "text": "alpha"},
        {"chunk_id": "b-0", "story": "b", "text": "beta"},
    ]
    chunks.write_text("\n".join(json.dumps(r) for r in recs) + "\n")
    cfg = mec.ExtractConfig("qwen3:4b", 4096, 1536, 42)
    version = mec.load_prompt(mec.DEFAULT_PROMPT).version
    keys = mec.expected_keys(chunks, cfg, version)
    key_a = next(k for k, c in keys.items() if c == "a-0")
    cache = ExtractCache(tmp_path / "p.sqlite")
    with cache.conn:
        cache.conn.execute("INSERT INTO raw VALUES (?,?)", (key_a, "{}"))
    cache.close()
    assert sr.cached_stories(chunks, tmp_path / "p.sqlite", "qwen3:4b") == {"a"}
    assert sr.count_rows(tmp_path / "p.sqlite") == 1
    assert sr.count_rows(tmp_path / "missing.sqlite") == 0


def test_kv(tmp_path):
    f = tmp_path / "s.json"
    sr.main(["kv", str(f), "a=3", "b=x", "c=[1,2]"])
    sr.main(["kv", str(f), "a=4"])
    assert json.loads(f.read_text()) == {"a": 4, "b": "x", "c": [1, 2]}


@pytest.mark.parametrize("name", ["server_bootstrap.sh", "server_run_all.sh", "server_progress.sh"])
def test_shell_scripts_parse(name):
    p = ROOT / "scripts" / name
    assert p.exists()
    subprocess.run(["bash", "-n", str(p)], check=True)
