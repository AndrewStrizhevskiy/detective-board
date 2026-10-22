"""CLI: python -m detective_board.extract.run --model M --chunks CHUNKS.jsonl --out OUT.jsonl"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Sequence
from pathlib import Path

from detective_board.extract.cache import ExtractCache
from detective_board.extract.llm import LLMClient, OllamaClient
from detective_board.extract.pipeline import (
    DEFAULT_PROMPT,
    ChunkResult,
    ExtractConfig,
    Extractor,
    load_prompt,
)


def build_report(results: Sequence[ChunkResult]) -> dict:
    n = len(results)
    live = [r for r in results if not r.cached and r.status != "error"]
    g = {"exact": 0, "fuzzy": 0, "none": 0}
    reasons: dict[str, int] = {}
    for r in results:
        for k in g:
            g[k] += r.grounding[k]
        for d in r.dropped:
            reasons[d["reason"]] = reasons.get(d["reason"], 0) + 1
    graded = sum(g.values())
    return {
        "chunks": n,
        "from_cache": sum(r.cached for r in results),
        "errors": sum(r.status == "error" for r in results),
        "valid_json_rate": round(sum(r.status == "ok" for r in results) / n, 3) if n else 0.0,
        "repaired": sum(r.status == "repaired" for r in results),
        "failed": sum(r.status == "failed" for r in results),
        "truncated": sum(r.truncated for r in results),
        "items_kept": sum(len(v) for r in results for v in r.extraction.values()),
        "items_dropped": sum(len(r.dropped) for r in results),
        "dropped_by_reason": dict(sorted(reasons.items())),
        "grounding": g,
        "grounded_rate": round((g["exact"] + g["fuzzy"]) / graded, 3) if graded else 0.0,
        "sec_per_chunk_live": round(sum(r.wall_s for r in live) / len(live), 1) if live else None,
    }


def select_chunks(path: Path, story: str | None, limit: int) -> list[dict]:
    recs = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rec = json.loads(line)
                if story is None or rec.get("story") == story:
                    recs.append(rec)
    return recs[:limit] if limit else recs


def main(argv: Sequence[str] | None = None, client: LLMClient | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m detective_board.extract.run")
    ap.add_argument("--model", required=True)
    ap.add_argument("--chunks", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--story")
    ap.add_argument("--cache", type=Path, default=Path("data/extract_cache.sqlite"))
    ap.add_argument("--prompt", type=Path, default=DEFAULT_PROMPT)
    ap.add_argument("--host", default="http://localhost:11434")
    ap.add_argument("--num-ctx", type=int, default=4096)
    ap.add_argument("--num-predict", type=int, default=1536)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--fuzzy-threshold", type=float, default=0.85)
    ap.add_argument("--keep-ungrounded", action="store_true")
    ap.add_argument("--graph-db", type=Path, help="also ingest usable results into this graph DB")
    a = ap.parse_args(argv)

    cfg = ExtractConfig(
        a.model, a.num_ctx, a.num_predict, a.seed,
        fuzzy_threshold=a.fuzzy_threshold, keep_ungrounded=a.keep_ungrounded,
    )  # fmt: skip
    cache = ExtractCache(a.cache)
    ex = Extractor(client or OllamaClient(a.host), cfg, cache, load_prompt(a.prompt))
    recs = select_chunks(a.chunks, a.story, a.limit)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    results: list[ChunkResult] = []
    t0 = time.perf_counter()
    with open(a.out, "w", encoding="utf-8") as out:
        for i, rec in enumerate(recs, 1):
            r = ex.extract_chunk(rec["chunk_id"], rec.get("story", ""), rec["text"])
            results.append(r)
            out.write(json.dumps(r.to_json(), ensure_ascii=False) + "\n")
            out.flush()
            tag = "cache" if r.cached else f"{r.wall_s:.0f}s"
            print(f"[{i}/{len(recs)}] {r.chunk_id} {r.status} {tag}"
                  f"{' TRUNC' if r.truncated else ''}", file=sys.stderr)  # fmt: skip
    cache.close()
    report = build_report(results)
    report.update(
        model=a.model, prompt_version=ex.prompt.version, total_s=round(time.perf_counter() - t0, 1)
    )
    if a.graph_db:
        from detective_board.extract.ingest import ingest_results
        from detective_board.graph import GraphStore

        store = GraphStore(str(a.graph_db))
        reps = ingest_results(store, results, {r["chunk_id"]: r for r in recs})
        report["graph_ingested"] = sum(x.status != "unchanged" for x in reps)
        store.close()
    print("== report", file=sys.stderr)
    for k, v in report.items():
        print(f"  {k}: {v}", file=sys.stderr)
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
