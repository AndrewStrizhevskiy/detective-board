import json
import sqlite3

import pytest

from detective_board.extract import run as cli
from detective_board.extract.cache import ExtractCache, cache_key
from detective_board.extract.llm import FakeClient, GenResponse, OllamaClient
from detective_board.extract.pipeline import ExtractConfig, Extractor, load_prompt

from .conftest import CHUNK, good_output

CFG = ExtractConfig("fake:1b")


def test_prompt_has_version_and_renders():
    p = load_prompt()
    assert (
        p.version == "extract-2.1"
        and "{{CHUNK}}" not in p.render("XYZ")
        and "XYZ" in p.render("XYZ")
    )


def test_extract_ok_grounds_and_rewrites_quotes():
    ex = Extractor(FakeClient([good_output()]), CFG)
    r = ex.extract_chunk("c1", "s", CHUNK)
    assert r.status == "ok" and r.grounding == {"exact": 4, "fuzzy": 0, "none": 0}
    assert r.extraction["events"][0]["quote"] == "I left the house at nine o’clock"
    assert r.to_extraction().claims[0].polarity == "deny"


def test_ungrounded_dropped_unless_kept():
    bad = good_output(
        claims=[{"speaker": "A", "content": "c", "quote": "Totally invented sentence here"}]
    )
    r = Extractor(FakeClient([bad]), CFG).extract_chunk("c1", "s", CHUNK)
    assert r.extraction["claims"] == []
    assert any(d["reason"] == "quote_not_grounded" for d in r.dropped)
    cfg = ExtractConfig("fake:1b", keep_ungrounded=True)
    r = Extractor(FakeClient([bad]), cfg).extract_chunk("c1", "s", CHUNK)
    assert r.extraction["claims"][0]["grounded"] == "none"


def test_truncated_output_keeps_complete_items():
    raw = good_output()
    cut = raw[: raw.index('"polarity"')]
    fc = FakeClient([GenResponse(cut, done_reason="length")])
    r = Extractor(fc, CFG).extract_chunk("c1", "s", CHUNK)
    assert r.status == "repaired" and r.truncated
    assert len(r.extraction["entities"]) == 2 and len(r.extraction["events"]) == 1
    assert r.extraction["claims"] == []


def test_garbage_is_failed_not_exception():
    r = Extractor(FakeClient(["nope"]), CFG).extract_chunk("c1", "s", CHUNK)
    assert r.status == "failed" and r.extraction == {}


def test_client_error_is_recorded_and_not_cached():
    def boom(_):
        raise TimeoutError("slow")

    cache = ExtractCache()
    r = Extractor(FakeClient(boom), CFG, cache).extract_chunk("c1", "s", CHUNK)
    assert r.status == "error" and "TimeoutError" in r.error and len(cache) == 0


def test_cache_hit_miss_and_key_sensitivity(tmp_path):
    path = tmp_path / "c.sqlite"
    fc = FakeClient(lambda p: good_output())
    ex = Extractor(fc, CFG, ExtractCache(path))
    assert not ex.extract_chunk("c1", "s", CHUNK).cached
    assert ex.extract_chunk("c1", "s", CHUNK).cached and len(fc.calls) == 1
    # new process / resume: same file, fresh objects
    fc2 = FakeClient(lambda p: good_output())
    ex2 = Extractor(fc2, CFG, ExtractCache(path))
    assert ex2.extract_chunk("c1", "s", CHUNK).cached and not fc2.calls
    # any key component change -> miss
    ex2.extract_chunk("c1", "s", CHUNK + "!")
    ex3 = Extractor(fc2, ExtractConfig("fake:1b", num_predict=99), ExtractCache(path))
    ex3.extract_chunk("c1", "s", CHUNK)
    ex4 = Extractor(fc2, ExtractConfig("other:2b"), ExtractCache(path))
    ex4.extract_chunk("c1", "s", CHUNK)
    assert len(fc2.calls) == 3
    base = ("t", "m", "p", "2", {"a": 1})
    assert cache_key(*base) == cache_key(*base)
    assert len({cache_key(*base), cache_key("t", "m", "p2", "2", {"a": 1}),
                cache_key("t", "m", "p", "3", {"a": 1})}) == 3  # fmt: skip
    assert sqlite3.connect(path).execute("select count(*) from raw").fetchone()[0] == 4


def test_deterministic():
    runs = [Extractor(FakeClient([good_output()]), CFG).extract_chunk("c", "s", CHUNK).to_json()
            for _ in range(2)]  # fmt: skip
    assert json.dumps(runs[0], sort_keys=True) == json.dumps(runs[1], sort_keys=True)


def test_ollama_payload_think_only_with_capability():
    from detective_board.extract.llm import GenRequest

    c = OllamaClient()
    req = GenRequest("m", "p", {"type": "object"}, {"seed": 1})
    assert c.build_payload(req, ["completion", "thinking"])["think"] is False
    assert "think" not in c.build_payload(req, ["completion"])
    p = c.build_payload(req, [])
    assert (
        p["format"] == {"type": "object"} and p["stream"] is False and p["options"] == {"seed": 1}
    )


def test_cli_with_fake_client_resume_and_report(chunks_file, tmp_path, capsys):
    out, cache = tmp_path / "o.jsonl", tmp_path / "c.sqlite"
    base = ["--model", "fake:1b", "--chunks", str(chunks_file), "--out", str(out),
            "--cache", str(cache)]  # fmt: skip
    outputs = [good_output(), good_output()[:200], "garbage", good_output()]
    fc = FakeClient(outputs)
    assert cli.main([*base, "--story", "s1", "--limit", "2"], client=fc) == 0
    rep = json.loads(capsys.readouterr().out)
    assert rep["chunks"] == 2 and rep["repaired"] == 1 and rep["valid_json_rate"] == 0.5
    assert rep["grounding"]["exact"] >= 4 and rep["from_cache"] == 0
    # resume over all 4 chunks: the first 2 come from cache, only 2 new calls
    assert cli.main(base, client=fc) == 0
    rep = json.loads(capsys.readouterr().out)
    assert rep["chunks"] == 4 and rep["from_cache"] == 2 and len(fc.calls) == 4
    assert rep["failed"] == 1
    lines = [json.loads(x) for x in out.read_text().splitlines()]
    assert len(lines) == 4 and lines[0]["status"] == "ok"


def test_cli_graph_ingest(chunks_file, tmp_path, capsys):
    pytest.importorskip("detective_board.graph")
    argv = ["--model", "m", "--chunks", str(chunks_file), "--out", str(tmp_path / "o.jsonl"),
            "--cache", str(tmp_path / "c.sqlite"), "--limit", "1",
            "--graph-db", str(tmp_path / "g.sqlite")]  # fmt: skip
    cli.main(argv, client=FakeClient(lambda p: good_output()))
    assert json.loads(capsys.readouterr().out)["graph_ingested"] == 1
    from detective_board.graph import GraphStore

    assert GraphStore(str(tmp_path / "g.sqlite")).stats()
