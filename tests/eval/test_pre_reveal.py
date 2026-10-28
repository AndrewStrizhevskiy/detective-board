"""Pre-reveal test without Ollama: the restriction wrapper on a hand-built store, the scorer, the
validator (including the real cases file)."""

import importlib.util
import json
from pathlib import Path

import pytest
import sqlite_vec

from detective_board.agent.backends import HybridRetriever
from detective_board.retrieval import (
    EmbeddingConfig,
    HashEmbedder,
    Store,
    embed_missing,
    load_chunks,
)
from detective_board.retrieval.sentences import SentenceStore

from .conftest import ROOT, load

P = load("pre_reveal")


def _validator():
    path = ROOT / "scripts" / "eval" / "validate_pre_reveal.py"
    spec = importlib.util.spec_from_file_location("validate_pre_reveal", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


V = _validator()
CFG = EmbeddingConfig(model="fake", dim=64)
# (chunk id, story, char_start, char_end, text); story "a" is cut at 200, story "b" is untouched
CHUNKS = [
    ("a-0", "a", 0, 100, "The trainer was found dead on the moor near the stables."),
    ("a-1", "a", 100, 190, "The stable boy was drugged with curried mutton that night."),
    ("a-2", "a", 190, 290, "The horse kicked the trainer in self-defence, said Holmes."),
    ("a-3", "a", 300, 400, "The real murderer is the horse, said Holmes to the trainer."),
    ("b-0", "b", 0, 100, "The trainer of another stable was found dead on the road."),
    ("b-1", "b", 100, 200, "The horse of the colonel was missing from the stables."),
]
SENTS = [  # id, chunk, start, end (inside the chunk), text
    (1, "a-0", 0, 55, "The trainer was found dead on the moor near the stables."),
    (2, "a-2", 0, 58, "The horse kicked the trainer in self-defence, said Holmes."),
    (3, "a-3", 0, 60, "The real murderer is the horse, said Holmes to the trainer."),
    (4, "b-1", 0, 53, "The horse of the colonel was missing from the stables."),
]


@pytest.fixture
def inner(tmp_path):
    path = tmp_path / "chunks.jsonl"
    path.write_text(
        "".join(
            json.dumps(
                dict(
                    chunk_id=c,
                    story=s,
                    section="I",
                    para_start=0,
                    para_end=0,
                    char_start=a,
                    char_end=b,
                    text=t,
                )  # fmt: skip
            )
            + "\n"
            for c, s, a, b, t in CHUNKS
        )
    )
    store = Store(":memory:", CFG)
    load_chunks(store, path)
    emb = HashEmbedder(CFG)
    embed_missing(store, emb)
    sents = SentenceStore(":memory:", CFG)
    with sents.db:
        for i, c, a, b, t in SENTS:
            story = c.split("-")[0]
            sents.db.execute(
                "INSERT INTO sent(id, chunk_id, story, start, end, text) VALUES (?,?,?,?,?,?)",
                (i, c, story, a, b, t),
            )
            sents.db.execute(
                "INSERT INTO sent_vec(rowid, embedding) VALUES (?, ?)",
                (i, sqlite_vec.serialize_float32(emb.embed_documents([t])[0])),
            )
            sents.db.execute("INSERT INTO sent_fts(rowid, text) VALUES (?, ?)", (i, t))
    return HybridRetriever(store, emb, sentences=sents)


Q = "Who killed the trainer, the horse?"


def test_cut_retriever_without_cuts_is_the_product_retriever(inner):
    ids = lambda hs: [h.chunk_id for h in hs]  # noqa: E731
    assert ids(P.CutRetriever(inner, {}).search(Q, 6)) == ids(inner.search(Q, 6))
    plain = [(h.chunk_id, h.start, h.end) for h in inner.sentence_search(Q, 4).hits]
    cut = [
        (h.chunk_id, h.start, h.end) for h in P.CutRetriever(inner, {}).sentence_search(Q, 4).hits
    ]
    assert cut == plain


def test_cut_drops_chunks_past_the_cut_and_the_straddling_one(inner):
    hits = P.CutRetriever(inner, {"a": 200}).search(Q, 10)
    got = {h.chunk_id for h in hits}
    assert "a-3" not in got and "a-2" not in got, "a-2 straddles 200 (190..290): dropped too"
    assert {"a-0", "a-1", "b-0", "b-1"} == got, "the other story is untouched"
    assert all(h.story != "a" or h.char_end <= 200 for h in hits)


def test_cut_drops_sentences_with_their_chunks_and_recomputes_ranks(inner):
    res = P.CutRetriever(inner, {"a": 200}).sentence_search(Q, 10)
    assert res is not None
    assert {h.chunk_id for h in res.hits} == {"a-0", "b-1"}
    assert set(res.chunks) == {"a-0", "b-1"}
    for arm in ("bm25", "vec"):  # ranks are 1..n over what is left, as in a smaller index
        ranks = sorted(h.ranks[arm] for h in res.hits if arm in h.ranks)
        assert ranks == list(range(1, len(ranks) + 1))


def test_no_sentence_index_gives_none(inner):
    inner.sentences = None
    assert P.CutRetriever(inner, {"a": 200}).sentence_search(Q, 3) is None


CASE = {
    "id": "c1",
    "story": "a",
    "cut_char": 200,
    "truth": "the horse",
    "rationale": "r",
    "truth_keywords": ["lessen his guilt"],
    "truth_keywords_alt": [["steel shoe", "Straker"]],
    "culprit_names": [["the horse"], ["Straker himself"], ["Silver", "kicked"]],
    "cleared_names": ["Simpson"],
}


def test_primary_metric_is_the_culprit_name_and_keywords_are_secondary():
    row = {"condition": "cut", "status": "answered", "citations": []}
    s = P.score(CASE, {**row, "answer": "The horse lashed out, said he."})
    assert (s["outcome"], s["outcome_keywords"], s["matched_name"]) == (
        "named",
        "wrong",
        "the horse",
    )
    s = P.score(CASE, {**row, "answer": "It may lessen his guilt, said he."})
    assert (s["outcome"], s["outcome_keywords"]) == ("wrong", "named"), "wording, not the name"
    s = P.score(CASE, {**row, "answer": "x", "citations": [{"quote": "Silver Blaze kicked out"}]})
    assert s["outcome"] == "named" and s["matched_name"] == "Silver+kicked", "quotes count"
    assert P.outcome(CASE, {**row, "answer": "Silver Blaze ran"}) == "wrong", "a set needs all"
    assert P.outcome(CASE, {**row, "answer": "THE HORSE"}) == "named", "case-insensitive"
    assert P.outcome(CASE, {**row, "answer": "other horse"}) == "wrong"


def test_refused_unscored_error_and_innocent_accused():
    row = {"condition": "cut", "status": "answered", "citations": []}
    assert P.outcome(CASE, {**row, "status": "refused", "answer": "the horse"}) == "refused"
    assert P.outcome(CASE, {**row, "answer": "the horse", "graph_used": True}) == "unscored"
    full = {**row, "condition": "full", "answer": "the horse", "graph_used": True}
    assert P.outcome(CASE, full) == "named", "only the cut run is unscored by graph use"
    assert P.outcome(CASE, {**row, "error": "boom"}) == "error"
    s = P.score(CASE, {**row, "answer": "Fitzroy Simpson struck him down."})
    assert s["innocent_accused"] and s["cleared_mentioned"] == "Simpson"
    s = P.score(CASE, {**row, "answer": "Not Simpson: the horse did it."})
    assert not s["innocent_accused"] and s["cleared_mentioned"] == "Simpson"
    s = P.score(CASE, {**row, "status": "refused", "answer": "Simpson"})
    assert not s["innocent_accused"]


def test_precut_exposure_counts_chunks_before_the_cut_only():
    chunks = [
        {"story": "a", "char_end": 100, "text": "the horse ran"},
        {"story": "a", "char_end": 300, "text": "the horse kicked"},
        {"story": "b", "char_end": 50, "text": "the horse"},
    ]
    assert P.precut_exposure(CASE, chunks) == {
        "the horse": 1,
        "Straker himself": 0,
        "Silver+kicked": 0,
    }


def _row(o, **kw):
    base = {"id": "1", "story": "s", "condition": "cut", "outcome": o, "total_s": 10.0}
    return {**base, "outcome_keywords": o, "innocent_accused": False, **kw}


def test_summary_counts_with_intervals():
    rows = [
        _row("refused"),
        _row("refused"),
        _row("wrong", innocent_accused=True),
        _row("unscored"),
    ]
    s = P.summarise(rows, {"1": CASE}, ["cut"])["cut"]
    assert (s["n_questions"], s["n_scored"], s["unscored"]) == (4, 3, 1)
    assert s["named"]["k"] == 0 and s["named"]["n"] == 3 and s["named"]["ci95"][1] < 0.7
    assert s["refused"]["k"] == 2 and s["latency_s"]["median"] == 10.0
    assert s["innocent_accused"]["k"] == 1 and s["named_keywords"]["k"] == 0


def test_rescore_uses_the_saved_answers_and_the_current_cases(tmp_path):
    cases = tmp_path / "cases.jsonl"
    cases.write_text(json.dumps(CASE) + "\n")
    old = {
        "meta": {
            "conditions": ["full", "cut"], "date": "d", "git_sha": "abc1234", "git_dirty": False,
            "generator": "g", "seed": 42, "temperature": 0.0, "machine": "m", "cases_file": "c",
            "cases_sha256": "0" * 64, "n_cases": 1, "n_stories": 1, "presence": {},
        },  # fmt: skip
        "rows": [
            {"id": "c1", "story": "a", "condition": "full", "status": "answered",
             "answer": "The horse.", "citations": [], "outcome": "wrong", "total_s": 1.0},
            {"id": "c1", "story": "a", "condition": "cut", "status": "answered",
             "answer": "Simpson did it.", "citations": [], "outcome": "wrong", "total_s": 1.0},
        ],
    }  # fmt: skip
    new = P.rescore(old, cases, "old.json")
    full, cut = new["rows"]
    assert full["outcome"] == "named" and cut["innocent_accused"]
    assert new["meta"]["rescored"]["from"] == "old.json" and new["meta"]["date"] == "d"
    assert new["summary"]["full"]["named"]["k"] == 1
    md = P.render_md(new["meta"], new["summary"], new["rows"], new["cases"], new["exposure"])
    for text in ("Primary: culprit named", "Secondary: keyword metric", "RESCORED", "McNemar"):
        assert text in md


# ------------------------------------------------------------------ validator


def _case(text, **kw):
    cut = text.index("REVEAL")
    base = {
        "id": "x", "story": "s", "cut_char": cut, "question": "Who did it?", "truth": "t",
        "truth_keywords": ["Jones"], "reveal_quotes": ["Jones did it"], "rationale": "r",
        "culprit_names": [["Jones"]],
    }  # fmt: skip
    return {**base, **kw}


TEXT = "Smith waited.\nJones was in the garden.\nREVEAL: Jones did it, said Holmes.\n"


def test_validator_accepts_a_leak_free_case_and_flags_leaks():
    chunks = [{"chunk_id": "s-0", "story": "s", "char_start": 0, "char_end": 5, "text": "Smith"}]
    ok = V.check_case(_case(TEXT, truth_keywords=["Jones", "did it"]), TEXT, chunks, set(), "c")
    assert ok == []
    leak = V.check_case(_case(TEXT), TEXT, chunks, set(), "c")
    assert any("pre-cut sentence" in e for e in leak), "the keyword alone is already pre-cut"
    sentence = "Smith waited.\nJones is the murderer here.\nREVEAL: Jones did it.\n"
    e = V.check_case(
        _case(sentence, truth_keywords=["murderer", "Jones"]), sentence, chunks, set(), "c"
    )
    assert any("holds all" in x for x in e) or any("is the" in x for x in e)
    wide = [
        {"chunk_id": "s-0", "story": "s", "char_start": 0, "char_end": 10, "text": "Jones did it"}
    ]
    e = V.check_case(_case(TEXT, truth_keywords=["Jones", "did it"]), TEXT, wide, set(), "c")
    assert any("pre-cut chunk" in x for x in e)


def test_validator_flags_quote_and_cut_errors():
    kw = {"truth_keywords": ["zzz"]}
    e = V.check_case(_case(TEXT, reveal_quotes=["Jones did not do it"], **kw), TEXT, [], set(), "c")
    assert any("not verbatim" in x for x in e)
    e = V.check_case(
        _case(TEXT, reveal_quotes=["Jones was in the garden"], **kw), TEXT, [], set(), "c"
    )
    assert any("before the cut" in x for x in e)
    e = V.check_case(_case(TEXT, cut_char=5, **kw), TEXT, [], set(), "c")
    assert any("paragraph start" in x for x in e)
    e = V.check_case(_case(TEXT, question="Did Jones do it? zzz", **kw), TEXT, [], set(), "c")
    assert any("question already contains" in x for x in e)
    seen: set[str] = set()
    V.check_case(_case(TEXT, **kw), TEXT, [], seen, "c")
    assert any("duplicate" in x for x in V.check_case(_case(TEXT, **kw), TEXT, [], seen, "c"))


def test_validator_checks_culprit_and_cleared_names():
    kw = {"truth_keywords": ["zzz"]}
    assert V.check_case(_case(TEXT, **kw), TEXT, [], set(), "c") == [], "aliases may occur pre-cut"
    e = V.check_case(_case(TEXT, culprit_names=[], **kw), TEXT, [], set(), "c")
    assert any("culprit_names" in x for x in e)
    e = V.check_case(_case(TEXT, culprit_names=[["Jones", ""]], **kw), TEXT, [], set(), "c")
    assert any("culprit_names" in x for x in e)
    e = V.check_case(_case(TEXT, cleared_names=["Mr Jones"], **kw), TEXT, [], set(), "c")
    assert any("matches a culprit alias" in x for x in e)
    case = _case(TEXT, **kw)
    del case["culprit_names"]
    assert any("missing field culprit_names" in x for x in V.check_case(case, TEXT, [], set(), "c"))


def test_real_cases_file_is_valid():
    assert (
        V.validate(
            ROOT / "eval" / "pre_reveal" / "cases.jsonl",
            ROOT / "data" / "clean",
            ROOT / "data" / "chunks.jsonl",
        )
        == []
    )
    rows = [
        json.loads(x) for x in Path(ROOT / "eval/pre_reveal/cases.jsonl").read_text().splitlines()
    ]
    assert len({r["story"] for r in rows}) >= 8
    golden = {
        json.loads(x)["question"]
        for x in (ROOT / "eval/golden/questions.jsonl").read_text().splitlines()
        if x
    }
    assert not golden & {r["question"] for r in rows}, "the questions are new, not from eval/golden"
