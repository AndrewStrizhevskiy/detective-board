# Data schema

Status: DRAFT, Phase 0. Sources: `data/chunks.jsonl` (real, 596 lines), `src/detective_board/extract/schema.py` (`SCHEMA_VERSION = "1"`, real), `docs/spike/db-research.md`. Everything about SQLite DDL, the graph layout and trace events is a **proposal**; nothing was executed. Marks: **[P]** provisional (ADR-0002 Proposed, pending measurement), **[U]** unverified API/behaviour.

## 1. Chunk record (exists)

One JSON object per line in `data/chunks.jsonl`, produced by `scripts/corpus/ingest.py`.

| Field | Type | Meaning |
|---|---|---|
| `chunk_id` | str | `<story>-<NNNN>`, e.g. `scandal-in-bohemia-0000`; primary key everywhere |
| `story` | str | slug, matches `data/clean/<story>.txt` |
| `section` | str | roman numeral / section label inside the story |
| `para_start`, `para_end` | int | paragraph index range (inclusive) |
| `char_start`, `char_end` | int | offsets into `data/clean/<story>.txt` (half-open `[start, end)` assumed, **[U]** confirm in ingest.py) |
| `text` | str | chunk text (Gutenberg `_italic_` underscores kept) |

Offset convention used below: **absolute anchor** = `(story, char_start, char_end)` in the clean story text; **chunk-relative** offsets are relative to `text`. Absolute = `chunk.char_start + relative` holds only if chunk text is a contiguous slice of the clean text; unwrapping may break this **[U]**, so the pipeline must verify `clean[char_start:char_end] == text` and fall back to relative-only anchors if not.

## 2. Retrieval tables (SQLite + FTS5 + sqlite-vec) [P]

Single file, e.g. `data/index/db.sqlite`. Extension loading is available locally (SQLite 3.45.1, FTS5 present, per db-research.md).

```sql
CREATE TABLE chunks (
  chunk_id   TEXT PRIMARY KEY,
  rowid_int  INTEGER UNIQUE NOT NULL,      -- integer key shared with FTS5 / vec0 rowid
  story      TEXT NOT NULL,
  section    TEXT NOT NULL,
  para_start INTEGER NOT NULL,
  para_end   INTEGER NOT NULL,
  char_start INTEGER NOT NULL,
  char_end   INTEGER NOT NULL,
  text       TEXT NOT NULL
);
CREATE INDEX chunks_story ON chunks(story, char_start);

-- BM25. External-content FTS5 over chunks.text.
CREATE VIRTUAL TABLE chunks_fts USING fts5(
  text, content='chunks', content_rowid='rowid_int',
  tokenize='porter unicode61'
);
-- query: SELECT rowid, bm25(chunks_fts) FROM chunks_fts WHERE chunks_fts MATCH ? ORDER BY bm25(chunks_fts) LIMIT ?;
-- scores are negative, lower = better; k1=1.2, b=0.75 fixed (db-research.md, sqlite.org/fts5).
-- user input must be escaped/quoted before MATCH.

-- Vectors. N and distance metric come from the embedding choice (pending spike).
CREATE VIRTUAL TABLE chunk_vec USING vec0(embedding float[N]);
-- KNN: SELECT rowid, distance FROM chunk_vec WHERE embedding MATCH ? ORDER BY distance LIMIT ?;
-- Python helper names (sqlite_vec.load, serialize_float32) NOT confirmed [U]; pin sqlite-vec==0.1.9.
-- rowid of chunk_vec = chunks.rowid_int.

CREATE TABLE index_manifest (
  key TEXT PRIMARY KEY, value TEXT NOT NULL   -- schema_version, extractor_version, embed_model, embed_dim, built_at, lib versions
);
```

Fusion: RRF done in Python over the two ranked lists (db-research.md recommendation). Both stores sit behind `VectorStore` / `Bm25Store` interfaces so LanceDB (fallback) or `bm25s` (comparison arm) can replace them. Unknown: whether sqlite-vec offers metadata filtering by `story` **[U]**; fallback is post-filtering.

## 2b. Sentence index (separate file `data/index/sentences.sqlite`)

Same chunks, one row per sentence; built by `python -m detective_board.index.sentences` (`just sentences`), searched by `retrieval.sentences.sentence_search`. Splitter: `agent.window.sentence_spans`; units of fewer than 4 words are merged into the following sentence (the previous one at the end of a chunk), so nothing is dropped and `chunk.text[start:end] == text` always holds. The embedding is computed from the text with whitespace collapsed, no prefixes, same `bge-m3` identity (cosine, 1024) as the chunk index.
```sql
CREATE TABLE sent (
  id INTEGER PRIMARY KEY,                 -- 1..N in chunks.jsonl order, sentence order inside a chunk
  chunk_id TEXT NOT NULL, story TEXT NOT NULL,
  start INTEGER NOT NULL, end INTEGER NOT NULL,   -- offsets INSIDE the chunk text
  text TEXT NOT NULL);
CREATE INDEX sent_chunk ON sent(chunk_id, start);
CREATE VIRTUAL TABLE sent_fts USING fts5(text, content='sent', content_rowid='id', tokenize='porter unicode61');
CREATE VIRTUAL TABLE sent_vec USING vec0(embedding float[1024] distance_metric=cosine);  -- rowid = sent.id
CREATE TABLE sent_manifest (key TEXT PRIMARY KEY, value TEXT NOT NULL);
-- schema_version, splitter, min_words, embed_model/dim/doc_prefix/query_prefix/metric,
-- chunks_sha256 (of the chunk file), sentences, complete ('1' only when every sentence has a vector)
```
Rebuild is idempotent (a complete file for the same chunk file, splitter and embedding identity is not touched) and resumable (rows are written in one transaction, vectors per batch; a per-text embedding cache `data/cache/sentences-emb.sqlite` makes even a deleted file cheap to rebuild). A different embedding configuration is refused (`SentenceIndexError`); a changed chunk file or splitter rebuilds the rows. The API opens the file only when `complete = 1`.

## 3. Graph schema (derived from Extraction v1) [P]

The extraction schema is flat: entities (`person|place|item`), events, claims and relations reference entities **by name string**, each with a verbatim `quote`. The graph layer turns this into typed nodes and edges with source anchors. Engine is **[P]** (Ladybug vs networkx+SQLite); the logical schema below is engine-independent, and the SQLite tables in 3.4 are the authoritative fallback form.

### 3.1 Nodes

| Node | Key | Properties | From |
|---|---|---|---|
| `Person` | `id` (`p:<story>:<slug>`) | `name`, `aliases[]` | `Entity.type=person` |
| `Place` | `id` | `name`, `aliases[]` | `Entity.type=place` |
| `Item` | `id` | `name`, `aliases[]` | `Entity.type=item` |
| `Event` | `id` (`e:<chunk_id>:<n>`) | `description`, `time_text`, `time_norm` (see below), `place_id?` | `Event` |
| `Claim` | `id` (`c:<chunk_id>:<n>`) | `content`, `speaker_id`, `about_id?` | `Claim` |
| `Chunk` | `chunk_id` | `story`, `char_start`, `char_end` | chunks table |

Entity ids are scoped per story in v1 (the same "Watson" in two stories gets two nodes plus an optional `SAME_AS` edge); cross-story merge is deferred **[P]**.

`time_text` is kept exactly as written ("nine o'clock"). `time_norm` is an optional derived object produced by a post-processor, never by the extraction LLM: `{"story_day": int|null, "minute_of_day": int|null, "rel": "before|after|during|at|null", "ref_event_id": str|null, "confidence": "high|low"}`. Null whenever the text is vague ("late", "that evening" can map to a range, see `range_min`/`range_max` **[P]**). This is the input to `timeline-alibi`.

### 3.2 Edges

| Edge | From -> To | Properties |
|---|---|---|
| `PARTICIPATED_IN` | Person -> Event | anchor |
| `OCCURRED_AT` | Event -> Place | anchor |
| `ASSERTS` | Person(speaker) -> Claim | anchor |
| `ABOUT` | Claim -> Person/Place/Item | anchor |
| `RELATION` | Entity -> Entity | `predicate` (lowercase verb phrase, e.g. "son of"), anchor |
| `MENTIONED_IN` | Entity/Event/Claim -> Chunk | anchor |
| `SAME_AS` | Entity -> Entity | `method`, `score` (optional, cross-story) |

### 3.3 Source anchor (on every edge and on Event/Claim nodes)

```json
{
  "story": "scandal-in-bohemia",
  "chunk_id": "scandal-in-bohemia-0007",
  "char_start": 10234,
  "char_end": 10301,
  "rel_start": 112,
  "rel_end": 179,
  "quote": "verbatim text of the span"
}
```

Anchor resolution (pipeline step, not done by the LLM, since `schema.py` has no offsets): find `quote` in `chunk.text`; `rel_*` = match offsets; `char_*` = `chunk.char_start + rel_*` if the contiguity check passes (section 1). Rules: exact substring match first; if multiple matches, take the first and set `ambiguous=true`; if none, the item is **dropped** (grounding failure) and counted in the manifest. `quote == text[rel_start:rel_end]` is an invariant checked on write and by the self-check at answer time.

### 3.4 Fallback form: SQLite tables (networkx loaded from them)

```sql
CREATE TABLE g_node (
  id TEXT PRIMARY KEY, kind TEXT NOT NULL CHECK (kind IN ('person','place','item','event','claim')),
  story TEXT NOT NULL, name TEXT, props_json TEXT NOT NULL   -- aliases, description, time_text, time_norm, content, speaker_id...
);
CREATE TABLE g_edge (
  id INTEGER PRIMARY KEY, src TEXT NOT NULL REFERENCES g_node(id), dst TEXT NOT NULL REFERENCES g_node(id),
  rel TEXT NOT NULL, props_json TEXT,
  chunk_id TEXT NOT NULL REFERENCES chunks(chunk_id),
  char_start INTEGER, char_end INTEGER, rel_start INTEGER, rel_end INTEGER,
  quote TEXT NOT NULL, ambiguous INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX g_edge_src ON g_edge(src, rel);  CREATE INDEX g_edge_dst ON g_edge(dst, rel);
CREATE INDEX g_node_name ON g_node(story, name);
```

If Ladybug is chosen, the same fields become `CREATE NODE TABLE` / `CREATE REL TABLE` definitions in Cypher DDL; exact DDL syntax and variable-length path support are inherited from Kuzu and **[U]** (db-research.md section 7).

## 4. Other tables

```sql
CREATE TABLE extraction_cache (           -- idempotence + audit
  chunk_id TEXT NOT NULL, extractor_version TEXT NOT NULL, model TEXT NOT NULL,
  schema_version TEXT NOT NULL, raw_json TEXT NOT NULL, dropped INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (chunk_id, extractor_version)
);
CREATE TABLE notes (                      -- evidence-notes server (optional)
  note_id TEXT PRIMARY KEY, created_at TEXT NOT NULL, text TEXT NOT NULL, anchors_json TEXT NOT NULL, tags_json TEXT
);
CREATE TABLE trace_log (                  -- persisted trace events, for replay in UI
  run_id TEXT NOT NULL, seq INTEGER NOT NULL, ts TEXT NOT NULL, type TEXT NOT NULL, event_json TEXT NOT NULL,
  PRIMARY KEY (run_id, seq)
);
```

## 5. Trace event schema (API and UI)

Transport: server stream (SSE or WebSocket, **[P]**), one JSON object per event; same objects are stored in `trace_log` and returned in the final response under `trace[]`. JSON Schema draft 2020-12 (informal; to be turned into pydantic models + generated TS types).

Envelope (all events):

```json
{
  "run_id": "string, uuid4",
  "seq": 0,
  "ts": "RFC 3339 UTC with ms",
  "type": "run.start | route | retrieve.vector | retrieve.graph | tool.call | tool.result | enrich | llm.call | llm.result | selfcheck | answer | refusal | error | run.end",
  "step_id": "string, groups start/end pairs",
  "parent_id": "string|null",
  "duration_ms": "integer|null (set on result/end events)",
  "payload": {}
}
```

Payloads by `type`:

| type | payload |
|---|---|
| `run.start` | `{question, session_id, config_digest}` |
| `route` | `{routes: ["vector"\|"graph"\|"mcp"\|"refusal"...], method: "rules"\|"llm", reason: str, confidence: number\|null}` |
| `retrieve.vector` | `{query, k, bm25_hits:[{chunk_id,score,rank}], vec_hits:[{chunk_id,distance,rank}], fused:[{chunk_id,rrf,rank}], reranked:[{chunk_id,score}]\|null}` |
| `retrieve.graph` | `{query_kind, seeds:[node_id], nodes:[{id,kind,name}], edges:[{id,rel,src,dst,anchor}], truncated: bool}` |
| `tool.call` | `{server, tool, arguments, timeout_ms}` |
| `tool.result` | `{server, tool, ok: bool, result_summary, error: {code,message}\|null}` (full result stored, UI shows summary) |
| `enrich` | `{evidence:[{ref_id, chunk_id, char_start, char_end, source:"vector"\|"graph"\|"tool"}], graph_facts:int, tool_results:int, prompt_tokens_est:int}` |
| `llm.call` | `{model, role:"answer"\|"router"\|"judge", attempt:int, temperature, num_ctx}` |
| `llm.result` | `{prompt_tokens, completion_tokens, finish_reason}` (text not duplicated here) |
| `selfcheck` | `{ok: bool, quotes:[{ref_id, verbatim: bool, anchor_valid: bool}], unsupported_claims:[str], action:"accept"\|"retry"\|"refuse"}` |
| `answer` | `{text, citations:[{ref_id, quote, anchor}], used_routes:[str]}` |
| `refusal` | `{code: "out_of_scope"\|"no_evidence"\|"selfcheck_failed"\|"tool_error", message, missing:[str]}` |
| `error` | `{code, message, retriable: bool}` |
| `run.end` | `{status:"answered"\|"refused"\|"error", total_ms}` |

`anchor` is the object from section 3.3. Citations in `answer` must resolve to `chunks` rows; the UI highlights `[char_start, char_end)` in the story text. Event order within a run is strictly by `seq`; clients must tolerate unknown `type` values and unknown payload fields (forward compatibility). Version field: `X-Trace-Schema: 1` header / `schema_version` in the final response **[P]**.
