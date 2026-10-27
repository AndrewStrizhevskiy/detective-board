# HTTP API contract (v1)

Owner: backend-engineer. Stack: ADR-0005 (Starlette 1.9.0 + uvicorn 0.54.0). Code: `src/detective_board/api/`. Tests: `tests/api/`.

Run: `PYTHONPATH=src python -m detective_board.api --host 127.0.0.1 --port 8000 [--config FILE] [--fake]`
(`--fake`: FakeLLM and a 3-chunk in-memory fixture; no Ollama, no data files. The fake answer is canned: the question "What was the speckled band?" yields a verified answer citing `speckled-band-0001`; an off-topic question such as "What is the weather in Paris today?" yields a refusal; "Are there contradictions in James McCarthy's account?" calls a fake `find_contradictions` and yields one derived R3 finding with a full `explanation`, so the 'Why?' panel works. The fixture holds two extra chunks of `boscombe-valley-mystery` whose quotes are verbatim in `data/clean`. That canned finding is the lean flavour used by the tests. The demo flavour (a real `--fake` server, or `DETECTIVE_BOARD_FIXTURE=demo`) runs the real rules in-process over the fixture graph: "Is there a conflict about where Garcia was at about one o'clock on the night he died?" yields an R1 `violated`, `conditional` finding (Wisteria Lodge, gold c001); the James McCarthy question yields no rule finding and, with the default `rule_first`, the fixed no-violation answer with coverage numbers and source passages (gold c042).)

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

Event types, in the order they occur: `route_decided`, `retrieval_started`, `retrieval_results` (hits with per-arm ranks/scores, gate), `graph_query`, `graph_results` (nodes, edges), `tool_call`, `tool_result`, `enriched_query` (numbered sources with labels; each source carries the shown excerpt as `window_start`/`window_end` in chunk offsets and `window_char_start`/`window_char_end` in story offsets; plus `prompt_tokens_estimate` = chars/4, `max_prompt_tokens`, `strategy` (`rank_full`: top-1 chunk whole, ranks 2.. as windows of `window_words`; `uniform`: windows for all), `window_words`, and `dropped_chunks`: chunk ids removed by the prompt budget, lowest rank first), `answer_token` (`text`, `attempt`; a retry starts a new `attempt`, discard earlier tokens), `citation_check`, `refusal` (`code`, `message`, `missing`, `searched`), and finally `final`. When the relevance gate passed but the model declined, the agent retries once with a firmer instruction (`citation_check` with `action: retry` and the problem `model declined, retrying with a firmer instruction`; same sources, no re-retrieve; `[agent] decline_retry`). If it still declines and the gate `support` is at least `decline_fallback_min_support` (0.5), `final` is `status: partial`, `verified: true`, with up to two verbatim `source_text` quotes under a fixed 'closest passages' sentence; otherwise the plain refusal stays. Retrieval, graph and tool steps may be absent depending on the route; a refusal may skip `enriched_query`.

**Rule-first answers** (`AgentConfig.rule_first`, default true; shown in `/api/config` under `agent`). When the router picks a rule tool (`find_contradictions` or `check_alibi`: contradiction and alibi questions) the model is not called. The events are the same, so a client needs no change: `route_decided`, retrieval, graph, `tool_call`, `tool_result`, then `enriched_query` (its `strategy` reads `rule-first (findings|empty|failed): no model call`, `prompt_chars` is 0, `sources` are the quotes the answer cites), `answer_token` events that stream the template at once, `citation_check` (the same verbatim check, which passes by construction) and `final` with `citations`, `provenance` and the tool's `explanation`. The answer is a fixed template: one sentence per finding with its rule id, verdict, label (`derived`|`conditional` with the low-confidence inputs) and verbatim quotes; or, when the rule returned nothing, `The rule engine found no violation among the facts extracted for <story>. This does not show that the accounts are consistent: <coverage>` (events and claims in the graph, how many have an exact clock time, a story day or a presence proposition, pairs R1 could not decide) plus up to three retrieved passages labelled `source_text` and marked as not rule results; or, when the tool failed, was skipped or the name is ambiguous, what was missing. With `rule_first=false` the LLM path runs, and its self-check rejects (with a retry hint) any answer that asserts consistency or absence of conflict when the rule result is empty or failed.

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
`{"status","fake","ollama":{"reachable": bool|null,"models":{"llm": bool,"embedding": bool}},"index":{"present","chunks","vectors"},"graph":{"present","counts":{...}},"mcp":{"configured","mode","server"},"warm":{"state","embedding","llm","seconds","error"},"busy","versions":{"api","python","starlette","index_schema","index_manifest"}}`.
`mcp.mode` is `stdio` (`facts_path` set; server label `timeline-alibi`), `in-process` (no `facts_path`, graph present; label `timeline-alibi[in-process]`, as shown in `tool_call.server`), `none` (no rule tools; `server` null), or `fake` (lean `--fake` fixture). `warm` is the start-up warm-up (real mode only, started by `python -m detective_board.api`, never by `build_app`): `state` is `idle|running|done|failed|skipped`; `embedding`/`llm` are true/false/null; `seconds`; `error` (exception class names only). It runs in a background thread and is never fatal: a question asked while it runs just runs normally (Ollama queues the requests). It loads the embedding model, then the answer model with one 1-token chat whose first message is the real static system prompt, so Ollama can reuse its KV prefix (about 8-10 s less time to first token, docs/perf/ttft-levers-2026-10-26.md). Disable with `warmup = false`.

Ollama is checked with `GET /api/tags` (2 s timeout; lists models, loads nothing). In fake mode Ollama is not contacted.

## GET /api/config

Non-secret effective settings: `{"fake","models":{"llm","embedding"},"llm_options":{"num_ctx","keep_alive"},"agent":{<AgentConfig thresholds>},"limits":{...},"events":[<all SSE event names>]}`. No paths.

## Static UI

Everything else is served from `web/` (`index.html` at `/`, ES modules, vendored libraries under `web/vendor/`). Unknown `/api/*` paths return JSON 404.

## Configuration

Precedence: defaults < TOML file (`--config` or `$DETECTIVE_BOARD_CONFIG`) < env `DETECTIVE_BOARD_<FIELD>` < CLI. Fields: `host`, `port`, `fake`, `index_path`, `graph_path`, `facts_path`, `facts_allow`, `web_dir`, `ollama_host`, `llm_model`, `embed_model`, `embed_dim`, `embed_doc_prefix`, `embed_query_prefix`, `num_ctx` (default 4096, pinned for the answer path), `keep_alive` (default `30m`, the Ollama request field, sent with answer and embedding requests), `warmup` (default true), limits, and an `[agent]` table of `AgentConfig` thresholds (env: `DETECTIVE_BOARD_AGENT_<NAME>`). Unknown keys are an error. Defaults: `data/index/db.sqlite`, `data/graph/graph.sqlite`, `qwen3:4b-instruct` (ADR-0008), `bge-m3` (1024, no prefixes; identical to what `index.build` writes); the embedding settings must match how the index was built (the store refuses a mismatch). The rule tools run over the stdio MCP server when `facts_path` (a FactBase JSON) is set; otherwise, if the graph file exists, the same tool functions run in-process over the graph (`tool_call.server` is then `timeline-alibi[in-process]`). Run `python -m detective_board.extract.normalise <graph>` once after building the graph so events have normalised times and claims have propositions. `just run` first runs `scripts/preflight.py` (stdlib; exit 2 with a clear message when Ollama is unreachable or the answer/embedding model is not pulled); it is skipped with `--fake`.
