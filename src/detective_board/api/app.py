"""Starlette application: /api/* plus the static UI (see docs/api.md)."""

from __future__ import annotations

import asyncio
import json
import platform
import re
import threading
import time
import urllib.request
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any

import starlette
from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.middleware import Middleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from detective_board.agent import Turn
from detective_board.api import graph_view, sse
from detective_board.api.config import ApiConfig
from detective_board.api.runtime import Busy, Runtime
from detective_board.retrieval import SCHEMA_VERSION as INDEX_SCHEMA_VERSION

API_VERSION = "1"
POLL_S = 0.25  # how often a waiting stream checks for a client disconnect
_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_STORY = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_MESSAGES = {
    "internal": "The run failed. See the server log.",
    "unavailable": "Index or graph is not available. Build the data first.",
    "timeout": "The run exceeded the time limit and was stopped.",
}

OllamaProbe = Callable[[], "list[str] | None"]


class SecurityHeaders:
    """Pure ASGI (BaseHTTPMiddleware would interfere with streaming and disconnects)."""

    HEADERS = ((b"x-content-type-options", b"nosniff"), (b"referrer-policy", b"no-referrer"))

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def wrapped(message: Any) -> None:
            if message["type"] == "http.response.start":
                message = {**message, "headers": [*message.get("headers", []), *self.HEADERS]}
            await send(message)

        await self.app(scope, receive, wrapped)


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        self.status, self.code, self.message = status, code, message


def _err(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status)


def ollama_models(host: str, timeout: float = 1.5) -> list[str] | None:
    """Model names from Ollama's documented `GET /api/tags`; None when unreachable. Lists only,
    never loads or runs a model."""
    try:
        with urllib.request.urlopen(host.rstrip("/") + "/api/tags", timeout=timeout) as r:  # noqa: S310
            return [m["name"] for m in json.load(r).get("models", [])]
    except Exception:  # noqa: BLE001
        return None


def _has_model(names: list[str], want: str) -> bool:
    got = set(names) | {n.removesuffix(":latest") for n in names}
    return want in got or f"{want}:latest" in got


def _qint(request: Request, name: str, default: int, lo: int, hi: int) -> int:
    raw = request.query_params.get(name)
    if raw is None or raw == "":
        return default
    try:
        v = int(raw)
    except ValueError:
        raise ApiError(400, "invalid_input", f"{name} must be an integer") from None
    if not lo <= v <= hi:
        raise ApiError(400, "invalid_input", f"{name} must be between {lo} and {hi}")
    return v


def _qstr(request: Request, name: str, maxlen: int, *, required: bool = False) -> str | None:
    v = request.query_params.get(name)
    if v is None or v.strip() == "":
        if required:
            raise ApiError(400, "invalid_input", f"{name} is required")
        return None
    if len(v) > maxlen:
        raise ApiError(400, "invalid_input", f"{name} is longer than {maxlen} characters")
    return v.strip()


def _story_param(request: Request) -> str | None:
    s = _qstr(request, "story", 64)
    if s is not None and not _STORY.match(s):
        raise ApiError(400, "invalid_input", "story has invalid characters")
    return s


def build_app(
    config: ApiConfig | None = None,
    *,
    ollama_probe: OllamaProbe | None = None,
    runtime: Runtime | None = None,
) -> Starlette:
    """Construct Store / HybridRetriever / GraphStore / Agent lazily (in worker threads) from
    `config` and return the ASGI app. `config.fake=True` uses FakeLLM and a tiny fixture."""
    cfg = config or ApiConfig()
    rt = runtime or Runtime(cfg)
    probe: OllamaProbe = ollama_probe or (lambda: ollama_models(cfg.ollama_host))

    # ---------------------------------------------------------------- /api/ask
    async def read_json(request: Request) -> Any:
        if (
            request.headers.get("content-type", "").split(";")[0].strip().lower()
            != "application/json"
        ):
            raise ApiError(415, "unsupported_media_type", "Content-Type must be application/json")
        cl = request.headers.get("content-length")
        if cl and cl.isdigit() and int(cl) > cfg.max_body_bytes:
            raise ApiError(413, "too_large", f"body exceeds {cfg.max_body_bytes} bytes")
        buf = bytearray()
        async for chunk in request.stream():
            buf += chunk
            if len(buf) > cfg.max_body_bytes:
                raise ApiError(413, "too_large", f"body exceeds {cfg.max_body_bytes} bytes")
        try:
            return json.loads(bytes(buf))
        except ValueError:
            raise ApiError(400, "invalid_input", "body is not valid JSON") from None

    def parse_ask(body: Any) -> tuple[str, list[Turn]]:
        if not isinstance(body, dict) or set(body) - {"question", "history"}:
            raise ApiError(
                400, "invalid_input", 'body must be {"question": str, "history"?: [...]}'
            )
        q = body.get("question")
        if not isinstance(q, str) or not q.strip():
            raise ApiError(400, "invalid_input", "question must be a non-empty string")
        if len(q) > cfg.max_question_chars:
            raise ApiError(400, "invalid_input", f"question exceeds {cfg.max_question_chars} chars")
        hist = body.get("history", [])
        if not isinstance(hist, list) or len(hist) > cfg.max_history_turns:
            raise ApiError(
                400, "invalid_input", f"history: list of at most {cfg.max_history_turns}"
            )
        turns = []
        for t in hist:
            if (
                not isinstance(t, dict)
                or set(t) != {"question", "answer"}
                or not all(isinstance(t[k], str) and len(t[k]) <= cfg.max_turn_chars for k in t)
            ):
                raise ApiError(400, "invalid_input", "history items: {question, answer} strings")
            turns.append(Turn(t["question"], t["answer"]))
        return q.strip(), turns

    async def ask(request: Request) -> Response:
        question, history = parse_ask(await read_json(request))
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()
        cancel = threading.Event()

        def put(item: tuple[str, Any]) -> None:
            try:
                loop.call_soon_threadsafe(queue.put_nowait, item)
            except RuntimeError:  # loop already closed (server shutdown)
                pass

        try:
            rt.start_run(question, history, cancel, put)
        except Busy:
            return _err(429, "busy", "Another run is in progress. Retry in a moment.")

        async def stream() -> AsyncIterator[bytes]:
            started = last = checked = time.monotonic()
            try:
                while True:
                    if time.monotonic() - checked >= POLL_S:  # busy streams never time out below
                        checked = time.monotonic()
                        if await request.is_disconnected():
                            return
                    try:
                        kind, val = await asyncio.wait_for(queue.get(), POLL_S)
                    except TimeoutError:
                        now = time.monotonic()
                        if await request.is_disconnected():
                            return
                        if now - started > cfg.run_timeout_s:
                            yield _error_frame("timeout")
                            return
                        if now - last >= cfg.keepalive_s:
                            last = now
                            yield sse.KEEPALIVE
                        continue
                    last = time.monotonic()
                    if kind == "end":
                        return
                    if kind == "error":
                        yield _error_frame(val)
                        continue
                    yield sse.frame(val.type, val.model_dump_json(), val.seq)
            finally:
                cancel.set()  # disconnect, timeout, normal end: stop the worker at the next token

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    def _error_frame(code: str) -> bytes:
        data = {"code": code, "message": _MESSAGES.get(code, _MESSAGES["internal"])}
        return sse.frame("run_error", json.dumps(data))

    # ---------------------------------------------------------------- graph
    async def subgraph(request: Request) -> Response:
        entity = _qstr(request, "entity", 200, required=True)
        hops = _qint(request, "hops", 1, 0, cfg.max_hops)
        story = _story_param(request)
        out = await rt.read(
            lambda s: graph_view.subgraph(
                s.graph,
                entity,
                hops,
                story=story,
                max_nodes=cfg.max_graph_nodes,  # type: ignore[arg-type]
            )
        )
        return JSONResponse(out)

    async def entities(request: Request) -> Response:
        q = _qstr(request, "q", 200) or ""
        kind = _qstr(request, "kind", 16)
        if kind is not None and kind not in graph_view.ENTITY_KINDS:
            raise ApiError(400, "invalid_input", f"kind must be one of {graph_view.ENTITY_KINDS}")
        limit = _qint(request, "limit", 25, 1, 100)
        story = _story_param(request)
        out = await rt.read(
            lambda s: graph_view.search_entities(s.graph, q, kind=kind, story=story, limit=limit)
        )
        return JSONResponse(out)

    # ---------------------------------------------------------------- source
    def highlights(
        text: str, c0: int, quote: str | None, start: int | None, end: int | None
    ) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        contiguous_abs = lambda r0, r1: (c0 + r0, c0 + r1)  # noqa: E731
        if quote:
            pos = text.find(quote)
            while pos != -1 and len(out) < 20:
                out.append({"rel_start": pos, "rel_end": pos + len(quote), "match": "exact"})
                pos = text.find(quote, pos + len(quote))
            if not out:
                pat = r"\s+".join(re.escape(w) for w in quote.split())
                for m in list(re.finditer(pat, text))[:20] if pat else []:
                    out.append(
                        {"rel_start": m.start(), "rel_end": m.end(), "match": "ws_normalised"}
                    )
        if start is not None and end is not None and 0 <= start - c0 < end - c0 <= len(text):
            out.append({"rel_start": start - c0, "rel_end": end - c0, "match": "offsets"})
        for h in out:
            h["char_start"], h["char_end"] = contiguous_abs(h["rel_start"], h["rel_end"])
        return out

    async def source(request: Request) -> Response:
        cid = request.path_params["chunk_id"]
        if not _ID.match(cid):
            raise ApiError(400, "invalid_input", "invalid chunk_id")
        quote = _qstr(request, "quote", cfg.max_quote_chars)
        start = _qint(request, "start", -1, -1, 2**31)
        end = _qint(request, "end", -1, -1, 2**31)

        def look(s):
            return s.store.db.execute(
                "SELECT chunk_id, story, section, para_start, para_end, char_start, char_end, text"
                " FROM chunks WHERE chunk_id=?",
                (cid,),
            ).fetchone()

        row = await rt.read(look)
        if row is None:
            raise ApiError(404, "not_found", f"unknown chunk: {cid}")
        text = row["text"]
        return JSONResponse(
            {
                "chunk_id": row["chunk_id"],
                "story": row["story"],
                "section": row["section"],
                "para_start": row["para_start"],
                "para_end": row["para_end"],
                "char_start": row["char_start"],
                "char_end": row["char_end"],
                "contiguous": len(text) == row["char_end"] - row["char_start"],
                "text": text,
                "highlights": highlights(
                    text,
                    row["char_start"],
                    quote,
                    None if start < 0 else start,
                    None if end < 0 else end,
                ),
            }
        )

    # ---------------------------------------------------------------- health / config
    async def health(request: Request) -> Response:
        def local(s):
            n_chunks = s.store.db.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
            n_vec = s.store.db.execute("SELECT COUNT(*) FROM chunk_vec").fetchone()[0]
            return {
                "chunks": n_chunks,
                "vectors": n_vec,
                "manifest": s.store.manifest(),
                "graph": s.graph.stats(),
                "graph_present": s.graph_present,
            }

        data, err = await asyncio.to_thread(rt.try_read, local)
        index = {"present": data is not None and data["chunks"] > 0}
        graph = {"present": data is not None and data["graph_present"]}
        if data:
            index |= {"chunks": data["chunks"], "vectors": data["vectors"]}
            graph |= {"counts": data["graph"]}
        if err:
            index["error"] = graph["error"] = err
        if cfg.fake:
            ollama = {"reachable": None, "skipped": "fake mode"}
            ok_ollama = True
        else:
            names = await asyncio.to_thread(probe)
            want = {"llm": cfg.llm_model, "embedding": cfg.embed_model}
            ollama = {
                "reachable": names is not None,
                "models": {k: names is not None and _has_model(names, v) for k, v in want.items()},
            }
            ok_ollama = names is not None and all(ollama["models"].values())
        ok = ok_ollama and index["present"] and graph["present"]
        return JSONResponse(
            {
                "status": "ok" if ok else "degraded",
                "fake": cfg.fake,
                "ollama": ollama,
                "index": index,
                "graph": graph,
                "mcp": {"configured": bool(cfg.facts_path)},
                "busy": rt.busy,
                "versions": {
                    "api": API_VERSION,
                    "python": platform.python_version(),
                    "starlette": starlette.__version__,
                    "index_schema": INDEX_SCHEMA_VERSION,
                    "index_manifest": data["manifest"] if data else None,
                },
            }
        )

    async def config(request: Request) -> Response:
        return JSONResponse(
            {
                "fake": cfg.fake,
                "models": {
                    "llm": "fake" if cfg.fake else cfg.llm_model,
                    "embedding": "fake-hash" if cfg.fake else cfg.embed_model,
                },
                "agent": {k: v for k, v in vars(cfg.agent_config()).items()},
                "limits": {
                    "max_body_bytes": cfg.max_body_bytes,
                    "max_question_chars": cfg.max_question_chars,
                    "max_history_turns": cfg.max_history_turns,
                    "max_hops": cfg.max_hops,
                    "max_graph_nodes": cfg.max_graph_nodes,
                    "keepalive_s": cfg.keepalive_s,
                    "run_timeout_s": cfg.run_timeout_s,
                },
                "events": [
                    "route_decided",
                    "retrieval_started",
                    "retrieval_results",
                    "graph_query",
                    "graph_results",
                    "tool_call",
                    "tool_result",
                    "enriched_query",
                    "answer_token",
                    "citation_check",
                    "refusal",
                    "final",
                    "run_error",
                ],
            }
        )

    # ---------------------------------------------------------------- app
    routes: list[Any] = [
        Route("/api/ask", ask, methods=["POST"]),
        Route("/api/graph/subgraph", subgraph, methods=["GET"]),
        Route("/api/graph/entities", entities, methods=["GET"]),
        Route("/api/source/{chunk_id}", source, methods=["GET"]),
        Route("/api/health", health, methods=["GET"]),
        Route("/api/config", config, methods=["GET"]),
    ]
    web = cfg.resolve(cfg.web_dir)
    if web.is_dir():
        routes.append(Mount("/", StaticFiles(directory=web, html=True), name="web"))

    async def on_api_error(request: Request, exc: Exception) -> Response:
        assert isinstance(exc, ApiError)
        return _err(exc.status, exc.code, exc.message)

    async def on_http_error(request: Request, exc: Exception) -> Response:
        assert isinstance(exc, HTTPException)
        code = {404: "not_found", 405: "method_not_allowed"}.get(exc.status_code, "http_error")
        return _err(exc.status_code, code, str(exc.detail))

    async def on_unhandled(request: Request, exc: Exception) -> Response:
        return _err(500, "internal", "Internal error. See the server log.")

    @asynccontextmanager
    async def lifespan(_app: Starlette) -> AsyncIterator[None]:
        yield
        await asyncio.to_thread(rt.close)

    app = Starlette(
        routes=routes,
        middleware=[
            Middleware(TrustedHostMiddleware, allowed_hosts=cfg.allowed_hosts()),
            Middleware(SecurityHeaders),
        ],
        exception_handlers={
            ApiError: on_api_error,
            HTTPException: on_http_error,
            Exception: on_unhandled,
        },
        lifespan=lifespan,
    )
    app.state.runtime = rt
    app.state.config = cfg
    return app
