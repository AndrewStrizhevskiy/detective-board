import pytest
from chunk_gold import find_spans

from .conftest import load

M = load("metrics")


def test_wilson_known_values_and_empty():
    lo, hi = M.wilson(5, 10)
    assert (round(lo, 4), round(hi, 4)) == (0.2366, 0.7634)
    assert M.wilson(0, 0) == (0.0, 1.0)
    lo, hi = M.wilson(0, 8)
    assert lo == 0.0 and 0.3 < hi < 0.33
    assert M.wilson(8, 8)[1] == 1.0


def test_share_never_turns_zero_over_zero_into_zero():
    assert M.share(0, 0)["value"] is None
    s = M.share(3, 4)
    assert (s["k"], s["n"], s["value"]) == (3, 4, 0.75)
    assert s["ci95"][0] < 0.75 < s["ci95"][1]


def test_mcnemar_exact():
    assert M.mcnemar_exact(0, 0) == 1.0
    assert M.mcnemar_exact(0, 5) == pytest.approx(0.0625)
    assert M.mcnemar_exact(1, 4) == pytest.approx(0.375)
    assert M.mcnemar_exact(3, 3) == 1.0


def test_paired_uses_only_shared_ids():
    p = M.paired({"a": True, "b": False, "c": True}, {"a": True, "b": True, "x": True})
    assert (p["n"], p["only_a"], p["only_b"]) == (2, 0, 1)


def test_duplicate_and_empty_citations_count_once():
    cites = [
        {"chunk_id": "c1", "quote": "the deadliest  snake"},
        {"chunk_id": "c1", "quote": "the deadliest snake"},
        {"chunk_id": "c1", "quote": "   "},
        {"chunk_id": "c2", "quote": "the deadliest snake"},
    ]
    assert [c["chunk_id"] for c in M.unique_citations(cites)] == ["c1", "c2"]


def test_citation_needs_verbatim_quote_and_gold_chunk():
    text = {
        "c1": "“It is a swamp adder!” cried Holmes;\n“the deadliest snake in India.",
        "c2": "Another passage.",
    }
    cites = [
        {
            "chunk_id": "c1",
            "quote": "the deadliest snake in India",
        },  # verbatim (line break tolerated), gold
        {"chunk_id": "c2", "quote": "the deadliest snake in India"},  # not in this chunk
        {"chunk_id": "c9", "quote": "anything"},  # unknown chunk
    ]
    v = M.citation_verdicts(cites, text, ["c1"], find_spans)
    assert [(x["verbatim"], x["gold_chunk"], x["correct"]) for x in v] == [
        (True, True, True),
        (False, False, False),
        (False, False, False),
    ]
    assert M.citation_verdicts([], text, ["c1"], find_spans) == []


def test_answer_sentence_hit_by_span_overlap_in_the_right_story():
    story = {"s": "Alpha beta gamma. The swamp adder bit him. Delta epsilon."}
    start = story["s"].index("The swamp")
    gold = [("s", start, start + len("The swamp adder bit him."))]
    assert M.answer_sentence_hit([{"story": "s", "quote": "swamp adder"}], story, gold, find_spans)
    assert not M.answer_sentence_hit(
        [{"story": "s", "quote": "Delta epsilon"}], story, gold, find_spans
    )
    assert not M.answer_sentence_hit(
        [{"story": "other", "quote": "swamp adder"}], story, gold, find_spans
    )
    assert not M.answer_sentence_hit([], story, gold, find_spans), "an empty answer hits nothing"


def test_refusal_counts():
    rows = [
        {"answerable": False, "refused": True},
        {"answerable": False, "refused": False},
        {"answerable": True, "refused": True},
        {"answerable": True, "refused": False},
        {"answerable": True, "refused": False},
    ]
    r = M.refusal_counts(rows)
    assert (r["refusal_precision"]["k"], r["refusal_precision"]["n"]) == (1, 2)
    assert (r["refusal_recall"]["k"], r["refusal_recall"]["n"]) == (1, 2)
    assert (r["false_refusal_rate"]["k"], r["false_refusal_rate"]["n"]) == (1, 3)
    empty = M.refusal_counts([])
    assert empty["refusal_precision"]["value"] is None


def test_recall_at_k():
    assert M.recall_at_k(["a", "b", "g"], ["g"], 2) is False
    assert M.recall_at_k(["a", "b", "g"], ["g"], 3) is True
    assert M.recall_at_k([], ["g"], 4) is False
    assert M.recall_at_k(["a"], [], 4) is None


def test_detection_counts_f1_and_control_fp_rate():
    items = [
        {"expected": True, "found": True},
        {"expected": True, "found": False},
        {"expected": False, "found": True},
        {"expected": False, "found": False},
        {"expected": False, "found": False},
    ]
    d = M.detection(items)
    assert (d["tp"], d["fp"], d["fn"], d["tn"]) == (1, 1, 1, 2)
    assert d["precision"]["value"] == 0.5 and d["recall"]["value"] == 0.5 and d["f1"] == 0.5
    assert (d["fp_rate_controls"]["k"], d["fp_rate_controls"]["n"]) == (1, 3)
    none = M.detection([])
    assert none["f1"] is None and none["precision"]["value"] is None
