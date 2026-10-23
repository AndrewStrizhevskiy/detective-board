"""Sharding balance and shard-cache merge/verify (tiny temp caches, no Ollama)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


shards = _load("extract_shards")
merge = _load("merge_extract_cache")

from detective_board.extract import schema_v2  # noqa: E402
from detective_board.extract.cache import ExtractCache, cache_key  # noqa: E402
from detective_board.extract.pipeline import ExtractConfig  # noqa: E402


def test_priority_list_has_20_stories():
    st = shards.priority_stories()
    assert len(st) == 20 and len(set(st)) == 20 and st[0] == "boscombe-valley-mystery"


@pytest.mark.parametrize("n", [1, 2, 4, 7])
def test_plan_partitions_all_stories_once(n):
    st = shards.priority_stories()
    counts = {s: 10 + (i * 7) % 23 for i, s in enumerate(st)}
    plan = shards.plan_shards(st, counts, n)
    flat = [s for sh in plan for s in sh]
    assert sorted(flat) == sorted(st) and len(plan) == n
    for sh in plan:  # priority order kept inside a shard
        assert sh == sorted(sh, key=st.index)


def test_plan_balance_on_real_corpus():
    counts = shards.chunk_counts()
    st = shards.priority_stories()
    assert set(st) <= set(counts)
    plan = shards.plan_shards(st, counts, 4)
    loads = [sum(counts[s] for s in sh) for sh in plan]
    assert max(loads) - min(loads) <= max(counts[s] for s in st)
    assert max(loads) <= 1.15 * sum(loads) / 4


def test_plan_is_deterministic_and_validates():
    st = ["a", "b", "c"]
    c = {"a": 5, "b": 5, "c": 5}
    assert shards.plan_shards(st, c, 2) == shards.plan_shards(st, c, 2)
    with pytest.raises(ValueError):
        shards.plan_shards(st, c, 0)


CFG = ExtractConfig("m:1")
PV = "v-test"


def _key(text: str, cfg=CFG, pv=PV, sv=schema_v2.SCHEMA_VERSION) -> str:
    return cache_key(text, cfg.model, pv, sv, cfg.options())


@pytest.fixture
def chunks(tmp_path):
    p = tmp_path / "chunks.jsonl"
    rows = [{"chunk_id": f"s-{i:04d}", "story": "s", "text": f"text {i}"} for i in range(5)]
    p.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    return p


def _fill(path: Path, items: dict[str, str]) -> Path:
    c = ExtractCache(path)
    for k, t in items.items():
        c.put(k, {"text": t})
    c.close()
    return path


def test_merge_idempotent_and_counts(tmp_path, chunks):
    exp = merge.expected_keys(chunks, CFG, PV)
    a = _fill(tmp_path / "a.sqlite", {_key("text 0"): "A0", _key("text 1"): "A1"})
    b = _fill(tmp_path / "b.sqlite", {_key("text 2"): "B2", _key("text 1"): "A1"})
    dest = tmp_path / "main.sqlite"
    r1 = merge.merge_caches(dest, [a, b], exp)
    assert (r1.added, r1.already_present, r1.total_dest) == (3, 1, 3)
    r2 = merge.merge_caches(dest, [a, b], exp)
    assert (r2.added, r2.total_dest) == (0, 3) and not r2.conflicts


def test_merge_refuses_foreign_model_prompt_schema(tmp_path, chunks):
    exp = merge.expected_keys(chunks, CFG, PV)
    other = ExtractConfig("other:2")
    bad = {
        "model": _key("text 0", cfg=other),
        "prompt": _key("text 0", pv="v-other"),
        "schema": _key("text 0", sv="999"),
    }
    for name, k in bad.items():
        src = _fill(tmp_path / f"{name}.sqlite", {k: "x", _key("text 3"): "ok"})
        dest = tmp_path / f"d-{name}.sqlite"
        with pytest.raises(ValueError, match="--force"):
            merge.merge_caches(dest, [src], exp)
        assert not dest.exists() or len(ExtractCache(dest)) == 0
        rep = merge.merge_caches(dest, [src], exp, force=True)
        assert rep.added == 2 and rep.foreign_merged == 1


def test_merge_reports_conflict_keeps_dest(tmp_path, chunks):
    exp = merge.expected_keys(chunks, CFG, PV)
    k = _key("text 0")
    dest = _fill(tmp_path / "main.sqlite", {k: "old"})
    src = _fill(tmp_path / "s.sqlite", {k: "new"})
    rep = merge.merge_caches(dest, [src], exp)
    assert rep.conflicts == [k] and rep.added == 0
    assert ExtractCache(dest).get(k) == {"text": "old"}


def test_dry_run_writes_nothing(tmp_path, chunks):
    exp = merge.expected_keys(chunks, CFG, PV)
    src = _fill(tmp_path / "s.sqlite", {_key("text 0"): "x"})
    dest = tmp_path / "main.sqlite"
    rep = merge.merge_caches(dest, [src], exp, dry_run=True)
    assert rep.added == 1 and not dest.exists()


def test_verify_compares_raw_outputs(tmp_path, chunks):
    exp = merge.expected_keys(chunks, CFG, PV)
    a = _fill(
        tmp_path / "a.sqlite", {_key("text 0"): "same", _key("text 1"): "L", _key("text 2"): "z"}
    )
    b = _fill(tmp_path / "b.sqlite", {_key("text 0"): "same", _key("text 1"): "R"})
    rep = merge.verify_caches(a, b, exp, n=3)
    assert (rep.compared, rep.identical, rep.different, rep.missing) == (
        2,
        1,
        ["s-0001"],
        ["s-0002"],
    )
    assert merge.verify_caches(a, b, exp, n=1).compared == 1


def test_cli_refuses_then_forces(tmp_path, chunks, capsys):
    src = _fill(tmp_path / "s.sqlite", {_key("text 0", cfg=ExtractConfig("zzz")): "x"})
    prompt = tmp_path / "p.txt"
    prompt.write_text(f"version: {PV}\n---\n{{{{CHUNK}}}}\n", encoding="utf-8")
    base = ["merge", str(tmp_path / "m.sqlite"), str(src), "--model", "m:1",
            "--chunks", str(chunks)]  # fmt: skip
    from detective_board.extract.pipeline import CHUNK_MARK

    prompt.write_text(f"version: {PV}\n---\n{CHUNK_MARK}\n", encoding="utf-8")
    base += ["--prompt", str(prompt)]
    assert merge.main(base) == 1
    assert merge.main([*base, "--force"]) == 0
    assert "added=1" in capsys.readouterr().out
