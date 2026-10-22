import hashlib
import importlib
import json
import math
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "spike"))
br = importlib.import_module("bench_retrieval")
cg = importlib.import_module("chunk_gold")

DIM = 64


def fake_vec(text):
    v = [0.0] * DIM
    for w in re.findall(r"[a-z]+", text.lower()):
        v[int(hashlib.md5(w.encode()).hexdigest(), 16) % DIM] += 1.0
    return v


class FakeEmbed:
    def __init__(self, fail_after=None):
        self.calls = 0
        self.texts = 0
        self.fail_after = fail_after

    def __call__(self, texts):
        if self.fail_after is not None and self.calls >= self.fail_after:
            raise KeyboardInterrupt
        self.calls += 1
        self.texts += len(texts)
        return [fake_vec(t) for t in texts]


# synthetic corpus: two stories, three chunks each, separated by 2-char gaps
TEXTS = {
    "alpha": ["The red fox jumped over the quiet river bank.",
              "A lantern burned in the attic of the old mill.",
              "Nothing happened in the garden that morning."],
    "beta": ["The captain kept his compass inside a brass kettle.",
             "Thunder rolled across the empty harbour at midnight.",
             "She whispered the password to the sleepy gatekeeper."],
}


def make_corpus(tmp_path):
    chunks = []
    clean = tmp_path / "clean"
    clean.mkdir(exist_ok=True)
    for story, parts in TEXTS.items():
        pos, full = 0, ""
        for i, t in enumerate(parts):
            chunks.append({"chunk_id": f"{story}-{i:04d}", "story": story, "char_start": pos,
                           "char_end": pos + len(t), "text": t})
            full += t + "\n\n"
            pos += len(t) + 2
        (clean / f"{story}.txt").write_text(full, encoding="utf-8")
    return chunks, clean


def questions():
    return [
        {"id": "q1", "lang": "en", "group": "old-en", "question": "red fox river bank",
         "expected_stories": ["alpha"], "quotes": [("alpha", "red fox jumped")]},
        {"id": "q2", "lang": "ru", "group": "old-ru", "question": "lantern attic old mill",
         "expected_stories": ["alpha"], "quotes": [("alpha", "lantern burned")]},
        {"id": "q3", "lang": "en", "group": "hard", "question": "where is the compass kept brass kettle",
         "expected_stories": ["beta"], "quotes": [("beta", "compass inside a brass")]},
        {"id": "q4", "lang": "en", "group": "cross", "question": "fox river harbour thunder midnight",
         "expected_stories": ["alpha", "beta"],
         "quotes": [("alpha", "quiet river"), ("beta", "Thunder rolled")]},
    ]


def test_find_spans_whitespace_and_quotes():
    text = "He said,  “It’s the\nonly way.” Done."
    assert cg.find_spans(text, "It's the only way.") != []
    assert cg.find_spans(text, 'said, "It\'s') != []
    assert cg.find_spans(text, "not present") == []


def test_boundary_straddle_maps_to_both_chunks(tmp_path):
    chunks, clean = make_corpus(tmp_path)
    # quote crossing the gap between alpha-0000 and alpha-0001
    q = [{"id": "s", "lang": "en", "group": "hard", "question": "x", "expected_stories": ["alpha"],
          "quotes": [("alpha", "river bank. A lantern")]}]
    gold, missing = cg.build_gold(q, chunks, clean)
    assert not missing
    assert gold["s"]["chunks"] == ["alpha-0000", "alpha-0001"]


def test_unmapped_quote_reported(tmp_path):
    chunks, clean = make_corpus(tmp_path)
    q = [{"id": "m", "lang": "en", "group": "hard", "question": "x", "expected_stories": ["alpha"],
          "quotes": [("alpha", "this text is nowhere")]}]
    gold, missing = cg.build_gold(q, chunks, clean)
    assert missing and missing[0]["id"] == "m" and gold["m"]["chunks"] == []


def test_load_questions_real_files_and_groups():
    qs = cg.load_questions()
    groups = {}
    for q in qs:
        groups[q["group"]] = groups.get(q["group"], 0) + 1
    assert groups["old-en"] == 15 and groups["old-ru"] == 5
    assert 12 <= groups["hard"] + groups["cross"] <= 15 and groups["cross"] >= 2
    assert len({q["id"] for q in qs}) == len(qs)


def test_real_gold_has_no_unmapped_quotes():
    gold, missing = cg.build_gold(cg.load_questions(), cg.load_jsonl(cg.CHUNKS))
    assert missing == []
    assert all(g["chunks"] for g in gold.values())


def test_metrics_and_groups(tmp_path):
    chunks, clean = make_corpus(tmp_path)
    qs = questions()
    gold, missing = cg.build_gold(qs, chunks, clean)
    assert not missing
    res = br.evaluate("fake", chunks, qs, gold, FakeEmbed(), path=tmp_path / "c.jsonl", batch=4)
    by = {r["id"]: r for r in res["per_question"]}
    assert by["q1"]["rank"] == 1 and by["q1"]["hit@1"]
    assert by["q3"]["rank"] == 1
    assert set(by["q4"]["gold_chunks"]) == {"alpha-0000", "beta-0001"}
    assert by["q4"]["recall@10"] == 1.0  # whole corpus is 6 chunks, all within top 10
    s = res["summary"]
    assert s["old-en"]["n"] == 1 and s["cross"]["n"] == 1 and s["all"]["n"] == 4
    assert math.isclose(s["all"]["hit@10"], 1.0)
    assert 0 < s["all"]["mrr"] <= 1.0


def test_score_question_hand_computed():
    chunks = [{"chunk_id": f"s-{i}", "story": "s" if i < 3 else "t"} for i in range(6)]
    q = {"id": "x", "group": "hard", "lang": "en", "expected_stories": ["t"]}
    row = br.score_question(q, ["s-2", "s-5"], [0, 1, 2, 3, 4, 5], chunks)  # gold at ranks 3 and 6
    assert row["rank"] == 3 and not row["hit@1"] and row["hit@5"] and row["hit@10"]
    assert math.isclose(row["rr"], 1 / 3) and row["recall@10"] == 1.0
    assert row["story_hit@5"] is True  # t-3 in top 5
    row = br.score_question(q, ["s-5"], [0, 1, 2, 3, 4, 5], chunks)
    assert row["rank"] == 6 and not row["hit@5"] and row["hit@10"]
    miss = br.score_question(q, ["zzz"], [0, 1, 2], chunks)
    assert miss["rank"] is None and miss["rr"] == 0.0 and miss["recall@10"] == 0.0


def test_cache_embeds_once_and_is_reused(tmp_path):
    chunks, clean = make_corpus(tmp_path)
    path = tmp_path / "c.jsonl"
    e1 = FakeEmbed()
    v1 = br.embed_corpus(chunks, "", e1, path, batch=4)
    assert e1.texts == 6
    e2 = FakeEmbed()
    v2 = br.embed_corpus(chunks, "", e2, path, batch=4)
    assert e2.calls == 0 and v1 == v2


def test_cache_resumes_after_interrupt_and_torn_line(tmp_path):
    chunks, _ = make_corpus(tmp_path)
    path = tmp_path / "c.jsonl"
    e1 = FakeEmbed(fail_after=1)  # first batch (2 chunks) saved, then interrupted
    try:
        br.embed_corpus(chunks, "", e1, path, batch=2)
    except KeyboardInterrupt:
        pass
    assert len(br.load_cache(path)) == 2
    with open(path, "a", encoding="utf-8") as f:
        f.write('{"id": "torn')  # simulate a half-written line
    e2 = FakeEmbed()
    v = br.embed_corpus(chunks, "", e2, path, batch=2)
    assert e2.texts == 4 and len(v) == 6
    assert len(br.load_cache(path)) == 6
    assert br.embed_corpus(chunks, "", FakeEmbed(), path, batch=2) == v


def test_cache_key_depends_on_prefix_and_model(tmp_path):
    a = br.cache_path("bge-m3", "", 2048, True, tmp_path)
    assert a != br.cache_path("bge-m3", "passage: ", 2048, True, tmp_path)
    assert a != br.cache_path("nomic-embed-text", "", 2048, True, tmp_path)
    assert br.cache_path("x:latest/y", "", 2048, True, tmp_path).name.startswith("x_latest_y-")
    assert a == br.cache_path("bge-m3", "", 2048, True, tmp_path)


def test_changed_text_invalidates_only_that_chunk(tmp_path):
    chunks, _ = make_corpus(tmp_path)
    path = tmp_path / "c.jsonl"
    br.embed_corpus(chunks, "", FakeEmbed(), path, batch=3)
    chunks[1] = {**chunks[1], "text": chunks[1]["text"] + " Extra."}
    e = FakeEmbed()
    br.embed_corpus(chunks, "", e, path, batch=3)
    assert e.texts == 1


def test_dry_run_makes_no_calls_and_writes_nothing(tmp_path, capsys, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("network used in dry-run")
    monkeypatch.setattr(br, "Http", boom)
    monkeypatch.setattr(br, "embed_all", boom)
    cache = tmp_path / "emb"
    rc = br.main(["bge-m3", "--dry-run", "--cache-dir", str(cache), "--doc-prefix", "bge-m3=passage: "])
    out = capsys.readouterr().out
    assert rc == 0 and "no network used" in out and "0/" in out
    assert not cache.exists()
