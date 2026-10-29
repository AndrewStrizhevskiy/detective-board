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


def _keys(path):
    with path.open(newline="", encoding="utf-8-sig") as f:
        return [(r["item_id"], r["set"], r["assignee"]) for r in csv.DictReader(f)]


def test_the_committed_kit_lists_what_the_script_selects(tmp_path):
    """Rows (id, set, assignee) match a fresh build; the filled-in columns and the dated sheets
    may differ once reviewers work, so they are not compared."""
    kit.build(tmp_path, "2026-10-29")
    assert _keys(KIT / "verdicts.csv") == _keys(tmp_path / "verdicts.csv"), "re-run review_kit.py"
    golden, contra, split = _sets()
    g, c = kit.select(golden, contra, split)
    sheets = {
        n: (KIT / n).read_text(encoding="utf-8")
        for n in ("golden.md", "contradictions.md", "extraction.md")
    }
    for i in g:
        assert f"## {i} ·" in sheets["golden.md"], i
    for i in c:
        assert f"## {i} ·" in sheets["contradictions.md"], i
    for ch in kit.CHUNKS:
        assert f"## {ch} (" in sheets["extraction.md"], ch


def test_a_rebuild_never_overwrites_filled_verdicts(tmp_path):
    kit.build(tmp_path, "2026-10-29")
    target = tmp_path / "verdicts.csv"
    text = target.read_text(encoding="utf-8").replace(
        "g004,golden,A,,,,,", "g004,golden,A,LitrumCoder,2026-10-30,ok,,3"
    )
    target.write_text(text, encoding="utf-8")
    kit.build(tmp_path, "2026-10-29")
    assert target.read_text(encoding="utf-8") == text


def test_the_extraction_sheet_says_where_its_text_is_from_and_keeps_paragraphs():
    sheet = (KIT / "extraction.md").read_text(encoding="utf-8")
    assert "chunk's own `text` field" in sheet and "Passages are from `data/clean/`" not in sheet
    assert "\n>\n> " in sheet, "paragraphs (lines of dialogue) stay apart"


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


def test_a_chunk_is_marked_with_its_scope_in_its_own_format_and_only_when_complete(sandbox):
    ok = {"reviewer": "LitrumCoder", "date": "2026-10-30", "verdict": "ok"}
    rows = [
        r["item_id"]
        for r in csv.DictReader((KIT / "verdicts.csv").open())
        if ":naval-treaty-0007:" in r["item_id"]
    ]
    out = _csv(sandbox, {i: ok for i in rows[:-1]})
    assert ap.main([str(out)]) == 0
    path = ap.EXTRACTION / "naval-treaty-0007.json"
    assert "reviewed_by" not in json.loads(path.read_text(encoding="utf-8")), "one row still open"
    out = _csv(sandbox, {i: ok for i in rows})
    assert ap.main([str(out)]) == 0
    text = path.read_text(encoding="utf-8")
    data = json.loads(text)
    assert (data["reviewed_by"], data["reviewed_on"], data["reviewed_scope"]) == (
        "LitrumCoder",
        "2026-10-30",
        ["claims", "relations"],
    )
    assert text == json.dumps(data, ensure_ascii=False, indent=1), "indent 1, no newline at the end"
    other = {**ok, "reviewer": "someone-else"}
    out = _csv(sandbox, {**{i: ok for i in rows[:-1]}, rows[-1]: other})
    with pytest.raises(SystemExit, match="one reviewer"):
        ap.main([str(out)])


def test_an_id_the_files_do_not_have_stops_before_anything_is_written(sandbox, tmp_path):
    before = {p: p.read_text(encoding="utf-8") for p in ap.SETS.values()}
    out = _csv(
        sandbox, {"g004": {"reviewer": "LitrumCoder", "date": "2026-10-30", "verdict": "ok"}}
    )
    text = out.read_text(encoding="utf-8").replace("g005,golden", "g999,golden")
    out.write_text(
        text.replace("g005,golden", "g999,golden").replace(
            ",B,,,,,", ",B,LitrumCoder,2026-10-30,ok,,", 1
        ),
        encoding="utf-8",
    )
    with pytest.raises(SystemExit, match="no item g999"):
        ap.main([str(out)])
    assert {p: p.read_text(encoding="utf-8") for p in ap.SETS.values()} == before


@pytest.mark.parametrize(
    "fill, why",
    [
        ({"reviewer": "LitrumCoder", "date": "2026-13-45", "verdict": "ok"}, "real date"),
        (
            {"reviewer": "LitrumCoder", "date": "2026-10-30", "fix": "forgot the verdict"},
            "no verdict",
        ),
    ],
)
def test_impossible_dates_and_half_filled_rows_are_refused(sandbox, capsys, fill, why):
    out = _csv(sandbox, {"g004": fill})
    assert ap.main([str(out)]) == 1
    assert why in capsys.readouterr().out


def test_a_spreadsheet_resave_is_read_or_refused_clearly(sandbox, capsys):
    out = _csv(
        sandbox, {"g004": {"reviewer": "LitrumCoder", "date": "2026-10-30", "verdict": "ok"}}
    )
    out.write_bytes(b"\xef\xbb\xbf" + out.read_bytes())  # BOM: still read
    assert ap.main([str(out), "--status"]) == 0
    out.write_text(out.read_text(encoding="utf-8-sig").replace(",", ";"), encoding="utf-8")
    assert ap.main([str(out)]) == 1
    assert "header must be" in capsys.readouterr().out
