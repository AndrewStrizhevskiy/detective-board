#!/usr/bin/env python3
"""Helpers for scripts/server_bootstrap.sh, server_run_all.sh and server_progress.sh.

No Ollama is needed for any of them (the report only shells out to read versions).

  check-models --list FILE [--models-md docs/team/models.md] TAG...   compare `ollama list` IDs
  pick-streams K=SEC_PER_CHUNK [K=SEC ...]                          best parallel stream count
  pick-probe-story --cache PARTIAL.sqlite [--model M]               first priority story not cached
  probe-split --story S --n 8 --streams K --outdir DIR              K chunk files, round-robin
  kv FILE key=value [...]                                           merge keys into a JSON file
  baseline [--model M]                                              chunks already in shard caches
  progress --dir data/cache/server [--model M]                      per-shard counts, rate, ETA
  report --dir data/cache/server --out report.md                    the final report.md
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODELS_MD = ROOT / "docs" / "team" / "models.md"
CHUNKS = ROOT / "data" / "chunks.jsonl"
SERVER_DIR = ROOT / "data" / "cache" / "server"
PREFER_FEWER_WITHIN = 0.05  # a larger stream count must be >5% faster to win


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def slug(model: str) -> str:
    """Same as extract_shard.sh: every char outside [A-Za-z0-9.] becomes '_'."""
    return re.sub(r"[^A-Za-z0-9.]", "_", model)


# ---------------------------------------------------------------- models table


def parse_models_table(text: str) -> dict[str, str]:
    """tag -> 12-char ID from the markdown table (rows like | `tag` | role | `id` | size |)."""
    out: dict[str, str] = {}
    for line in text.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 3:
            continue
        tag = re.fullmatch(r"`([^`]+)`", cells[0])
        digest = re.fullmatch(r"`([0-9a-f]{12})`", cells[2])
        if tag and digest:
            out[tag.group(1)] = digest.group(1)
    return out


def parse_ollama_list(text: str) -> dict[str, str]:
    """name -> ID from `ollama list` output (NAME ID SIZE MODIFIED)."""
    out: dict[str, str] = {}
    for line in text.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2 and re.fullmatch(r"[0-9a-f]{12}", parts[1]):
            out[parts[0]] = parts[1]
    return out


def compare_models(expected: dict[str, str], actual: dict[str, str], required: list[str]):
    """Return (lines, ok). A required tag may be given without ':latest'."""
    lines: list[str] = []
    ok = True
    for tag in required:
        want = expected.get(tag) or expected.get(f"{tag}:latest")
        have = actual.get(tag) or actual.get(f"{tag}:latest")
        if want is None:
            lines.append(f"UNKNOWN  {tag}: not in docs/team/models.md")
            ok = False
        elif have is None:
            lines.append(f"MISSING  {tag}: not pulled (expected {want})")
            ok = False
        elif have != want:
            lines.append(f"MISMATCH {tag}: server has {have}, docs/team/models.md says {want}")
            ok = False
        else:
            lines.append(f"OK       {tag} {have}")
    return lines, ok


# ---------------------------------------------------------------- stream count


def pick_streams(sec_per_chunk: dict[int, float], tol: float = PREFER_FEWER_WITHIN) -> int:
    """Stream count with the best throughput (lowest seconds per chunk, wall clock / chunks).

    The smallest count wins unless a larger one is more than `tol` faster than the current best.
    """
    if not sec_per_chunk:
        raise ValueError("no probe results")
    best = None
    for k in sorted(sec_per_chunk):
        if best is None or sec_per_chunk[k] < sec_per_chunk[best] * (1 - tol):
            best = k
    assert best is not None
    return best


# ---------------------------------------------------------------- chunks / caches


def read_chunks(path: Path, story: str | None = None) -> list[dict]:
    recs = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rec = json.loads(line)
                if story is None or rec.get("story") == story:
                    recs.append(rec)
    return recs


def cached_stories(chunks: Path, cache: Path, model: str) -> set[str]:
    """Stories having at least one chunk in `cache` under the default prompt/options."""
    mec = _load("merge_extract_cache")
    cfg = mec.ExtractConfig(model, 4096, 1536, 42)
    version = mec.load_prompt(mec.DEFAULT_PROMPT).version
    keys = mec.expected_keys(chunks, cfg, version)  # key -> chunk_id
    story_of = {r["chunk_id"]: r["story"] for r in read_chunks(chunks)}
    present: set[str] = set()
    if cache.exists():
        # SQLite creates -wal/-shm files even for reads: never open the repo file itself
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "c.sqlite"
            shutil.copy(cache, copy)
            wal = cache.with_name(cache.name + "-wal")
            if wal.exists():
                shutil.copy(wal, Path(tmp) / "c.sqlite-wal")
            present = {k for k, _ in _rows(copy)}
    return {story_of[cid] for k, cid in keys.items() if k in present}


def _rows(path: Path) -> list[tuple[str, str]]:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return conn.execute("SELECT key, value FROM raw").fetchall()
    finally:
        conn.close()


def count_rows(path: Path) -> int:
    if not path.exists():
        return 0
    try:
        return len(_rows(path))
    except sqlite3.Error:
        return 0


def pick_probe_story(stories: list[str], cached: set[str], counts: dict[str, int], n: int) -> str:
    for s in stories:
        if s not in cached and counts.get(s, 0) >= n:
            return s
    raise ValueError("every story is (partly) in the partial cache")


def split_round_robin(recs: list[dict], k: int) -> list[list[dict]]:
    return [recs[i::k] for i in range(k)]


# ---------------------------------------------------------------- progress


def progress_stats(
    done: int, total: int, baseline: int, started: float, now: float
) -> dict[str, float | None]:
    """Chunks per minute since launch (excluding what was cached before) and ETA in minutes."""
    minutes = max((now - started) / 60.0, 1e-9)
    new = max(done - baseline, 0)
    rate = new / minutes if new else 0.0
    remaining = max(total - done, 0)
    eta = remaining / rate if rate > 0 else None
    return {"per_min": rate, "eta_min": eta, "remaining": remaining}


def _fmt_eta(eta: float | None) -> str:
    if eta is None:
        return "n/a"
    h, m = divmod(int(round(eta)), 60)
    return f"{h}h{m:02d}m" if h else f"{m}m"


def _alive(pidfile: Path) -> bool:
    try:
        pid = int(pidfile.read_text().strip())
    except (OSError, ValueError):
        return False
    try:
        import os

        os.kill(pid, 0)
    except OSError:
        return False
    return True


def cmd_progress(a: argparse.Namespace) -> int:
    d = Path(a.dir)
    run = _read_json(d / "run.json")
    if not run:
        print("no run started yet (data/cache/server/run.json missing)")
        return 1
    n = int(run["streams"])
    es = _load("extract_shards")
    counts = es.chunk_counts()
    shards = es.plan_shards(es.priority_stories(), counts, n)
    sl = slug(a.model)
    now = time.time()
    tot_done = tot = 0
    print(f"{'shard':>5} {'state':<7} {'done':>9}  stories")
    for k, sh in enumerate(shards):
        total = sum(counts[s] for s in sh)
        done = count_rows(ROOT / "data" / "cache" / f"extract-cache-{sl}-shard{k}.sqlite")
        state = "running" if _alive(d / "pids" / f"shard{k}.pid") else "stopped"
        log = d / "logs" / f"shard{k}.log"
        if state == "stopped" and log.exists() and "failures: 0)" in log.read_text(errors="ignore"):
            state = "done"
        tot_done += done
        tot += total
        print(f"{k:>5} {state:<7} {done:>4}/{total:<4}  {len(sh)} stories")
    st = progress_stats(tot_done, tot, int(run.get("baseline", 0)), float(run["started"]), now)
    per_min = st["per_min"] or 0.0
    print(
        f"TOTAL {tot_done}/{tot}  {per_min:.2f} chunks/min  "
        f"remaining {int(st['remaining'] or 0)}  ETA {_fmt_eta(st['eta_min'])}"
    )
    return 0


# ---------------------------------------------------------------- report


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _sh(cmd: list[str]) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=20, cwd=ROOT)
        return (r.stdout or r.stderr).strip()
    except (OSError, subprocess.SubprocessError):
        return "unavailable"


def _commit() -> str:
    """Hash from git, or from the COMMIT file added by `git archive --add-file`."""
    if (ROOT / ".git").exists():
        dirty = (
            " (dirty)" if _sh(["git", "status", "--porcelain"]) not in ("", "unavailable") else ""
        )
        return _sh(["git", "rev-parse", "HEAD"]) + dirty
    f = ROOT / "COMMIT"
    return f.read_text().strip() if f.exists() else "unknown (no .git and no COMMIT file)"


def extract_stats(jsonls: list[Path]) -> dict:
    """Totals over extract.run result files (one JSON per line, ChunkResult.to_json())."""
    chunks = kept = dropped = 0
    status: dict[str, int] = {}
    reasons: dict[str, int] = {}
    wall = []
    for p in jsonls:
        with open(p, encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                r = json.loads(line)
                chunks += 1
                status[r["status"]] = status.get(r["status"], 0) + 1
                kept += sum(len(v) for v in r["extraction"].values())
                dropped += len(r["dropped"])
                for dr in r["dropped"]:
                    reasons[dr["reason"]] = reasons.get(dr["reason"], 0) + 1
                if not r["cached"] and r["status"] != "error":
                    wall.append(r["wall_s"])
    return {
        "chunks": chunks,
        "kept": kept,
        "dropped": dropped,
        "status": dict(sorted(status.items())),
        "dropped_by_reason": dict(sorted(reasons.items())),
        "live_sec_per_chunk": round(sum(wall) / len(wall), 1) if wall else None,
    }


def graph_stats(db: Path, all_stories: list[str] | None = None) -> dict:
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        q = lambda sql: conn.execute(sql).fetchone()[0]  # noqa: E731
        events = q("SELECT COUNT(*) FROM g_node WHERE kind='event'")
        claims = q("SELECT COUNT(*) FROM g_node WHERE kind='claim'")
        with_text = q(
            "SELECT COUNT(*) FROM g_node WHERE kind='event'"
            " AND COALESCE(json_extract(props_json,'$.time_text'),'')<>''"
        )
        timed = q(
            "SELECT COUNT(DISTINCT o.node_id) FROM g_overlay o JOIN g_node n ON n.id=o.node_id"
            " WHERE n.kind='event' AND o.key='time'"
        )
        dated = q(
            "SELECT COUNT(DISTINCT o.node_id) FROM g_overlay o JOIN g_node n ON n.id=o.node_id"
            " WHERE n.kind='event' AND o.key='story_day'"
        )
        props = q(
            "SELECT COUNT(DISTINCT o.node_id) FROM g_overlay o JOIN g_node n ON n.id=o.node_id"
            " WHERE n.kind='claim' AND o.key='prop'"
        )
        with_events = {
            r[0] for r in conn.execute("SELECT DISTINCT story FROM g_node WHERE kind='event'")
        }
        stories = set(all_stories or []) | {
            r[0] for r in conn.execute("SELECT DISTINCT story FROM g_chunk")
        }
        nodes = {k: c for k, c in conn.execute("SELECT kind, COUNT(*) FROM g_node GROUP BY kind")}
    finally:
        conn.close()
    share = lambda a, b: round(a / b, 3) if b else None  # noqa: E731
    return {
        "events": events,
        "claims": claims,
        "events_with_time_text": share(with_text, events),
        "events_with_time_norm": share(timed, events),
        "events_with_story_day": share(dated, events),
        "claims_with_prop": share(props, claims),
        "stories": len(stories),
        "stories_zero_events": sorted(stories - with_events),
        "nodes": dict(sorted(nodes.items())),
    }


def render_report(d: dict) -> str:
    def fmt(v):
        return "n/a" if v is None else str(v)

    det = d.get("determinism") or {}
    probe = d.get("probe") or {}
    run = d.get("run") or {}
    ex = d.get("extract") or {}
    g = d.get("graph") or {}
    L = ["# Server extraction report", ""]
    L += ["## Environment", ""]
    L += [f"- commit: `{d.get('commit')}`", f"- ollama: `{d.get('ollama')}`"]
    L += [f"- GPU / VRAM / driver: {d.get('gpu')}"]
    L += [f"- generated: {d.get('generated')}", "", "## Model IDs (`ollama list`)", ""]
    for tag, mid in sorted((d.get("models") or {}).items()):
        L.append(f"- `{tag}` {mid}")
    L += ["", "## Seconds per chunk", ""]
    L += ["| phase | seconds per chunk | note |", "|---|---|---|"]
    L.append(f"| determinism (3 chunks, 1 stream) | {fmt(det.get('sec_per_chunk'))} | |")
    for k, v in sorted((probe.get("results") or {}).items(), key=lambda kv: int(kv[0])):
        mark = " (chosen)" if str(probe.get("best")) == str(k) else ""
        L.append(f"| probe, {k} stream(s) | {fmt(v)} | wall clock / chunks{mark} |")
    L.append(
        f"| full run, {fmt(run.get('streams'))} streams, effective | "
        f"{fmt(run.get('effective_sec_per_chunk'))} | wall clock / live chunks |"
    )
    L.append(f"| full run, per request (mean) | {fmt(ex.get('live_sec_per_chunk'))} | |")
    L += ["", "## Determinism check against the laptop partial cache", ""]
    L.append(
        f"- compared {fmt(det.get('compared'))}, byte-identical {fmt(det.get('identical'))}, "
        f"different {fmt(det.get('different'))}"
    )
    L += ["", "## Corpus numbers", ""]
    L.append(f"- total chunks: {fmt(ex.get('chunks'))} (status {ex.get('status')})")
    L.append(f"- items kept: {fmt(ex.get('kept'))}, dropped: {fmt(ex.get('dropped'))}")
    L.append(f"- dropped by reason: {ex.get('dropped_by_reason')}")
    L.append(
        f"- events with a time (time_text): {fmt(g.get('events_with_time_text'))}; "
        f"normalised time: {fmt(g.get('events_with_time_norm'))}; "
        f"with story day: {fmt(g.get('events_with_story_day'))} (of {fmt(g.get('events'))} events)"
    )
    L.append(
        f"- claims with a proposition: {fmt(g.get('claims_with_prop'))} (of {fmt(g.get('claims'))})"
    )
    L.append(
        f"- stories with zero events: {g.get('stories_zero_events')} (of {fmt(g.get('stories'))})"
    )
    if d.get("gold12"):
        L += ["", "## gold12 quality check", ""]
        for name, v in sorted(d["gold12"].items()):
            L.append(
                f"- {name}: sec_per_chunk_live {fmt(v.get('sec_per_chunk_live'))}, "
                f"valid_json_rate {fmt(v.get('valid_json_rate'))}, "
                f"grounded_rate {fmt(v.get('grounded_rate'))}"
            )
        L.append("- full table: docs/spike/results/gold12-*.md")
    L += ["", "## Anything unusual", "", "(write here)", ""]
    return "\n".join(L)


def collect(d: Path) -> dict:
    data: dict = {
        "commit": _commit(),
        "ollama": _sh(["ollama", "--version"]),
        "gpu": _sh(
            ["nvidia-smi", "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader"]
        ),
        "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "models": parse_ollama_list(_sh(["ollama", "list"])),
        "determinism": _read_json(d / "determinism.json"),
        "probe": _read_json(d / "probe.json"),
        "run": _read_json(d / "run.json"),
    }
    outs = sorted((ROOT / "data" / "cache").glob("extract-*.jsonl"))
    outs = [p for p in outs if p.name not in ("extract-cache.sqlite",)]
    data["extract"] = extract_stats(outs) if outs else {}
    gdb = ROOT / "data" / "graph" / "graph.sqlite"
    if gdb.exists():
        data["graph"] = graph_stats(gdb)
    gold = {}
    for p in sorted((ROOT / "data" / "cache" / "gold12").glob("*.report.json")):
        rep = _read_json(p)
        if rep:
            gold[p.name.removesuffix(".report.json")] = rep
    data["gold12"] = gold
    return data


# ---------------------------------------------------------------- CLI


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check-models")
    c.add_argument("--list", type=Path, required=True)
    c.add_argument("--models-md", type=Path, default=MODELS_MD)
    c.add_argument("tags", nargs="+")
    p = sub.add_parser("pick-streams")
    p.add_argument("pairs", nargs="+", help="K=seconds_per_chunk")
    s = sub.add_parser("pick-probe-story")
    s.add_argument("--cache", type=Path, required=True)
    s.add_argument("--model", default="qwen3:4b")
    s.add_argument("--n", type=int, default=8)
    sp = sub.add_parser("probe-split")
    sp.add_argument("--story", required=True)
    sp.add_argument("--n", type=int, default=8)
    sp.add_argument("--streams", type=int, required=True)
    sp.add_argument("--outdir", type=Path, required=True)
    k = sub.add_parser("kv")
    k.add_argument("file", type=Path)
    k.add_argument("pairs", nargs="+")
    pr = sub.add_parser("progress")
    pr.add_argument("--dir", default=str(SERVER_DIR))
    pr.add_argument("--model", default="qwen3:4b")
    bl = sub.add_parser("baseline")
    bl.add_argument("--model", default="qwen3:4b")
    r = sub.add_parser("report")
    r.add_argument("--dir", default=str(SERVER_DIR))
    r.add_argument("--out", type=Path, default=SERVER_DIR / "report.md")
    a = ap.parse_args(argv)

    if a.cmd == "check-models":
        lines, ok = compare_models(
            parse_models_table(a.models_md.read_text(encoding="utf-8")),
            parse_ollama_list(a.list.read_text(encoding="utf-8")),
            a.tags,
        )
        print("\n".join(lines))
        return 0 if ok else 1
    if a.cmd == "pick-streams":
        res = {int(x.split("=")[0]): float(x.split("=")[1]) for x in a.pairs}
        print(pick_streams(res))
        return 0
    if a.cmd == "pick-probe-story":
        es = _load("extract_shards")
        print(
            pick_probe_story(
                es.priority_stories(),
                cached_stories(CHUNKS, a.cache, a.model),
                dict(es.chunk_counts()),
                a.n,
            )
        )
        return 0
    if a.cmd == "probe-split":
        recs = read_chunks(CHUNKS, a.story)[: a.n]
        a.outdir.mkdir(parents=True, exist_ok=True)
        for i, part in enumerate(split_round_robin(recs, a.streams)):
            with open(a.outdir / f"part{i}.jsonl", "w", encoding="utf-8") as f:
                for rec in part:
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print(len(recs))
        return 0
    if a.cmd == "kv":
        cur = _read_json(a.file)
        for pair in a.pairs:
            key, _, val = pair.partition("=")
            try:
                cur[key] = json.loads(val)
            except ValueError:
                cur[key] = val
        a.file.parent.mkdir(parents=True, exist_ok=True)
        a.file.write_text(json.dumps(cur, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        return 0
    if a.cmd == "progress":
        return cmd_progress(a)
    if a.cmd == "baseline":
        pat = f"extract-cache-{slug(a.model)}-shard*.sqlite"
        print(sum(count_rows(p) for p in (ROOT / "data" / "cache").glob(pat)))
        return 0
    data = collect(Path(a.dir))
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(render_report(data), encoding="utf-8")
    print(f"wrote {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
