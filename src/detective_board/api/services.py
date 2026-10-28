"""Wiring: construct Store / HybridRetriever / GraphStore / Agent from an `ApiConfig`.

SQLite connections are bound to the thread that opened them, so `build_services` is called once
inside each worker thread (see `runtime.py`); never share a `Services` between threads."""

from __future__ import annotations

import dataclasses
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from detective_board.agent import LLM, Agent, HybridRetriever, OllamaLLM, ToolClient
from detective_board.agent.rules_client import InProcessRulesClient
from detective_board.api import fixture
from detective_board.api.config import ApiConfig, graph_missing_message, index_missing_message
from detective_board.api.tool_client import SyncToolClient
from detective_board.graph import GraphStore
from detective_board.retrieval import EmbeddingConfig, OllamaEmbedder, Store
from detective_board.retrieval.sentences import SentenceIndexError, SentenceStore

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

    def chat(
        self,
        messages,
        *,
        temperature: float = 0.0,
        seed: int | None = None,
        format=None,
        num_predict: int | None = None,
    ):
        if self._is_cancelled():
            raise RunCancelled
        return self._wrap(
            self._inner.chat(
                messages,
                temperature=temperature,
                seed=seed,
                format=format,
                num_predict=num_predict,
            )
        )

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
    sentences: SentenceStore | None = None  # optional sentence index (extractive candidates)

    def close(self) -> None:
        if self.sentences is not None:
            self.sentences.close()
        if self.tools is not None:
            self.tools.close()
        self.store.close()
        self.graph.close()


def mcp_status(cfg: ApiConfig, graph_present: bool, tools: Any = None) -> dict[str, Any]:
    """How the rule tools are reached, mirroring `build_services`: what `tool_call.server` shows.
    `tools` is the live ask-side client, when one exists: it tells whether the stdio server is
    up (then `version` and `tools` are reported) or the labelled in-process fallback took over."""
    if cfg.fake and not fixture.demo_mode():
        return {"configured": True, "mode": "fake", "server": "timeline-alibi"}
    if cfg.fake:
        return {"configured": True, "mode": "in-process", "server": InProcessRulesClient.server}
    if not cfg.facts_path and not graph_present:
        return {"configured": False, "mode": "none", "server": None}
    if isinstance(tools, InProcessRulesClient):  # the stdio server could not start
        return {"configured": True, "mode": "in-process", "server": InProcessRulesClient.server}
    out: dict[str, Any] = {"configured": True, "mode": "stdio", "server": "timeline-alibi"}
    info = getattr(tools, "info", None)
    out["started"] = bool(getattr(tools, "started", False))
    if out["started"] and info:
        out["version"] = info.get("version")
        out["tools"] = info.get("tools")
    return out


def _mcp_tools(cfg: ApiConfig) -> SyncToolClient | None:
    if not cfg.facts_path:
        return None
    from detective_board.mcp.client import open_session, server_params  # lazy: needs `mcp`

    params = server_params(
        str(cfg.resolve(cfg.facts_path)),
        cfg.facts_allow or str(cfg.resolve(cfg.facts_path).parent),
    )
    return SyncToolClient(lambda: open_session(params))


def _graph_tools(cfg: ApiConfig, graph: GraphStore, gpath: Path) -> RuleTools:
    """Default rule tools: the stdio `timeline-alibi` server over the graph file, read-only,
    spawned now and kept for the session. If it cannot start, the same tool functions run
    in-process, labelled `timeline-alibi[in-process]` in the trace."""
    try:
        from detective_board.mcp.client import graph_server_params, open_session

        params = graph_server_params(str(gpath), str(gpath.parent))
        client = SyncToolClient(lambda: open_session(params))
        if client.start():
            return client
        client.close()
    except Exception as exc:  # noqa: BLE001 - a missing `mcp` package or a spawn error: fall back
        print(f"warning: MCP stdio server unavailable ({type(exc).__name__})", file=sys.stderr)
    else:
        print("warning: MCP stdio server did not start; using in-process rules", file=sys.stderr)
    return InProcessRulesClient(graph)


def build_services(
    cfg: ApiConfig, *, with_agent: bool, is_cancelled: Any = lambda: False
) -> Services:
    tools: RuleTools | None
    sentences: SentenceStore | None = None
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
        sentences = _open_sentences(cfg, emb_cfg)
        graph = GraphStore(str(gpath)) if gpath.exists() else GraphStore()
        if not gpath.exists():
            print(f"warning: {graph_missing_message(cfg)}", file=sys.stderr)
        emb = OllamaEmbedder(emb_cfg, base_url=cfg.ollama_host, keep_alive=cfg.keep_alive)
        llm = OllamaLLM(
            cfg.llm_model,
            cfg.ollama_host,
            num_ctx=cfg.num_ctx,
            keep_alive=cfg.keep_alive,
            timeout=cfg.llm_timeout_s,
        )
        tools = None
        if with_agent:  # stdio MCP: FactBase file if configured, else the graph file
            tools = _mcp_tools(cfg) or (_graph_tools(cfg, graph, gpath) if gpath.exists() else None)
    svc = Services(
        store, graph, tools=tools, graph_present=cfg.fake or cfg.resolve(cfg.graph_path).exists()
    )
    svc.sentences = sentences
    if with_agent:
        client: ToolClient | None = tools
        ac = _agent_cfg(cfg)
        translate_llm: LLM = llm  # the answer model by default: no second model in RAM
        if not cfg.fake and ac.translate_model != cfg.llm_model:
            translate_llm = OllamaLLM(
                ac.translate_model,
                cfg.ollama_host,
                num_ctx=cfg.num_ctx,
                keep_alive=cfg.keep_alive,
                timeout=cfg.llm_timeout_s,
            )
        svc.agent = Agent(
            CancellableLLM(llm, is_cancelled),  # type: ignore[arg-type]
            HybridRetriever(store, emb, sentences=svc.sentences),
            graph=graph,  # type: ignore[arg-type]
            tools=client,
            config=ac,
            translate_llm=CancellableLLM(translate_llm, is_cancelled),  # type: ignore[arg-type]
        )
    return svc


def _open_sentences(cfg: ApiConfig, emb_cfg: EmbeddingConfig) -> SentenceStore | None:
    """The optional sentence index; absent or incompatible -> None (the agent falls back)."""
    path = cfg.resolve(cfg.agent_config().sentence_index_path)
    if not path.exists():  # never create an empty one implicitly
        print(f"note: no sentence index at {path} (`just sentences`)", file=sys.stderr)
        return None
    try:
        st = SentenceStore(path, emb_cfg)
    except SentenceIndexError as e:
        print(f"warning: sentence index ignored: {e}", file=sys.stderr)
        return None
    if st.manifest().get("complete") != "1":
        print(f"warning: sentence index {path} is incomplete (rebuild it)", file=sys.stderr)
        st.close()
        return None
    return st


def _agent_cfg(cfg: Any) -> Any:
    """Agent thresholds; the window word weights default to the corpus next to the index."""
    ac = cfg.agent_config()
    if not ac.idf_chunks:
        chunks = cfg.resolve("data/chunks.jsonl")
        if chunks.exists():
            ac = dataclasses.replace(ac, idf_chunks=str(chunks))
    scenes = cfg.resolve("data/curated/scenes.jsonl")
    if not cfg.fake and not ac.scenes_path and scenes.exists():  # curated crime scenes (11.6)
        ac = dataclasses.replace(ac, scenes_path=str(scenes))
    if cfg.fake and "answer_mode" not in cfg.agent:  # the canned fixture model writes answers
        ac = dataclasses.replace(ac, answer_mode="generate")
    return ac
