"""Steady-state RAM per model: unload everything, load one, run a 300-word prompt, read runner RSS."""
import json, sys, time, urllib.request

sys.path.insert(0, __import__("os").path.dirname(__file__))
from _common import _ollama_pids, _rss_kib  # noqa: E402

H = "http://localhost:11434"


def call(path, body=None):
    req = urllib.request.Request(H + path, json.dumps(body).encode() if body else None,
                                 {"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=600))


def unload_all():
    for m in call("/api/ps").get("models", []):
        call("/api/generate", {"model": m["name"], "keep_alive": 0})
    for _ in range(60):
        if not call("/api/ps").get("models") and not [p for p, r in _ollama_pids().items() if r == "runner"]:
            return
        time.sleep(1)
    raise SystemExit("could not unload models")


chunk = next(json.loads(l) for l in open("data/chunks.jsonl") if "norwood-builder-0013" in l)["text"]
rows = []
for model in sys.argv[1:]:
    unload_all()
    call("/api/generate", {"model": model, "prompt": "Summarize:\n" + chunk, "stream": False,
                           **({"think": False} if "qwen3" in model else {}),
                           "options": {"num_ctx": 4096, "num_predict": 20, "temperature": 0, "seed": 42}})
    run = [p for p, r in _ollama_pids().items() if r == "runner"]
    tot = sum(_rss_kib(p)[0] for p in run) // 1024
    anon = sum(_rss_kib(p)[1] for p in run) // 1024
    rows.append({"model": model, "runners": len(run), "rss_mib": tot, "anon_mib": anon})
    print(rows[-1], flush=True)
unload_all()
json.dump(rows, open("docs/spike/results/rss-steady.json", "w"), indent=1)
