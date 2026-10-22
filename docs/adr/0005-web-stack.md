# ADR-0005: Web stack (API, SSE trace stream, static UI)

- Status: Accepted
- Date: 2026-10-22
- Deciders: tech-lead, backend-engineer
- Provisional parts: none. Versions verified on PyPI / npm registry on 2026-10-22.

## Context

One local process must serve (a) a JSON API, (b) a Server-Sent Events stream of the agent's trace events (`POST /api/ask`), and (c) a static single-page UI with a graph view. Constraints: offline after setup (no CDN, no npm build at run time), CPU-only laptop, localhost demo, small dependency surface, tests without a network. The agent (`agent.Agent.ask`) is a synchronous generator; the MCP client is async. The stream is one-way (server to browser), so WebSocket is not needed.

## Options

Backend:

1. FastAPI 0.161.0 + uvicorn. Adds pydantic-based request validation and OpenAPI; pulls `opentelemetry-api`, `annotated-doc`, `typing-inspection`. We already have pydantic models, but the API has 6 endpoints and one request body; OpenAPI is not a requirement.
2. Starlette 1.9.0 + uvicorn 0.54.0 (what FastAPI is built on). Routing, `StreamingResponse`, `StaticFiles`, `TestClient` (needs `httpx`). Deps: `anyio`.
3. Starlette + `sse-starlette` 3.5.0 (`EventSourceResponse`: SSE framing, keep-alive pings, disconnect handling). One more package; its behaviour (ping, `\r\n` separators, shutdown handling) is another surface to verify offline.
4. stdlib `http.server` (threaded): no deps, but hand-written routing, no async, no robust disconnect/limits handling, no standard test client. aiohttp: a heavier dependency with its own test tooling, no gain over Starlette.

SSE framing is small (`event:`, `id:`, `data:` lines, blank line terminator, `: comment` for heartbeats), so a library only for it is not justified.

UI:

A. Vanilla JS as ES modules, served as static files; Cytoscape.js 3.34.4 (MIT) vendored as a single file `web/vendor/cytoscape.esm.min.mjs` (434 KB; `cytoscape.min.js` 436 KB also exists) copied once from the npm package, with its LICENSE and a sha256 recorded next to it. No build step.
B. A bundler (Vite/esbuild) plus npm install: needs Node at setup, a lockfile, and a build in `just run`; breaks "offline from clean checkout" unless node_modules is vendored too.

## Decision

- Backend: Starlette 1.9.0 (BSD-3-Clause, Python >=3.11) + uvicorn 0.54.0 (BSD-3-Clause, Python >=3.10). Tests: `httpx2` 2.16.0 (BSD-3-Clause, Python >=3.11; Starlette 1.9's `TestClient` needs an HTTP client and warns that `httpx` is deprecated in favour of `httpx2`; verified: no warning with `httpx2`). No FastAPI, no sse-starlette. Use plain `uvicorn` without the `standard` extra (h11, no uvloop/httptools/watchfiles; enough for one local client).
- SSE: own ~30-line formatter returned through `starlette.responses.StreamingResponse(media_type="text/event-stream")` over an async generator. One SSE event per trace event: `event: <type>`, `id: <seq>`, `data: <JSON of the pydantic model>`. A comment line `: keepalive` every 15 s. Headers `Cache-Control: no-cache`, `X-Accel-Buffering: no`. `POST` is used (question in the body), so the browser reads it with `fetch()` + `ReadableStream`, not `EventSource` (which is GET-only).
- Disconnect and cancellation: Starlette 1.9's `StreamingResponse` only listens for `http.disconnect` itself when the ASGI spec version is below 2.4; otherwise a failed send raises `OSError` (-> `ClientDisconnect`). We therefore (a) run the sync agent generator in a worker thread feeding an `asyncio.Queue`, (b) poll `request.is_disconnected()` while waiting, (c) set a cancel flag and `close()` the generator in a `finally`. The run stops at the next event boundary; a blocking LLM call already in flight is not interrupted (it finishes, its output is dropped). This is a documented limitation.
- UI: option A. Static files in `web/`, mounted with `StaticFiles(html=True)` after the `/api` routes. Vendored files are committed; nothing is fetched at run time.
- Security defaults: bind `127.0.0.1`; no CORS middleware (same origin only); request body limit (default 16 KiB) enforced before JSON parsing; no endpoint takes a filesystem path (`/api/source/{chunk_id}` looks the id up in the index and validates it against `^[A-Za-z0-9._-]{1,128}$`).

## Consequences

- Dependencies to add to `pyproject.toml` (not done by the backend zone; request to the devops/tech-lead owner): `starlette==1.9.0`, `uvicorn==0.54.0`, dev: `httpx2==2.16.0`. Transitive: `anyio`, `click`, `h11` (runtime); `httpcore2`, `idna`, `truststore` (tests).
- No automatic OpenAPI; the contract is hand-maintained in `docs/api.md` and checked by tests.
- Heartbeat/disconnect code is ours and tested (`tests/api`).
- Cytoscape upgrades are manual (copy file, update sha256). UI code has no type checking or minification; acceptable for a demo-size SPA.
- If the UI outgrows ES modules, a bundler can be added later without changing the API; revisit then.
