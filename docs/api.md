# HTTP API contract (v1)

Owner: backend-engineer. Stack: ADR-0005 (Starlette 1.9.0 + uvicorn 0.54.0). Code: `src/detective_board/api/`. Tests: `tests/api/`.

Run: `PYTHONPATH=src python -m detective_board.api --host 127.0.0.1 --port 8000 [--config FILE] [--fake]`
(`--fake`: FakeLLM and a 3-chunk in-memory fixture; no Ollama, no data files. The fake answer is canned: the question "What was the speckled band?" yields a verified answer citing `speckled-band-0001`; an off-topic question such as "What is the weather in Paris today?" yields a refusal; "Are there contradictions in James McCarthy's account?" calls a fake `find_contradictions` and yields one derived R3 finding with a full `explanation`, so the 'Why?' panel works. The fixture holds two extra chunks of `boscombe-valley-mystery` whose quotes are verbatim in `data/clean`.)

All JSON errors have the shape `{"error": {"code": str, "message": str}}`. No stack traces, no filesystem paths. Codes: `invalid_input` 400, `not_found` 404, `unsupported_media_type` 415, `too_large` 413, `busy` 429, `internal` 500.
Same origin only: no CORS headers are sent. Requests whose `Host` is not `localhost`/`127.0.0.1` are rejected with 400 (when bound to loopback).

## POST /api/ask  (Server-Sent Events)

Request: `Content-Type: application/json`, body at most 16 KiB:
`{"question": str (1..1000 chars), "history"?: [{"question": str, "answer": str}] (max 6, each field max 2000 chars)}`. Unknown keys are rejected.
Use `fetch()` with a `ReadableStream` reader (not `EventSource`, which cannot POST). `AbortController.abort()` cancels the run.

Response `200 text/event-stream`. One SSE message per trace event:

```
event: <type>
id: <seq>
data: <JSON>
```

`data` is exactly `model_dump_json()` of the model in `src/detective_board/agent/events.py` with `type == event`. Envelope on every event: `run_id`, `seq` (0-based, no gaps), `ts` (ISO-8601 UTC, ms), `step_id`, `duration_ms`.

Event types, in the order they occur: `route_decided`, `retrieval_started`, `retrieval_results` (hits with per-arm ranks/scores, gate), `graph_query`, `graph_results` (nodes, edges), `tool_call`, `tool_result`, `enriched_query` (numbered sources with labels), `answer_token` (`text`, `attempt`; a retry starts a new `attempt`, discard earlier tokens), `citation_check`, `refusal` (`code`, `message`, `missing`, `searched`), and finally `final`. Retrieval, graph and tool steps may be absent depending on the route; a refusal may skip `enriched_query`.

`final` is the last agent event and carries: `status` (`answered`|`partial`|`refused`), `verified`, `answer`, `citations[]` (`n`, `quote`, `label`, `anchor{story, chunk_id, char_start, char_end, quote}`), `provenance[]` (`n`, `label` in `extracted|derived|conditional|source_text`, `origin`, `rule_id`, `summary`, `explanation`: the item's symbolic `Explanation`, present only for rule-derived items, else `null`), `route`, `attempts`, `refusal_code`. After `final` the server closes the stream.

Extra event, not an agent model: `event: run_error`, `data: {"code": "internal"|"unavailable"|"timeout", "message": str}`. It replaces `final` when the run failed (LLM down, index missing, 600 s limit); trace events delivered before it are valid. Treat it as terminal.

Keep-alive: a comment line `: keepalive` every 15 s of silence (ignore it). One run at a time: a second `POST` while a run is active returns `429 busy` (JSON, not a stream); retry shortly. Closing the connection cancels the run at the next streamed token (an in-flight prompt prefill is not interruptible).

### Symbolic `Explanation` in the trace (R-14)

`tool_result` has optional `provenance` (`derived`|`conditional`|`extracted`, as the MCP tool reported it; for `find_contradictions` the label of the first finding) and `explanation`: the `Explanation` object of docs/symbolic-layer.md section 3.1 (`rule_id`, `rule_version`, `verdict`, `conditional`, `reason_code`, `facts`, `edges`, `derivation`, `anchors`, `depends_on_extracted`, `weak`, `missing`, `notes`, `subject`, `suspects`). It is the tool's own object, validated and serialised, never rewritten by the agent: top-level `explanation` of the tool result (`check_alibi`), else that of the first finding/overlap. Findings after the first are reachable through `final.provenance[].explanation`. Both fields are `null` when the tool gave none or the object does not validate (it is dropped, not repaired). Models are `extra=forbid`; clients should still ignore unknown fields.
`graph_results.edges[]` carry `provenance: "derived"` and `explanation` only for rule-derived edges (the explanation is read from the edge's stored `props.explanation`); extracted edges are unchanged.

## GET /api/graph/subgraph?entity=..&hops=..&story=..

`entity`: required, node id (e.g. `p:speckled-band:helen-stoner`) or exact entity name/alias (normalised; titles and case ignored; no substring match: use `/api/graph/entities` to find ids). `hops`: integer 0..3, default 1. `story`: optional story slug filter. At most 200 nodes (`truncated: true` when cut).
Response:
```
{"query_kind": "neighbours", "entity": str, "hops": int, "seeds": [node_id],
 "nodes": [{"id","kind": person|place|item|event|claim,"story","name","label","aliases","confidence": high|low,
            "provenance": extracted|derived,"props","anchors":[Anchor],"anchor_total","hops"}],
 "edges": [{"id","rel","src","dst","confidence","provenance","props","anchor": Anchor,
            "explanation"?: Explanation  // only when provenance == "derived" and one is stored}],
 "anchors": [Anchor], "truncated": bool, "notes": [str]}
Anchor = {"story","chunk_id","char_start","char_end","quote","rel_start","rel_end","ambiguous"}
```
Unknown entity: `200` with empty `seeds`/`nodes`. `char_*` are absolute offsets in the cleaned story text; `rel_*` are offsets inside the chunk.

## GET /api/graph/entities?q=..&kind=..&story=..&limit=..

Entity search for autocomplete: case-insensitive substring over names and aliases, exact matches first, then by mention count. `q` optional (empty lists the most mentioned entities), `kind` in `person|place|item`, `limit` 1..100 (default 25).
Response: `{"q", "entities": [node as above + "mentions": int], "total": int, "truncated": bool}`.

## GET /api/source/{chunk_id}?quote=..&start=..&end=..

`chunk_id` must match `[A-Za-z0-9._-]{1,128}` and is looked up in the index (never a path). Optional `quote` (max 1000 chars) and/or absolute `start`/`end` (a citation anchor) to get highlight ranges.
Response: `{"chunk_id","story","section","para_start","para_end","char_start","char_end","contiguous": bool,"text","highlights":[{"rel_start","rel_end","char_start","char_end","match": "exact"|"ws_normalised"|"offsets"}]}`.
Highlight with `text.slice(rel_start, rel_end)`. `char_*` in highlights are absolute (`chunk.char_start + rel`) and only meaningful when `contiguous` is true. `404 not_found` for unknown chunks.

## GET /api/health

Always `200`; `status` is `ok` or `degraded`:
`{"status","fake","ollama":{"reachable": bool|null,"models":{"llm": bool,"embedding": bool}},"index":{"present","chunks","vectors"},"graph":{"present","counts":{...}},"mcp":{"configured"},"busy","versions":{"api","python","starlette","index_schema","index_manifest"}}`.
Ollama is checked with `GET /api/tags` (2 s timeout; lists models, loads nothing). In fake mode Ollama is not contacted.

## GET /api/config

Non-secret effective settings: `{"fake","models":{"llm","embedding"},"agent":{<AgentConfig thresholds>},"limits":{...},"events":[<all SSE event names>]}`. No paths.

## Static UI

Everything else is served from `web/` (`index.html` at `/`, ES modules, vendored libraries under `web/vendor/`). Unknown `/api/*` paths return JSON 404.

## Configuration

Precedence: defaults < TOML file (`--config` or `$DETECTIVE_BOARD_CONFIG`) < env `DETECTIVE_BOARD_<FIELD>` < CLI. Fields: `host`, `port`, `fake`, `index_path`, `graph_path`, `facts_path`, `facts_allow`, `web_dir`, `ollama_host`, `llm_model`, `embed_model`, `embed_dim`, `embed_doc_prefix`, `embed_query_prefix`, `num_ctx`, limits, and an `[agent]` table of `AgentConfig` thresholds (env: `DETECTIVE_BOARD_AGENT_<NAME>`). Unknown keys are an error. Defaults: `data/index.sqlite`, `data/graph.sqlite`, `qwen3:8b`, `nomic-embed-text` (768, prefixes `search_document: ` / `search_query: `); the embedding settings must match how the index was built (the store refuses a mismatch). MCP tools are enabled only when `facts_path` (a FactBase JSON) is set.
