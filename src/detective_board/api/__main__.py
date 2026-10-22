"""CLI: python -m detective_board.api --host 127.0.0.1 --port 8000 [--fake] [--config FILE]"""

from __future__ import annotations

import argparse
import sys

from detective_board.api.config import LOOPBACK, load_config


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="detective_board.api", description=__doc__)
    ap.add_argument("--host", help="bind address (default 127.0.0.1)")
    ap.add_argument("--port", type=int, help="port (default 8000)")
    ap.add_argument("--config", help="TOML file (or $DETECTIVE_BOARD_CONFIG)")
    ap.add_argument(
        "--fake", action="store_true", help="FakeLLM + tiny fixture; no Ollama, no data"
    )
    ns = ap.parse_args(argv)
    cfg = load_config(ns.config, host=ns.host, port=ns.port, fake=True if ns.fake else None)
    if cfg.host not in LOOPBACK:
        print(f"warning: binding to {cfg.host}, the API is not authenticated", file=sys.stderr)

    import uvicorn  # noqa: PLC0415 - only the server entry needs it

    from detective_board.api.app import build_app  # noqa: PLC0415

    uvicorn.run(build_app(cfg), host=cfg.host, port=cfg.port, log_level="info")


if __name__ == "__main__":
    main()
