"""Human-review kit for the gold sets (issue #9): scripts/eval/review_kit.py and apply_review.py."""

import csv
import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _script(name):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / "eval" / f"{name}.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


kit = _script("review_kit")
ap = _script("apply_review")
KIT = ROOT / "eval" / "review" / "2026-10-29"


def _sets():
    golden, contra = kit.load_jsonl(kit.GOLDEN), kit.load_jsonl(kit.CONTRA)
    return golden, contra, json.loads(kit.SPLIT.read_text(encoding="utf-8"))


def test_the_selection_has_the_issue_sizes_and_every_named_id():
    golden, contra, split = _sets()
    g, c = kit.select(golden, contra, split)
    assert len(g) == 20 and len(c) == 16 and len(kit.CHUNKS) == 4
    assert set(kit.NAMED_GOLDEN) <= set(g) and set(kit.NAMED_CONTRA) <= set(c)
    test = set(split["content"]["golden"]["test"])
    assert len([i for i in g if i in test and i not in kit.NAMED_GOLDEN]) >= 6, (
        "6 more from the test split"
    )
    assert "g027" in g and "c042" in c, "the disagreement the issue asks to resolve"
    assert kit.select(golden, contra, split) == (g, c), "deterministic"


def test_the_committed_kit_is_what_the_script_builds(tmp_path):
    kit.build(tmp_path, "2026-10-29")
    for name in ("golden.md", "contradictions.md", "extraction.md", "verdicts.csv"):
        assert (tmp_path / name).read_text(encoding="utf-8") == (KIT / name).read_text(
            encoding="utf-8"
        ), f"re-run review_kit.py: {name}"


def test_every_quote_is_shown_in_its_passage_and_none_fails():
    for name in ("golden.md", "contradictions.md", "extraction.md"):
        text = (KIT / name).read_text(encoding="utf-8")
        assert "pre-check: FAIL" not in text, name
    golden = (KIT / "golden.md").read_text(encoding="utf-8")
    assert "**a salary of £ 4 a week for purely nominal services**" in golden


def test_a_missing_quote_is_flagged_not_hidden():
    corpus = {"s": "One line.\n\nHe said it was nearly one o’clock.\n\nEnd."}
    assert kit.quote_block(corpus, "s", "nearly one   o’clock")[0] == "verbatim, 1 place"
    assert kit.quote_block(corpus, "s", "nearly two o’clock")[0].startswith("FAIL")
    assert kit.quote_block(corpus, "t", "x")[0].startswith("FAIL")
    note, text = kit.quote_block(corpus, "s", "nearly one o’clock")
    assert "**nearly one o’clock**" in text and "End" not in text, "the quote's own paragraph"


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """Copies of the gold sets; apply_review writes there, never to the repo."""
    g = tmp_path / "golden"
    g.mkdir()
    for p in ap.SETS.values():
        shutil.copy(p, g / p.name)
    x = tmp_path / "extraction"
    shutil.copytree(ap.EXTRACTION, x)
    monkeypatch.setattr(ap, "SETS", {k: g / p.name for k, p in ap.SETS.items()})
    monkeypatch.setattr(ap, "EXTRACTION", x)
    return tmp_path


def _csv(tmp_path, fill):
    rows = list(csv.DictReader((KIT / "verdicts.csv").open(encoding="utf-8")))
    for r in rows:
        r.update(fill.get(r["item_id"], {}))
    out = tmp_path / "verdicts.csv"
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=kit.CSV_FIELDS)
        w.writeheader()
        w.writerows(rows)
    return out


def test_ok_and_fixed_items_get_reviewed_fields_and_nothing_else_changes(sandbox):
    before = {p.name: p.read_text(encoding="utf-8").splitlines() for p in ap.SETS.values()}
    ok = {"reviewer": "LitrumCoder", "date": "2026-10-30", "verdict": "ok"}
    chunk = "silver-blaze-0004"
    xrows = [
        r["item_id"]
        for r in csv.DictReader((KIT / "verdicts.csv").open())
        if f":{chunk}:" in r["item_id"]
    ]
    fill = {
        "g027": ok,
        "c042": {**ok, "verdict": "fixed", "fix": "note: see g027"},
        "g029": {**ok, "verdict": "unsure", "fix": "dates"},
    }
    fill.update({i: ok for i in xrows})
    out = _csv(sandbox, fill)
    assert ap.main([str(out)]) == 0
    for p in ap.SETS.values():
        after = p.read_text(encoding="utf-8").splitlines()
        for old, new in zip(before[p.name], after, strict=True):
            item = json.loads(new)
            if item["id"] in ("g027", "c042"):
                assert (item["reviewed_by"], item["reviewed_on"]) == ("LitrumCoder", "2026-10-30")
                assert {
                    k: v for k, v in item.items() if not k.startswith("reviewed_")
                } == json.loads(old)
            else:
                assert new == old, f"{item['id']} must stay byte for byte"
    data = json.loads((ap.EXTRACTION / f"{chunk}.json").read_text(encoding="utf-8"))
    assert data["reviewed_by"] == "LitrumCoder"
    other = ap.EXTRACTION / "naval-treaty-0007.json"
    assert other.read_text(encoding="utf-8") == (
        ROOT / "eval/extraction_gold/naval-treaty-0007.json"
    ).read_text(encoding="utf-8")
    assert ap.main([str(out)]) == 0, "idempotent"


def test_a_badly_filled_row_stops_everything(sandbox):
    before = ap.SETS["golden"].read_text(encoding="utf-8")
    for bad in (
        {"reviewer": "LitrumCoder", "date": "30.10.2026", "verdict": "ok"},
        {"reviewer": "two words", "date": "2026-10-30", "verdict": "ok"},
        {"reviewer": "LitrumCoder", "date": "2026-10-30", "verdict": "fine"},
        {"reviewer": "LitrumCoder", "date": "2026-10-30", "verdict": "fixed"},
    ):
        out = _csv(
            sandbox,
            {
                "g004": bad,
                "g005": {"reviewer": "LitrumCoder", "date": "2026-10-30", "verdict": "ok"},
            },
        )
        assert ap.main([str(out)]) == 1
        assert ap.SETS["golden"].read_text(encoding="utf-8") == before


def test_status_counts_for_the_disclosure_table(sandbox, capsys):
    ok = {"reviewer": "LitrumCoder", "date": "2026-10-30", "verdict": "ok", "time_min": "4"}
    out = _csv(sandbox, {"g004": ok, "g005": {**ok, "verdict": "drop", "fix": "wrong story"}})
    before = ap.SETS["golden"].read_text(encoding="utf-8")
    assert ap.main([str(out), "--status"]) == 0
    text = capsys.readouterr().out
    assert (
        "golden: 2 of 20 rows reviewed by LitrumCoder on 2026-10-30; ok 1, fixed 0, drop 1, unsure 0; 8 min"
        in text
    )
    assert "contradictions: 0 of 16 rows" in text and "extraction: 0 of 32 rows" in text
    assert ap.SETS["golden"].read_text(encoding="utf-8") == before, "--status writes nothing"
