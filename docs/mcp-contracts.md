# MCP contracts

Status: DRAFT, Phase 0. Contracts are a design proposal; no server exists yet. SDK facts come only from `docs/spike/db-research.md` section 5 (desk research of `mcp` 2.3.0, nothing installed or run). Marks: **[U]** unverified, must be checked against current SDK docs before coding (mcp-engineer rule). Data model references: `docs/data-schema.md`.

Neuro-symbolic note (planned, not built): `check_alibi`, `find_overlaps` and the contradiction tool do not contain logic of their own. They parse input, load facts from the store, call the rules module (`src/detective_board/rules/`, rules R1-R3, `docs/symbolic-layer.md`) and map its result to the output below. The agent calls the same module in-process, so both paths give the same answer. `build_timeline` orders events with R2's order relation.

## 1. SDK facts used (from db-research.md)

- Package `mcp`, pin `>=2.3,<3` (ADR-0003); v1 `FastMCP` snippets are stale: v2 uses `from mcp.server import MCPServer` (README) / `mcp.server.mcpserver` (`MCPServer`, `Context`).
- Server: `mcp = MCPServer("name")`, `@mcp.tool()` on typed functions, `mcp.run()` defaults to stdio. A stdio server must not print to stdout.
- Client: `from mcp import Client, StdioServerParameters`; `async with Client(StdioServerParameters(command=..., args=[...], env={...})) as client:` then `await client.list_tools()`, `await client.call_tool(name, args)`; result has `structured_content`. The stdio child receives only a minimal env allow-list (HOME, PATH, ...); anything else goes through `env=`.
- **[U]** whether `@mcp.tool()` derives the JSON input schema from type hints and output schema from return annotations (v1 did; v2 not confirmed in fetched text). **[U]** per-call timeout parameter name on `Client.call_tool`; **[U]** how tool errors surface (`isError` on result vs exception). Until verified, timeouts are enforced by the caller with `asyncio.timeout()` / `anyio.fail_after()` around the call, and errors are normalised by our own wrapper (section 5).

## 2. Common conventions (all own servers)

- Transport: stdio, one child process per server, spawned by the agent's MCP client.
- Read-only store access: `timeline-alibi` opens the index read-only; it never calls an LLM and never touches the network.
- Every derived result carries an `explanation` object (shared definition below) and `provenance: "derived"`; a result that rests on a low-confidence extracted fact has `provenance: "conditional"` and `explanation.conditional: true` and `explanation.depends_on_extracted[]` listing those facts. Facts echoed from the graph are `provenance: "extracted"` with their confidence. No `explanation`, no conclusion.
- Every result carries `anchors[]` (the anchor object from data-schema.md 3.3) for each fact returned, so the answer can quote it. A tool must not return a conclusion without at least one anchor, except `status: "insufficient_evidence"`.
- Time model: `time_norm` from data-schema.md 3.1. Times are intervals `{start_min, end_min}` in minutes of the story day plus `story_day` (int or null); `null` = unknown. Tools never guess unknown times.
- IDs are node ids from the graph (`p:...`, `e:...`).
- Input is validated against the JSON Schema below; unknown properties are rejected (`additionalProperties: false`).
- Default timeout per call: 5 s (graph queries are in-memory/SQLite, no model call). Hard cap 15 s. Limits and defaults below are **[P]** until measured.

Shared definitions (referenced as `$defs`):

```json
{
  "Anchor": {"type": "object", "required": ["story","chunk_id","char_start","char_end","quote"],
    "properties": {"story": {"type":"string"}, "chunk_id": {"type":"string"},
      "char_start": {"type":"integer","minimum":0}, "char_end": {"type":"integer","minimum":0},
      "rel_start": {"type":"integer"}, "rel_end": {"type":"integer"}, "quote": {"type":"string"}}},
  "Explanation": {"description": "Mirror of detective_board.symbolic.api.Explanation (single source of truth: docs/symbolic-layer.md section 'Python interface'). Do not diverge.",
    "type": "object", "required": ["rule_id","rule_version","verdict","conditional","reason_code","facts","edges","derivation","anchors"],
    "properties": {"rule_id": {"enum": ["R1","R2","R3"]}, "rule_version": {"type":"string"},
      "verdict": {"enum": ["violated","consistent","unknown"]}, "conditional": {"type":"boolean"},
      "reason_code": {"type":"string"},
      "facts": {"type":"array","items":{"type":"object","required":["fact_id","kind","provenance","summary","anchors"],
        "properties":{"fact_id":{"type":"string"},"kind":{"enum":["event","claim","entity","order","relation","derived"]},
          "provenance":{"enum":["extracted","derived"]},"confidence":{"enum":["high","low",null]},
          "summary":{"type":"string"},"anchors":{"type":"array","items":{"$ref":"#/$defs/Anchor"}}}}},
      "edges": {"type":"array","items":{"type":"object","required":["edge_id","rel","src","dst","anchors"],
        "properties":{"edge_id":{"type":["integer","string"]},"rel":{"type":"string"},"src":{"type":"string"},"dst":{"type":"string"},
          "anchors":{"type":"array","items":{"$ref":"#/$defs/Anchor"}}}}},
      "derivation": {"type":"array","items":{"type":"object","required":["step","op","inputs","output"],
        "properties":{"step":{"type":"integer"},"op":{"type":"string"},"inputs":{"type":"array","items":{"type":"string"}},"output":{"type":"string"}}}},
      "anchors": {"type":"array","items":{"$ref":"#/$defs/Anchor"}},
      "depends_on_extracted": {"type":"array","items":{"type":"object"}, "description": "FactRef list: extracted facts the conclusion rests on"},
      "weak": {"type":"array","items":{"type":"string"}}, "missing": {"type":"array","items":{"type":"string"}},
      "notes": {"type":"array","items":{"type":"string"}}, "subject": {"type":"object","additionalProperties":{"type":"string"}}}},
  "Interval": {"type": "object", "required": ["start_min","end_min"],
    "properties": {"story_day": {"type":["integer","null"]},
      "start_min": {"type":"integer","minimum":0,"maximum":1440}, "end_min": {"type":"integer","minimum":0,"maximum":1440},
      "time_text": {"type":"string"}, "confidence": {"enum":["high","low"]}}}
}
```

## 3. Server `timeline-alibi` (own)

### 3.1 `build_timeline`

Description: ordered list of events for a story, optionally restricted to one person and/or place, with time intervals and anchors.

Input:
```json
{"type":"object","required":["story"],"additionalProperties":false,
 "properties":{"story":{"type":"string"},
  "person_id":{"type":"string"}, "place_id":{"type":"string"},
  "include_undated":{"type":"boolean","default":false},
  "limit":{"type":"integer","minimum":1,"maximum":200,"default":50}}}
```
Output:
```json
{"type":"object","required":["status","events"],
 "properties":{"status":{"enum":["ok","insufficient_evidence"]},
  "events":{"type":"array","items":{"type":"object","required":["event_id","description","anchors"],
    "properties":{"event_id":{"type":"string"},"description":{"type":"string"},
      "when":{"oneOf":[{"$ref":"#/$defs/Interval"},{"type":"null"}]},
      "place_id":{"type":["string","null"]},"participants":{"type":"array","items":{"type":"string"}},
      "anchors":{"type":"array","minItems":1,"items":{"$ref":"#/$defs/Anchor"}}}}},
  "undated_count":{"type":"integer"},"truncated":{"type":"boolean"}}}
```
Ordering: dated events by `(story_day, start_min)`; ties by `char_start` of the first anchor. Undated events are omitted unless `include_undated`, then appended in text order (never interleaved).

### 3.2 `check_alibi`

Description: given a person and a time window, report whether the text places the person elsewhere (contradiction), at the place (support), or says nothing. Evidence only; no verdict beyond the three statuses.

Input:
```json
{"type":"object","required":["story","person_id","window"],"additionalProperties":false,
 "properties":{"story":{"type":"string"},"person_id":{"type":"string"},
  "window":{"$ref":"#/$defs/Interval"},
  "claimed_place_id":{"type":"string","description":"place the person claims to have been at, optional"}}}
```
Output:
```json
{"type":"object","required":["status","evidence"],
 "properties":{"status":{"enum":["supported","contradicted","unknown","insufficient_evidence"]},
  "evidence":{"type":"array","items":{"type":"object","required":["kind","event_id","anchors"],
    "properties":{"kind":{"enum":["places_person_at_claimed","places_person_elsewhere","claim_by_person","claim_by_other"]},
      "event_id":{"type":"string"},"place_id":{"type":["string","null"]},"speaker_id":{"type":["string","null"]},
      "overlap":{"$ref":"#/$defs/Interval"},"anchors":{"type":"array","minItems":1,"items":{"$ref":"#/$defs/Anchor"}}}}},
  "notes":{"type":"array","items":{"type":"string"}},
  "provenance":{"enum":["derived","conditional"]},"explanation":{"$ref":"#/$defs/Explanation"}}}
```
`explanation` is present when `status` is `supported` or `contradicted` (R1); for `unknown` and `insufficient_evidence` it may be omitted. Semantics (proposal; the rule itself is R1 in the rules module, this text only describes it): `contradicted` if some dated event with the person as participant overlaps the window at a place different from `claimed_place_id` with confidence `high`; `supported` if the overlap is at the claimed place; `unknown` if only low-confidence or claim-only (speaker-asserted, i.e. unverified) evidence; `insufficient_evidence` if the person has no dated events. A `Claim` is evidence of what was asserted, not of what happened; `claim_by_*` kinds exist so the LLM can say "X said so" rather than "so it was".

### 3.3 `find_overlaps`

Description: find pairs of events (or persons' presences) that overlap in time, optionally at the same place.

Input:
```json
{"type":"object","required":["story"],"additionalProperties":false,
 "properties":{"story":{"type":"string"},"person_ids":{"type":"array","items":{"type":"string"},"minItems":1,"maxItems":10},
  "same_place_only":{"type":"boolean","default":true},
  "window":{"$ref":"#/$defs/Interval"},"limit":{"type":"integer","minimum":1,"maximum":100,"default":25}}}
```
Output:
```json
{"type":"object","required":["status","overlaps"],
 "properties":{"status":{"enum":["ok","insufficient_evidence"]},
  "overlaps":{"type":"array","items":{"type":"object","required":["a","b","overlap","anchors"],
    "properties":{"a":{"type":"string","description":"event_id"},"b":{"type":"string"},
      "overlap":{"$ref":"#/$defs/Interval"},"place_id":{"type":["string","null"]},
      "shared_person_ids":{"type":"array","items":{"type":"string"}},
      "anchors":{"type":"array","minItems":2,"items":{"$ref":"#/$defs/Anchor"}}}}},
  "truncated":{"type":"boolean"}}}
```
Each overlap item also carries `provenance` and `explanation` (rule R1). 

### 3.3a `find_contradictions` (planned)

Description: run R1, R2 and R3 on a story (optionally one person) and list violations. Input: `{story, person_id?, rules?: ("R1"|"R2"|"R3")[], limit?}`. Output: `{status: "ok"|"insufficient_evidence", findings: [{rule, provenance, explanation, anchors}], truncated}`. An empty `findings` with `status: "ok"` means the rules found none on the facts available, not that the story is consistent.

### 3.4 Entity lookup helper (needed to get ids)

`resolve_entity` {story, name, type?} -> {candidates:[{id, kind, name, aliases, score}]}. Included because the tools above take ids; the agent resolves names first. **[P]** may instead be done inside the agent via `GraphStore`; decide when the graph engine ADR is resolved.

## 4. Server `evidence-notes` (own, optional)

Optional; build only if time remains after `timeline-alibi`. Persists investigator notes tied to anchors (table `notes`, data-schema.md section 4). This is the only own server that writes, and only to the `notes` table of a separate file, never to the index.

| Tool | Input | Output |
|---|---|---|
| `add_note` | `{text: string (1..2000), anchors: Anchor[] (>=1), tags?: string[]}` | `{note_id, created_at}` |
| `list_notes` | `{tag?: string, chunk_id?: string, limit?: int<=100}` | `{notes:[{note_id,text,anchors,tags,created_at}]}` |
| `delete_note` | `{note_id}` | `{deleted: bool}` (only notes created by this server; no bulk delete) |

Note text is user data and corpus quotes are data: neither is ever executed or interpreted as instructions by the agent.

## 5. Error model (all own servers)

Domain failures are returned as a normal tool result with `status` (e.g. `insufficient_evidence`). Protocol/validation/runtime failures use one error object; the client wrapper maps SDK-level failures to it **[U: SDK error surface, see section 1]**:

```json
{"error": {"code": "invalid_input | not_found | ambiguous | insufficient_evidence | timeout | store_unavailable | internal",
  "message": "human-readable, no stack traces, no file paths outside the allowlist",
  "retriable": false, "details": {}}}
```

| code | When | retriable |
|---|---|---|
| `invalid_input` | schema violation, bad interval (`start_min > end_min`) | no |
| `not_found` | unknown story/person/place/event id | no |
| `ambiguous` | name resolves to several ids (details lists candidates) | no |
| `insufficient_evidence` | only used where a tool cannot return a status (kept for symmetry) | no |
| `timeout` | exceeded per-call limit (client-enforced and server-side deadline) | yes, once |
| `store_unavailable` | index file missing/locked | yes |
| `internal` | bug | no |

Agent behaviour: a failed tool call produces a `tool.result` trace event with `ok:false`; the agent proceeds without that evidence and, if the question depended on it, refuses with code `tool_error` (never fabricates a result). Server crash: client restarts the child at most once per run.

## 6. Timeouts and limits (all **[P]**, measure then fix)

| Item | Value |
|---|---|
| per-call default / hard cap (own servers) | 5 s / 15 s |
| server start (spawn + `list_tools`) | 10 s |
| response size cap | 64 KB serialized; beyond that `truncated: true` |
| calls per run | 6 (agent loop guard) |

## 7. Off-the-shelf servers and allowlisting

Goal: integrate one off-the-shelf server (filesystem or fetch) with an explicit allowlist, owned by the agent's MCP client config (`src/detective_board/mcp/`), not by the model.

Design (the allowlist is enforced in two places, so a server misconfiguration alone does not open access):

1. Server-side restriction, set at spawn time by our config: the filesystem server is started with only the allowed directories as arguments. **[U]** exact package name and CLI (the reference `@modelcontextprotocol/server-filesystem` takes allowed dirs as positional args; not fetched here). Allowed: `data/clean/`, `data/raw/` (read-only use), `docs/` if needed. Not allowed: repo root, `.env*`, `~`, `.claude/`, `scripts/`, any secrets path.
2. Client-side gate in our MCP client wrapper, before sending `call_tool`:
   - tool-name allowlist (read-only tools only: e.g. read/list/search; write/move/edit tools are never exposed to the model **[U]** actual tool names to be read from `list_tools`);
   - path argument is `resolve()`d (symlinks followed) and must be inside an allowed root, otherwise the call is rejected with `invalid_input` and a `tool.result ok:false` trace event;
   - response size cap as in section 6.
3. `fetch` (optional, **[P]**): disabled by default because the product is offline. If enabled for a demo, host allowlist in config (e.g. `www.gutenberg.org` only), checked client-side on the `url` argument before the call. **[U]** package (`mcp-server-fetch`) and whether it has its own host restrictions: not verified.
4. Env: stdio children get a minimal env (SDK behaviour per db-research.md); we add nothing secret via `env=`.
5. Content returned by any server is data, never instructions: it enters the prompt only inside delimited evidence blocks and is subject to the same self-check as corpus text.

Test plan (for mcp-engineer, not run here): for each rules-backed tool, assert the tool output equals the direct rules-module output on the same mini graph (AC-25); spawn each server through `Client(StdioServerParameters(...))`; assert a path outside the allowlist, a `..` traversal and a symlink escape are all rejected by the client gate; assert a write tool is not listed to the model.
