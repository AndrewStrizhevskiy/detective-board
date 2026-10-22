#!/usr/bin/env python3
"""Phase 0 spike: run graph extraction on the hand-labelled chunks with one model.

Writes predictions as JSONL ({chunk_id, output: <raw string>, ...timing}) in the format
scripts/spike/score_extraction.py reads. Uses Ollama /api/generate with `format` = JSON schema
(constrained decoding), temperature 0, fixed seed. One model per invocation.
Run: uv run --with pydantic python scripts/spike/run_extraction.py MODEL [--limit N]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import ROOT, Http, RssSampler, mem_available_mib  # noqa: E402
from detective_board.extract.schema import ollama_format_schema  # noqa: E402

GOLD = ROOT / "eval" / "extraction_gold"
OUT = ROOT / "docs" / "spike" / "results"

PROMPT = """You extract structured facts from a passage of a Sherlock Holmes story.
Return JSON that follows the given schema. Rules:
- Use only what the passage says. Do not add facts from memory.
- Every item needs a `quote`: an exact, contiguous span copied character for character from the passage.
- entities: people, places and objects that matter; put other surface forms in `aliases`.
- events: things that happened, with the time exactly as written if the passage gives one.
- claims: statements made by a speaker (testimony, denials, accusations, alibis).
- relations: subject, short verb phrase, object (e.g. kinship, employment, ownership, location).
- Use plain names as written; for an unnamed person use a short description such as "the deceased".
- Be selective: at most 8 entities, 5 events, 5 claims, 6 relations.

Passage:
{chunk}
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("model")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--num-ctx", type=int, default=4096)
    ap.add_argument("--num-predict", type=int, default=1536)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--host", default="http://localhost:11434")
    a = ap.parse_args()
    files = sorted(GOLD.glob("*.json"))
    files = [f for f in files if f.name != "README.json"]
    if a.limit:
        files = files[: a.limit]
    http = Http(a.host)
    assert http.available(a.model), f"{a.model} not installed"
    for m in http.get("/api/ps").get("models", []):
        http.post("/api/generate", {"model": m["name"], "prompt": "", "keep_alive": 0, "stream": False})
    time.sleep(3)
    caps = http.post("/api/show", {"model": a.model}).get("capabilities", [])
    schema = ollama_format_schema()
    stamp = time.strftime("%Y%m%d-%H%M%S")
    path = OUT / f"extract-{a.model.replace(':', '_')}-{stamp}.jsonl"
    OUT.mkdir(parents=True, exist_ok=True)
    print(f"== {a.model} -> {path.name} ({len(files)} chunks)", file=sys.stderr)
    with RssSampler(0.5) as rss, open(path, "w", encoding="utf-8") as out:
        for f in files:
            g = json.loads(f.read_text(encoding="utf-8"))
            payload = {"model": a.model, "prompt": PROMPT.format(chunk=g["text"]), "stream": False,
                       "format": schema, "keep_alive": "10m",
                       "options": {"temperature": 0, "seed": a.seed, "num_ctx": a.num_ctx,
                                   "num_predict": a.num_predict}}
            if "thinking" in caps:
                payload["think"] = False
            t0 = time.perf_counter()
            try:
                r = http.post("/api/generate", payload)
            except Exception as e:  # keep going: a failed chunk counts as invalid output
                r = {"response": "", "error": str(e)[:200]}
            dt = time.perf_counter() - t0
            rec = {"chunk_id": g["chunk_id"], "output": r.get("response", ""), "wall_s": round(dt, 1),
                   "gen_tokens": r.get("eval_count"), "prompt_tokens": r.get("prompt_eval_count"),
                   "done_reason": r.get("done_reason"), "error": r.get("error"), "model": a.model,
                   "num_predict": a.num_predict, "mem_available_mib": round(mem_available_mib())}
            out.write(json.dumps(rec, ensure_ascii=False) + "\n")
            out.flush()
            print(f"  {g['chunk_id']}: {dt:.0f}s gen={rec['gen_tokens']} {rec['done_reason']}", file=sys.stderr)
    print(json.dumps({"model": a.model, "rss": rss.result(), "file": path.name}))


if __name__ == "__main__":
    main()
