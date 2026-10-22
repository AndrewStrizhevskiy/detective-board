#!/usr/bin/env python3
"""Phase 0 spike: LLM latency/throughput/RAM benchmark against a local Ollama server.

Stdlib only. Fields verified against the Ollama API docs (docs/api.md, ollama/ollama):
  POST /api/generate: model, prompt, stream, think, options{seed,temperature,num_ctx,num_predict}, keep_alive
  final stream object: total_duration, load_duration, prompt_eval_count, prompt_eval_duration,
                       eval_count, eval_duration (all durations in nanoseconds), done_reason
  unload: empty prompt + keep_alive=0 (done_reason "unload")
  thinking: `think` (bool|level) on /api/generate; thinking text arrives in the `thinking` field.
  GET /api/show -> `capabilities` (observed on Ollama 0.35.0 to contain "thinking" for qwen3 models;
  the docs page only shows ["completion","vision"] as examples).
Thinking policy (--think auto|off|none):
  auto (default): send think=false iff /api/show capabilities contains "thinking". `/no_think` is NOT
  used (not mentioned in the docs). The mode actually used is reported per model; any `thinking`
  output or "<think>" in the response is counted as a leak and flagged.

Run (see --help). Do not run while RAM-sensitive work is ongoing.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import uuid

sys.path.insert(0, __import__("os").path.dirname(__file__))
from _common import (  # noqa: E402
    CHUNKS, Http, RssSampler, fmt, load_jsonl, mem_available_mib, rate, stats, write_results,
)

QA_PROMPT = (
    "Answer in two sentences. Who is Dr. John Watson in relation to Sherlock Holmes, "
    "and where do the two men live?"
)
SUM_TEMPLATE = (
    "Read the passage from a Sherlock Holmes story and summarise it in exactly three sentences.\n\n"
    "Passage:\n{chunk}\n\nSummary:"
)


def pick_chunk(chunks: list[dict], target_words: int = 300) -> dict:
    """Deterministic: chunk whose word count is closest to target (ties -> first in file)."""
    return min(chunks, key=lambda c: abs(len(c["text"].split()) - target_words))


def build_prompts(chunks: list[dict], num_predict_sum: int, num_predict_qa: int) -> list[dict]:
    c = pick_chunk(chunks)
    return [
        {"name": "summarize_chunk", "body": SUM_TEMPLATE.format(chunk=c["text"]),
         "num_predict": num_predict_sum, "chunk_id": c["chunk_id"], "chunk_words": len(c["text"].split())},
        {"name": "short_qa", "body": QA_PROMPT, "num_predict": num_predict_qa},
    ]


def think_mode(http: Http, model: str, policy: str) -> tuple[bool | None, str]:
    """Returns (think value to send or None, human description)."""
    if policy == "none":
        return None, "not sent (--think none)"
    if policy == "off":
        return False, "think=false (forced by --think off)"
    caps = http.post("/api/show", {"model": model}).get("capabilities", [])
    if "thinking" in caps:
        return False, "think=false (capabilities include 'thinking')"
    return None, "not sent (no 'thinking' capability)"


def one_run(http, model, prompt, think, args, nonce):
    # Nonce at the very start defeats prompt-prefix KV reuse, so prompt_eval is a real measurement.
    payload = {
        "model": model,
        "prompt": f"[req {nonce}]\n{prompt['body']}",
        "stream": True,
        "keep_alive": args.keep_alive,
        "options": {"temperature": 0, "seed": args.seed, "num_ctx": args.num_ctx,
                    "num_predict": prompt["num_predict"]},
    }
    if think is not None:
        payload["think"] = think
    ttft = None
    text = []
    think_chars = 0
    final = None
    t_end = 0.0
    for t, obj in http.stream("/api/generate", payload):
        r, th = obj.get("response", ""), obj.get("thinking", "")
        if (r or th) and ttft is None:
            ttft = t
        text.append(r)
        think_chars += len(th)
        if obj.get("done"):
            final, t_end = obj, t
    out = "".join(text)
    return {
        "ttft_s": ttft,
        "wall_s": t_end,
        "load_s": (final.get("load_duration") or 0) / 1e9,
        "prompt_tokens": final.get("prompt_eval_count"),
        "prompt_cached_tokens": final.get("prompt_eval_cached_count"),
        "prompt_tps": rate(final.get("prompt_eval_count"), final.get("prompt_eval_duration")),
        "gen_tokens": final.get("eval_count"),
        "gen_tps": rate(final.get("eval_count"), final.get("eval_duration")),
        "done_reason": final.get("done_reason"),
        "thinking_chars": think_chars,
        "think_tag_in_response": "<think>" in out,
        "output_preview": out[:160],
    }


def bench_model(http, model, prompts, args):
    res = {"model": model}
    if not http.available(model):
        res["error"] = "model not installed (not in /api/tags)"
        return res
    think, desc = think_mode(http, model, args.think)
    res["think_mode"] = desc
    if not args.no_unload:
        for loaded in http.get("/api/ps").get("models", []):  # no other model may stay resident
            http.post("/api/generate", {"model": loaded["name"], "prompt": "", "keep_alive": 0, "stream": False})
        time.sleep(3.0)
    res["mem_available_before_mib"] = round(mem_available_mib(), 1)
    per_prompt = {}
    with RssSampler(args.sample_interval) as rss:
        for p in prompts:
            runs = []
            for i in range(args.warmup + args.runs):
                r = one_run(http, model, p, think, args, uuid.uuid4().hex[:8])
                r["warmup"] = i < args.warmup
                runs.append(r)
                print(f"  {model} {p['name']} {'warmup' if r['warmup'] else 'run'} {i}: "
                      f"ttft={r['ttft_s']:.2f}s gen={r['gen_tps'] or 0:.2f} tok/s "
                      f"load={r['load_s']:.2f}s", file=sys.stderr)
            meas = [r for r in runs if not r["warmup"]]
            per_prompt[p["name"]] = {
                "runs": runs,
                "summary": {
                    "ttft_s": stats([r["ttft_s"] for r in meas]),
                    "gen_tps": stats([r["gen_tps"] for r in meas]),
                    "prompt_tps": stats([r["prompt_tps"] for r in meas]),
                    "gen_tokens": stats([r["gen_tokens"] for r in meas]),
                    "prompt_tokens": stats([r["prompt_tokens"] for r in meas]),
                    "wall_s": stats([r["wall_s"] for r in meas]),
                    "thinking_leaks": sum(1 for r in meas if r["thinking_chars"] or r["think_tag_in_response"]),
                },
            }
    res["rss"] = rss.result()
    res["mem_available_after_mib"] = round(mem_available_mib(), 1)
    # cold load = load_duration of the very first (warmup) call of the first prompt, if unloaded before
    first = per_prompt[prompts[0]["name"]]["runs"][0]
    res["cold_load_s"] = first["load_s"] if not args.no_unload else None
    res["prompts"] = per_prompt
    return res


def to_markdown(data: dict) -> str:
    a = data["args"]
    L = [f"# LLM benchmark ({data['timestamp']})", "",
         f"Ollama {data['ollama_version']}; temperature 0, seed {a['seed']}, num_ctx {a['num_ctx']}, "
         f"stream=true; {a['warmup']} warmup + {a['runs']} measured runs per prompt (mean ± stdev). "
         f"RSS sampled every {a['sample_interval']}s from /proc over all `ollama` processes "
         "(VmRSS incl. mmap'd weights; anon = RssAnon only).", ""]
    for p in data["prompts"]:
        L.append(f"- prompt `{p['name']}`: num_predict={p['num_predict']}"
                 + (f", chunk `{p['chunk_id']}` ({p['chunk_words']} words)" if "chunk_id" in p else ""))
    L.append("")
    for pname in [p["name"] for p in data["prompts"]]:
        L += [f"## {pname}", "",
              "| model | think | TTFT s | gen tok/s | prompt tok/s | gen toks | prompt toks | cold load s | peak RSS MiB (total / anon) | MemAvail before→after MiB | think leaks |",
              "|---|---|---|---|---|---|---|---|---|---|---|"]
        for m in data["models"]:
            if "error" in m:
                L.append(f"| {m['model']} | {m['error']} |" + " |" * 9)
                continue
            s = m["prompts"][pname]["summary"]
            cl = "n/a" if m["cold_load_s"] is None else f"{m['cold_load_s']:.2f}"
            L.append(
                f"| {m['model']} | {m['think_mode']} | {fmt(s['ttft_s'])} | {fmt(s['gen_tps'])} | "
                f"{fmt(s['prompt_tps'], 1)} | {fmt(s['gen_tokens'], 0)} | {fmt(s['prompt_tokens'], 0)} | {cl} | "
                f"{m['rss']['peak_rss_total_mib']} / {m['rss']['peak_rss_anon_mib']} | "
                f"{m['mem_available_before_mib']}→{m['mem_available_after_mib']} | {s['thinking_leaks']} |")
        L.append("")
    return "\n".join(L)


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("models", nargs="+", help="Ollama model tags, e.g. qwen3:4b-instruct qwen2.5:7b")
    ap.add_argument("--host", default="http://localhost:11434")
    ap.add_argument("--runs", type=int, default=3, help="measured runs per prompt (default 3)")
    ap.add_argument("--warmup", type=int, default=1, help="warmup runs per prompt (default 1)")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--num-ctx", type=int, default=4096)
    ap.add_argument("--num-predict-summary", type=int, default=200)
    ap.add_argument("--num-predict-qa", type=int, default=100)
    ap.add_argument("--keep-alive", default="10m")
    ap.add_argument("--sample-interval", type=float, default=0.5)
    ap.add_argument("--think", choices=["auto", "off", "none"], default="auto",
                    help="auto: think=false only if /api/show lists 'thinking' capability")
    ap.add_argument("--no-unload", action="store_true", help="skip unloading before each model (no cold-load number)")
    ap.add_argument("--dry-run", action="store_true", help="validate args and prompts; no Ollama calls, no files written")
    a = ap.parse_args(argv)
    if a.runs < 1 or a.warmup < 0 or a.num_ctx < 512 or a.sample_interval <= 0:
        ap.error("need runs>=1, warmup>=0, num-ctx>=512, sample-interval>0")
    if len(set(a.models)) != len(a.models):
        ap.error("duplicate models")
    return a


def host_env() -> dict:
    """Conditions that affect CPU speed; recorded with every result."""
    import glob, subprocess
    def rd(path):
        try:
            return open(path).read().strip()
        except OSError:
            return None
    mem = {l.split(":")[0]: int(l.split()[1]) // 1024 for l in open("/proc/meminfo")
           if l.split(":")[0] in ("MemAvailable", "SwapFree", "SwapTotal")}
    try:
        prof = subprocess.run(["powerprofilesctl", "get"], capture_output=True, text=True, timeout=3).stdout.strip()
    except Exception:
        prof = None
    temps = [int(rd(f) or 0) // 1000 for f in glob.glob("/sys/class/thermal/thermal_zone*/temp")]
    return {"governor": rd("/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor"),
            "power_profile": prof, "loadavg": rd("/proc/loadavg"),
            "mem_mib": mem, "max_temp_c": max(temps) if temps else None,
            "ac_online": [rd(f) for f in glob.glob("/sys/class/power_supply/A*/online")]}


def main(argv=None):
    a = parse_args(argv)
    chunks = load_jsonl(CHUNKS)
    prompts = build_prompts(chunks, a.num_predict_summary, a.num_predict_qa)
    est = int(len(prompts[0]["body"].split()) * 1.4)
    if est + a.num_predict_summary > a.num_ctx:
        sys.exit(f"num_ctx {a.num_ctx} too small for summary prompt (~{est} tok + {a.num_predict_summary})")
    if a.dry_run:
        print(f"[dry-run] models={a.models} runs={a.runs} warmup={a.warmup} seed={a.seed} num_ctx={a.num_ctx} think={a.think}")
        for p in prompts:
            print(f"[dry-run] prompt {p['name']}: {len(p['body'].split())} words, num_predict={p['num_predict']}"
                  + (f", chunk={p['chunk_id']} ({p['chunk_words']} words)" if "chunk_id" in p else ""))
        print(f"[dry-run] est. calls: {len(a.models) * len(prompts) * (a.runs + a.warmup)}; no network used. OK")
        return 0
    http = Http(a.host)
    version = http.get("/api/version")["version"]
    data = {"timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"), "ollama_version": version,
            "env_start": host_env(), "args": vars(a), "prompts": [{k: v for k, v in p.items() if k != "body"} for p in prompts], "models": []}
    for m in a.models:
        print(f"== {m}", file=sys.stderr)
        data["models"].append(bench_model(http, m, prompts, a))
    data["env_end"] = host_env()
    j, md = write_results("llm", data, to_markdown(data))
    print(f"wrote {j}\nwrote {md}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
