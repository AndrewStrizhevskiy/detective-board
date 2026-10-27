"""scripts/spike/presence_eval.py: gold construction and scoring, with canned predictions."""

import importlib.util
import json
import sys

from detective_board.extract import presence
from detective_board.extract.presence import PROMPT_V1

from .helpers import ROOT, fact, fake_by_passage, records, write_chunks

_spec = importlib.util.spec_from_file_location(
    "presence_eval", ROOT / "scripts" / "spike" / "presence_eval.py"
)
pe = importlib.util.module_from_spec(_spec)
sys.modules["presence_eval"] = pe
_spec.loader.exec_module(pe)


def gold():
    return pe.build_gold(
        records(),
        ROOT / "eval" / "extraction_gold",
        ROOT / "eval" / "golden" / "contradictions.jsonl",
    )


def test_gold_is_built_from_the_extraction_gold_and_the_contradiction_cases():
    g = gold()
    assert {x["source"].split(":")[0] for x in g} == {"extraction_gold", "contradiction", "hand"}
    assert {x["source"] for x in g if x["source"].startswith("contradiction")} >= {
        "contradiction:c001", "contradiction:c003"
    }  # fmt: skip
    strict = [x for x in g if x["strict"]]
    assert 3 <= len(strict) < len(g)  # most gold needs text outside the quote
    for x in g:
        text = records()[x["chunk_id"]]["text"]
        assert pe.normalise(x["quote"]).text in pe.normalise(text).text  # verbatim, right chunk
        assert x["strict"] == all(x["in_quote"].values())
    c001 = [x for x in g if x["source"] == "contradiction:c001"]
    assert len(c001) == 3 and not any(x["strict"] for x in c001)
    assert [x["id"] for x in g] == [f"pg{i:03d}" for i in range(len(g))]


def run_runner(tmp_path, table, *extra):
    chunks = sorted({x["chunk_id"] for x in gold() if x["strict"]})
    out = tmp_path / "pred.jsonl"
    rc = presence.main(
        ["--model", "fake", "--chunks", str(write_chunks(tmp_path / "ch.jsonl", *chunks)),
         "--cache", str(tmp_path / "c.sqlite"), "--out", str(out), "--prompt", str(PROMPT_V1), *extra],
        client=fake_by_passage(table),
    )  # fmt: skip
    assert rc == 0
    return [json.loads(line) for line in out.read_text().splitlines()]


def canned_from_gold():
    table: dict[str, list[dict]] = {}
    for x in gold():
        if x["strict"]:
            key = x["quote"][:30]
            table.setdefault(key, []).append(
                fact(person=x["person"], place=x["place_forms"][-1], time_text=x["time_text"],
                     quote=x["quote"])
            )  # fmt: skip
    return table


def test_perfect_predictions_score_one_on_the_strict_tier(tmp_path):
    preds = run_runner(tmp_path, canned_from_gold())
    r = pe.score(gold(), preds, records())
    s = r["strict"]
    assert (s["gold"], s["recall_quote"], s["recall_full"], s["precision"]) == (
        len([x for x in gold() if x["strict"]]), 1.0, 1.0, 1.0,
    )  # fmt: skip
    assert r["survival"] == 1.0 and r["quote_grounded"] == 1.0 and r["unjudged_preds"] == 0
    # context gold is reached only when its quote overlaps a strict prediction (James/Bristol)
    assert (
        r["all"]["recall_full"] >= round(s["gold"] / len(gold()), 3)
        and r["all"]["recall_full"] < 0.5
    )


def test_wrong_place_hits_the_quote_but_not_the_fields(tmp_path):
    table = {
        k: [{**f, "place": "Hatherley"} for f in v if f["place"] != "Hatherley"] or v
        for k, v in canned_from_gold().items()
    }
    # the Pyland maid is placed in "Hatherley" (a place of another chunk) -> grounding drops it
    preds = run_runner(tmp_path, table)
    r = pe.score(gold(), preds, records())
    assert r["survival"] < 1.0 and r["strict"]["recall_full"] < 1.0


def test_no_predictions_and_empty_runs():
    r = pe.score(gold(), [], records())
    assert r["strict"]["recall_quote"] == 0.0 and r["survival"] == 0.0 and r["chunks"] == 0
    assert pe.score([], [], records())["all"]["gold"] == 0


def test_cli_writes_gold_and_scores(tmp_path, capsys):
    preds = run_runner(tmp_path, canned_from_gold())
    pf = tmp_path / "p.jsonl"
    pf.write_text("".join(json.dumps(p) + "\n" for p in preds), encoding="utf-8")
    gold_out, score_out = tmp_path / "gold.jsonl", tmp_path / "s.json"
    assert pe.main([str(pf), "--gold-out", str(gold_out), "--json", str(score_out)]) == 0
    assert len(gold_out.read_text().splitlines()) == len(gold())
    doc = json.loads(score_out.read_text())
    assert doc["scores"][str(pf)]["strict"]["recall_full"] == 1.0
    assert pe.main([str(pf), "--gold", str(gold_out)]) == 0  # a stored gold works too
    assert "gold:" in capsys.readouterr().err


def test_scores_per_stage_grounded_voted_verified(tmp_path):
    preds = run_runner(tmp_path, canned_from_gold())
    old = [{k: v for k, v in p.items() if k != "stages"} for p in preds]
    assert pe.score_stages(gold(), old, records()) == {}  # older records: nothing to split
    first = next(p for p in preds if p["facts"])
    bad = {**first["facts"][0], "place": "Nowhere Hall"}  # wrong place, same quote
    for p in preds:
        p["stages"] = {st: list(p["facts"]) for st in pe.STAGES}
    first["stages"]["grounded"] = [*first["facts"], bad]
    first["stages"]["voted"] = [*first["facts"], bad]  # the verifier is what removes it
    st = pe.score_stages(gold(), preds, records())
    assert st["grounded"]["strict"]["precision"] < 1.0 == st["verified"]["strict"]["precision"]
    assert st["verified"]["strict"]["recall_full"] == st["grounded"]["strict"]["recall_full"]
    assert st["grounded"]["facts"] == st["verified"]["facts"] + 1
    assert list(st) == ["grounded", "voted", "verified"]
