"""API configuration: defaults < TOML file < environment (DETECTIVE_BOARD_*)."""

from __future__ import annotations

import dataclasses
import os
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from detective_board.agent import AgentConfig

ENV_PREFIX = "DETECTIVE_BOARD_"
ENV_CONFIG = ENV_PREFIX + "CONFIG"
REPO_ROOT = Path(__file__).resolve().parents[3]
LOOPBACK = ("127.0.0.1", "localhost", "::1")


@dataclass(frozen=True)
class ApiConfig:
    host: str = "127.0.0.1"
    port: int = 8000
    fake: bool = False  # FakeLLM + tiny in-memory fixture; never touches Ollama or data files
    # data (relative paths resolve against the repo root)
    index_path: str = "data/index/db.sqlite"  # retrieval.Store
    graph_path: str = "data/graph/graph.sqlite"  # graph.GraphStore
    facts_path: str | None = None  # FactBase JSON for the timeline-alibi MCP server
    facts_allow: str | None = None  # allow-listed dirs for it (os.pathsep separated)
    web_dir: str = "web"
    # models; the embedding identity must match the one the index was built with
    ollama_host: str = "http://localhost:11434"
    llm_model: str = "qwen3:8b"
    embed_model: str = "bge-m3"  # same as index.build.CONFIG
    embed_dim: int = 1024
    embed_doc_prefix: str = ""
    embed_query_prefix: str = ""
    num_ctx: int | None = None
    llm_timeout_s: float = 300.0
    # limits
    max_body_bytes: int = 16 * 1024
    max_question_chars: int = 1000
    max_history_turns: int = 6
    max_turn_chars: int = 2000
    max_quote_chars: int = 1000
    max_graph_nodes: int = 200
    max_hops: int = 3
    keepalive_s: float = 15.0
    run_timeout_s: float = 600.0
    agent: dict[str, Any] = field(default_factory=dict)  # AgentConfig overrides

    def agent_config(self) -> AgentConfig:
        return AgentConfig(**self.agent)

    def resolve(self, p: str) -> Path:
        path = Path(p)
        return path if path.is_absolute() else REPO_ROOT / path

    def data_status(self) -> list[str]:
        """Real mode only: one line per data file, with a fix when it is missing."""
        lines = []
        for label, rel, missing in (
            ("index", self.index_path, index_missing_message(self)),
            ("graph", self.graph_path, graph_missing_message(self)),
        ):
            lines.append(
                f"{label}: present ({rel})" if self.resolve(rel).exists() else f"{label}: {missing}"
            )
        return lines

    def allowed_hosts(self) -> list[str]:
        """Host-header allow-list (DNS-rebinding guard); other binds are the operator's choice."""
        if self.host in LOOPBACK:
            return ["localhost", "127.0.0.1", "[::1]"]
        return ["*"]


def index_missing_message(cfg: ApiConfig) -> str:
    return (
        f"index not found: {cfg.index_path}. Build it with `just index` "
        "(python -m detective_board.index.build), or point DETECTIVE_BOARD_INDEX_PATH at it."
    )


def graph_missing_message(cfg: ApiConfig) -> str:
    return (
        f"graph not found: {cfg.graph_path}; the graph is empty. Build it with `just graph` "
        "(extraction + `just normalise`), or point DETECTIVE_BOARD_GRAPH_PATH at it."
    )


_FIELDS = {f.name: f for f in dataclasses.fields(ApiConfig)}


def _coerce(name: str, value: Any) -> Any:
    ftype = str(_FIELDS[name].type)
    if name == "agent":
        if not isinstance(value, Mapping):
            raise ValueError("'agent' must be a table")
        valid = {f.name for f in dataclasses.fields(AgentConfig)}
        bad = sorted(set(value) - valid)
        if bad:
            raise ValueError(f"unknown agent option(s): {', '.join(bad)}")
        base = AgentConfig()
        out: dict[str, Any] = {}
        for k, v in value.items():
            t = type(getattr(base, k))
            truthy = str(v).strip().lower() in ("1", "true", "yes", "on")
            out[k] = truthy if t is bool and isinstance(v, str) else t(v)
        return out
    if ftype.startswith("bool"):
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on")
        return bool(value)
    if ftype.startswith("int"):
        return None if value in (None, "") else int(value)
    if ftype.startswith("float"):
        return float(value)
    if value in (None, "") and "None" in ftype:
        return None
    return str(value)


def load_config(
    path: str | Path | None = None,
    env: Mapping[str, str] | None = None,
    **overrides: Any,
) -> ApiConfig:
    """Read the TOML file (explicit `path`, else $DETECTIVE_BOARD_CONFIG, else none), then env,
    then keyword overrides. Unknown keys are an error (typos must not pass silently)."""
    env = os.environ if env is None else env
    values: dict[str, Any] = {}
    file = path or env.get(ENV_CONFIG)
    if file:
        with open(file, "rb") as f:
            values.update(tomllib.load(f))
    for name in _FIELDS:
        key = ENV_PREFIX + name.upper()
        if name != "agent" and key in env:
            values[name] = env[key]
    for k, v in env.items():  # DETECTIVE_BOARD_AGENT_TOP_K=7
        if k.startswith(ENV_PREFIX + "AGENT_"):
            values.setdefault("agent", {})[k[len(ENV_PREFIX + "AGENT_") :].lower()] = v
    values.update({k: v for k, v in overrides.items() if v is not None})
    unknown = sorted(set(values) - set(_FIELDS))
    if unknown:
        raise ValueError(f"unknown config key(s): {', '.join(unknown)}")
    cfg = ApiConfig(**{k: _coerce(k, v) for k, v in values.items()})
    cfg.agent_config()  # validates the thresholds' names and types early
    return cfg
