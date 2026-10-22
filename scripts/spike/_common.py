"""Shared helpers for the Phase 0 spike benchmarks (stdlib only)."""
from __future__ import annotations

import datetime as dt
import json
import os
import statistics
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RESULTS_DIR = ROOT / "docs" / "spike" / "results"
CHUNKS = ROOT / "data" / "chunks.jsonl"


def load_jsonl(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def mem_available_mib() -> float:
    with open("/proc/meminfo") as f:
        for line in f:
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) / 1024
    return float("nan")


def stats(xs: list[float]) -> dict:
    xs = [x for x in xs if x is not None]
    if not xs:
        return {"n": 0, "mean": None, "stdev": None, "min": None, "max": None}
    return {
        "n": len(xs),
        "mean": statistics.fmean(xs),
        "stdev": statistics.stdev(xs) if len(xs) > 1 else 0.0,
        "min": min(xs),
        "max": max(xs),
    }


def fmt(s: dict, nd: int = 2) -> str:
    if not s or s["mean"] is None:
        return "n/a"
    return f"{s['mean']:.{nd}f} ± {s['stdev']:.{nd}f}"


def rate(count, dur_ns):
    if not count or not dur_ns:
        return None
    return count / dur_ns * 1e9


class Http:
    def __init__(self, host: str, timeout: float = 900.0):
        self.base = host.rstrip("/")
        self.timeout = timeout

    def _req(self, path, payload=None):
        data = None if payload is None else json.dumps(payload).encode()
        return urllib.request.Request(
            self.base + path,
            data=data,
            headers={"Content-Type": "application/json"},
            method="GET" if payload is None else "POST",
        )

    def get(self, path):
        with urllib.request.urlopen(self._req(path), timeout=self.timeout) as r:
            return json.load(r)

    def post(self, path, payload):
        try:
            with urllib.request.urlopen(self._req(path, payload), timeout=self.timeout) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"HTTP {e.code} {path}: {e.read().decode(errors='replace')[:300]}") from e

    def stream(self, path, payload):
        """Yield (t_seconds_since_send, parsed_json_line)."""
        t0 = time.perf_counter()
        try:
            r = urllib.request.urlopen(self._req(path, payload), timeout=self.timeout)
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"HTTP {e.code} {path}: {e.read().decode(errors='replace')[:300]}") from e
        with r:
            for line in r:
                line = line.strip()
                if line:
                    yield time.perf_counter() - t0, json.loads(line)

    def available(self, model: str) -> bool:
        names = {m["name"] for m in self.get("/api/tags")["models"]}
        return model in names or (":" not in model and f"{model}:latest" in names)


def _ollama_pids() -> dict[int, str]:
    """pid -> role ('serve'|'runner'|'other') for processes whose argv[0] basename is ollama."""
    me = os.getpid()
    out = {}
    for d in os.listdir("/proc"):
        if not d.isdigit() or int(d) == me:
            continue
        try:
            with open(f"/proc/{d}/cmdline", "rb") as f:
                argv = f.read().split(b"\0")
        except OSError:
            continue
        if not argv:
            continue
        base = os.path.basename(argv[0].decode(errors="replace"))
        rest = [a.decode(errors="replace") for a in argv[1:]]
        if base == "llama-server":  # Ollama 0.35 runs the model in this child process
            out[int(d)] = "runner"
        elif base == "ollama":
            out[int(d)] = "runner" if "runner" in rest else ("serve" if "serve" in rest else "other")
    return out


def _rss_kib(pid: int) -> tuple[int, int]:
    """(VmRSS, RssAnon) in KiB from /proc/<pid>/status."""
    tot = anon = 0
    with open(f"/proc/{pid}/status") as f:
        for line in f:
            if line.startswith("VmRSS:"):
                tot = int(line.split()[1])
            elif line.startswith("RssAnon:"):
                anon = int(line.split()[1])
    return tot, anon


class RssSampler:
    """Samples summed RSS of ollama processes every `interval` s (reads /proc, no psutil).

    VmRSS includes file-backed (mmap'd model weights) pages; RssAnon is anonymous memory only.
    """

    def __init__(self, interval: float = 0.5):
        self.interval = interval
        self._stop = threading.Event()
        self._t = threading.Thread(target=self._run, daemon=True)
        self.samples = 0
        self.peak_total = 0
        self.peak_anon = 0
        self.peak_runner = 0
        self.peak_serve = 0

    def _sample(self):
        tot = anon = run = srv = 0
        for pid, role in _ollama_pids().items():
            try:
                t, a = _rss_kib(pid)
            except OSError:
                continue
            tot += t
            anon += a
            if role == "runner":
                run += t
            elif role == "serve":
                srv += t
        self.samples += 1
        self.peak_total = max(self.peak_total, tot)
        self.peak_anon = max(self.peak_anon, anon)
        self.peak_runner = max(self.peak_runner, run)
        self.peak_serve = max(self.peak_serve, srv)

    def _run(self):
        while not self._stop.is_set():
            self._sample()
            self._stop.wait(self.interval)

    def __enter__(self):
        self._t.start()
        return self

    def __exit__(self, *a):
        self._stop.set()
        self._t.join()
        self._sample()

    def result(self) -> dict:
        mib = lambda k: round(k / 1024, 1)  # noqa: E731
        return {
            "samples": self.samples,
            "interval_s": self.interval,
            "peak_rss_total_mib": mib(self.peak_total),
            "peak_rss_anon_mib": mib(self.peak_anon),
            "peak_rss_runner_mib": mib(self.peak_runner),
            "peak_rss_serve_mib": mib(self.peak_serve),
        }


def write_results(prefix: str, data: dict, md: str) -> tuple[Path, Path]:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    j = RESULTS_DIR / f"{prefix}-{stamp}.json"
    m = RESULTS_DIR / f"{prefix}-{stamp}.md"
    j.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    m.write_text(md, encoding="utf-8")
    return j, m
