"""Fail early, with a clear message, when Ollama is unreachable or a model is missing.

Usage: python scripts/preflight.py [--config FILE]   (stdlib only; exit 0 ok, 2 not ready)
Checks the models of the effective config (defaults < TOML < env DETECTIVE_BOARD_*): the answer
model (`llm_model`) and the embedding model (`embed_model`), via Ollama's `GET /api/tags`."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tomllib
import urllib.request

PREFIX = "DETECTIVE_BOARD_"
DEFAULTS = {
    "ollama_host": "http://localhost:11434",
    "llm_model": "qwen3:4b-instruct",
    "embed_model": "bge-m3",
}


def effective(path: str | None, env: dict[str, str]) -> dict[str, str]:
    vals = dict(DEFAULTS)
    file = path or env.get(PREFIX + "CONFIG")
    if file:
        with open(file, "rb") as f:
            vals.update({k: str(v) for k, v in tomllib.load(f).items() if k in DEFAULTS})
    for k in DEFAULTS:
        if PREFIX + k.upper() in env:
            vals[k] = env[PREFIX + k.upper()]
    return vals


def installed(host: str, timeout: float = 3.0) -> list[str] | None:
    try:
        with urllib.request.urlopen(host.rstrip("/") + "/api/tags", timeout=timeout) as r:  # noqa: S310
            return [m["name"] for m in json.load(r).get("models", [])]
    except Exception:  # noqa: BLE001
        return None


def has_model(names: list[str], want: str) -> bool:
    got = set(names) | {n.removesuffix(":latest") for n in names}
    return want in got or f"{want}:latest" in got


def check(vals: dict[str, str], names: list[str] | None) -> list[str]:
    """Problems as printable lines; empty when ready."""
    if names is None:
        return [
            f"Ollama is not reachable at {vals['ollama_host']}. Start it (`ollama serve`) "
            "or set DETECTIVE_BOARD_OLLAMA_HOST. `just run --fake` needs no Ollama."
        ]
    return [
        f"model missing: {vals[k]} (run `ollama pull {vals[k]}`)"
        for k in ("llm_model", "embed_model")
        if not has_model(names, vals[k])
    ]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", help="TOML file (or $DETECTIVE_BOARD_CONFIG)")
    ns = ap.parse_args(argv)
    vals = effective(ns.config, dict(os.environ))
    problems = check(vals, installed(vals["ollama_host"]))
    for line in problems:
        print(f"preflight: {line}", file=sys.stderr)
    return 2 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
