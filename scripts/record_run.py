"""Record one real run of the API as a replay file for the UI backup recording (stdlib only).

Usage: scripts/record_run.py --question "..." --out web/replay/real-g001.json [--port 8000]
The API (python -m detective_board.api, real mode) must be running. The file is {meta, events}:
the SSE trace events exactly as streamed, each with its original `ts`, so
`?replay=replay/real-g001.json` plays them at the original timing. The meta says what the
recording is (a RECORDING of a real run on this machine) so the UI can label it.
"""Record one real run of the API as a replay file for the UI backup recording (stdlib only).

Usage: scripts/record_run.py --question "..." --out web/replay/real-g001.json [--port 8000] [--note "..."]
The API (python -m detective_board.api, real mode) must be running. The file is {meta, events}: the SSE trace events
exactly as streamed, each with its original `ts`, so `?replay=replay/real-g001.json` plays them at the original
timing. The meta says what the recording is (a RECORDING of a real run on this machine) so the UI can label it.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path


def record(port: int, question: str, timeout: float = 1800.0) -> tuple[list[dict], float]:
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/ask",
        json.dumps({"question": question}).encode(),
        {"Content-Type": "application/json", "Origin": f"http://127.0.0.1:{port}"},
    )
    events: list[dict] = []
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        for raw in resp:
            line = raw.decode().rstrip("\n")
            if line.startswith("data:"):
                events.append(json.loads(line[5:]))
    return events, time.time() - t0


def main() -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("--question", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--note", default="")
    a = ap.parse_args()
    health = json.load(urllib.request.urlopen(f"http://127.0.0.1:{a.port}/api/health", timeout=10))
    if health.get("fake"):
        print("refusing to record: the API runs in --fake mode", file=sys.stderr)
        return 2
    events, seconds = record(a.port, a.question)
    if not events or events[-1].get("type") not in ("final", "run_error"):
        print("the run did not end with final/run_error; not saving", file=sys.stderr)
        return 3
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
    except Exception:
        commit = None
    meta = {
        "label": "RECORDING",
        "kind": "real run recorded on the target laptop",
        "question": a.question,
        "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "seconds": round(seconds, 1),
        "commit": commit,
        "mcp": health.get("mcp"),
        "graph": (health.get("graph") or {}).get("counts"),
        "versions": health.get("versions"),
        "note": a.note,
    }
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps({"meta": meta, "events": events}, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(f"saved {out} ({len(events)} events, {seconds:.1f} s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
