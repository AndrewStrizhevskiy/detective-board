"""Wiring: construct Store / HybridRetriever / GraphStore / Agent from an `ApiConfig`.

SQLite connections are bound to the thread that opened them, so `build_services` is called once
inside each worker thread (see `runtime.py`); never share a `Services` between threads."""

from __future__ import annotations

import dataclasses
import sys
from dataclasses import dataclass
from typing import Any

from detective_board.agent import LLM, Agent, HybridRetriever, OllamaLLM, ToolClient
from detective_board.agent.rules_client import InProcessRulesClient
from detective_board.api import fixture
from detective_board.api.config import ApiConfig, graph_missing_message, index_missing_message
from detective_board.api.tool_client import SyncToolClient
from detective_board.graph import GraphStore
from detective_board.retrieval import EmbeddingConfig, OllamaEmbedder, Store

RuleTools = SyncToolClient | InProcessRulesClient | fixture.FakeToolClient


class RunCancelled(BaseException):  # noqa: N818 - BaseException: the agent's `except Exception` must not swallow it
    """Raised inside the worker thread when the client went away."""


class CancellableLLM:
    """Checks `is_cancelled()` before every streamed token, so a disconnect stops generation
    (closing the generator closes the HTTP stream to Ollama)."""

    def __init__(self, inner: LLM, is_cancelled: Any) -> None:
        self._inner, self._is_cancelled = inner, is_cancelled

    def _wrap(self, it):
        for tok in it:
            if self._is_cancelled():
                close = getattr(it, "close", None)
                if close:
                    close()
                raise RunCancelled
            yield tok

    def chat(self, messages, *, temperature: float = 0.0, seed: int | None = None):
        if self._is_cancelled():
            raise RunCancelled
        return self._wrap(self._inner.chat(messages, temperature=temperature, seed=seed))

    def generate(self, prompt, *, temperature: float = 0.0, seed: int | None = None):
        if self._is_cancelled():
            raise RunCancelled
        return self._wrap(self._inner.generate(prompt, temperature=temperature, seed=seed))


@dataclass
class Services:
    store: Store
    graph: GraphStore
    agent: Agent | None = None
    tools: RuleTools | None = None
    index_present: bool = True
    graph_present: bool = True

    def close(self) -> None:
        if self.tools is not None:
            self.tools.close()
        self.store.close()
        self.graph.close()


def _mcp_tools(cfg: ApiConfig) -> SyncToolClient | None:
    if not cfg.facts_path:
        return None
    from detective_board.mcp.client import open_session, server_params  # lazy: needs `mcp`

    params = server_params(
        str(cfg.resolve(cfg.facts_path)),
        cfg.facts_allow or str(cfg.resolve(cfg.facts_path).parent),
    )
    return SyncToolClient(lambda: open_session(params))


def build_services(
    cfg: ApiConfig, *, with_agent: bool, is_cancelled: Any = lambda: False
) -> Services:
    tools: RuleTools | None
    if cfg.fake:
        store, emb = fixture.build_store()
        graph = fixture.build_graph()
        llm: LLM = fixture.build_llm()
        # demo flavour: the real rules over the fixture graph; lean (tests): one canned finding
        tools = InProcessRulesClient(graph) if fixture.demo_mode() else fixture.FakeToolClient()
    else:
        emb_cfg = EmbeddingConfig(
            model=cfg.embed_model,
            dim=cfg.embed_dim,
            doc_prefix=cfg.embed_doc_prefix,
            query_prefix=cfg.embed_query_prefix,
        )
        index, gpath = cfg.resolve(cfg.index_path), cfg.resolve(cfg.graph_path)
        if not index.exists():  # never create an empty index implicitly
            raise FileNotFoundError(index_missing_message(cfg))
        store = Store(index, emb_cfg)
        graph = GraphStore(str(gpath)) if gpath.exists() else GraphStore()
        if not gpath.exists():
            print(f"warning: {graph_missing_message(cfg)}", file=sys.stderr)
        emb = OllamaEmbedder(emb_cfg, base_url=cfg.ollama_host)
        llm = OllamaLLM(
            cfg.llm_model, cfg.ollama_host, num_ctx=cfg.num_ctx, timeout=cfg.llm_timeout_s
        )
        tools = None
        if with_agent:  # stdio MCP over a FactBase file if configured, else the same tools
            tools = _mcp_tools(cfg) or (InProcessRulesClient(graph) if gpath.exists() else None)
    svc = Services(
        store, graph, tools=tools, graph_present=cfg.fake or cfg.resolve(cfg.graph_path).exists()
    )
    if with_agent:
        client: ToolClient | None = tools
        svc.agent = Agent(
            CancellableLLM(llm, is_cancelled),  # type: ignore[arg-type]
            HybridRetriever(store, emb),
            graph=graph,  # type: ignore[arg-type]
            tools=client,
            config=_agent_cfg(cfg),
        )
    return svc


def _agent_cfg(cfg: Any) -> Any:
    """Agent thresholds; the window word weights default to the corpus next to the index."""
    ac = cfg.agent_config()
    if not ac.idf_chunks:
        chunks = cfg.resolve("data/chunks.jsonl")
        if chunks.exists():
            ac = dataclasses.replace(ac, idf_chunks=str(chunks))
    return ac
