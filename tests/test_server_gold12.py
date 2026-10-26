import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts" / "spike"))
_spec = importlib.util.spec_from_file_location(
    "server_gold12", ROOT / "scripts" / "server_gold12.py"
)
sg = importlib.util.module_from_spec(_spec)
sys.modules["server_gold12"] = sg
_spec.loader.exec_module(sg)


def test_chunks_cover_all_gold_files(tmp_path):
    out = tmp_path / "gold12.jsonl"
    recs = sg.build_chunks(sg.GOLD_DIR, tmp_path / "missing-corpus.jsonl", out)
    gold_ids = sorted(p.stem for p in sg.GOLD_DIR.glob("*.json"))
    assert len(recs) == 12
    assert [r["chunk_id"] for r in recs] == gold_ids
    lines = [json.loads(x) for x in out.read_text(encoding="utf-8").splitlines()]
    assert all(r["text"] and r["story"] for r in lines)


def test_chunks_prefer_corpus_text(tmp_path):
    gold = tmp_path / "g"
    gold.mkdir()
    (gold / "a.json").write_text(
        json.dumps({"chunk_id": "a-0", "story": "a", "text": "gold  text", "gold": {}})
    )
    corpus = tmp_path / "c.jsonl"
    corpus.write_text(json.dumps({"chunk_id": "a-0", "story": "a", "text": "corpus text"}) + "\n")
    (rec,) = sg.build_chunks(gold, corpus, tmp_path / "o.jsonl")
    assert rec["text"] == "corpus text"


def test_slug_is_filesystem_safe():
    assert sg.slug("qwen3:4b", "prompts/extract/extract_v2_1.txt") == "qwen3_4b__extract_v2_1"
    assert sg.slug("qwen3:4b-instruct", "x/extract_v2.txt") == "qwen3_4b_instruct__extract_v2"


def test_report_writes_markdown(tmp_path, capsys):
    recs = [
        {"chunk_id": p.stem, "story": "s", "status": "failed", "extraction": {}, "wall_s": 1.0}
        for p in sg.GOLD_DIR.glob("*.json")
    ]
    out = tmp_path / "m__p.jsonl"
    out.write_text("".join(json.dumps(r) + "\n" for r in recs))
    md = sg.report("T", [out], results_dir=tmp_path)
    assert md.name == "gold12-T.md" and "m__p" in md.read_text()
    assert "m__p" in capsys.readouterr().out


def test_shell_script_syntax_and_help():
    sh = ROOT / "scripts" / "server_gold12.sh"
    assert subprocess.run(["bash", "-n", str(sh)]).returncode == 0
    r = subprocess.run([str(sh), "--help"], capture_output=True, text=True)
    assert r.returncode == 0 and "Usage" in r.stdout
