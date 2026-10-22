# Phase 0 desk research: stores, graph DB, BM25, rerankers, MCP

Date: 2026-10-22. Method: desk research only (PyPI JSON API, HF API, official docs/READMEs). Nothing was installed or run. Target: Python 3.12.3, Linux x86_64, CPU-only, offline, embedded.
"Size" = largest manylinux x86_64 cp312/abi3 wheel on PyPI (download size, not installed size, transitive deps not counted). "Unverified" = not confirmed in a fetched source.
Local facts: system SQLite 3.45.1 has FTS5 and `enable_load_extension` available (checked with `python3 -c`).

## 1. Vector stores

| Package (PyPI) | Latest (date) | License | Wheel | Direct deps | Local persistence API (from docs) | Risks |
|---|---|---|---|---|---|---|
| `lancedb` | 0.40.0 (2026-10-07) | Apache-2.0 | 71 MB | pyarrow>=16, pydantic, numpy, lance-namespace, tqdm... | `db.create_table(name, schema=LanceModel)`, `table.add`, `table.search(..., query_type="hybrid").rerank(RRFReranker()).where(..).limit(k)`, `table.create_fts_index("text")` | Heaviest install (pyarrow); fast release cadence (0.x, API churn); hybrid page does not say native vs tantivy FTS (unverified). |
| `chromadb` | 1.5.9 (2026-05-05) | Apache-2.0 | 22 MB | 31 requirements | `collection.add(ids, documents)`, `collection.query(query_texts, n_results)`; PersistentClient (page for it not reachable, unverified) | Large transitive tree; default embedding function download behavior and telemetry opt-out not confirmed (unverified); we supply our own embeddings anyway. |
| `sqlite-vec` | 0.1.9 (2026-03-31) | MIT / Apache-2.0 dual | ~160 KB | none | SQL: `CREATE VIRTUAL TABLE v USING vec0(emb float[N])`, KNN via `WHERE emb MATCH ? ... ORDER BY distance LIMIT k`. Python helper names (`sqlite_vec.load`, `serialize_float32`) NOT confirmed on fetched page (unverified, check py docs before use). | README: "pre-v1, expect breaking changes"; 163 open issues; needs `enable_load_extension` (present here); brute-force vs ANN status not confirmed. Fine for a corpus of tens of thousands of chunks. |
| `qdrant-client` (local mode) | 1.20.0 (2026-10-22) | Apache-2.0 | 460 KB (pure Python) | 14 reqs | `QdrantClient(path="dir")` or `":memory:"`, `query_points(...)` | README positions local mode as dev/test/CI, "switch to server mode to scale"; hybrid in local mode not documented there (unverified). |

Sources: https://pypi.org/pypi/lancedb/json , https://docs.lancedb.com/search/hybrid-search , https://pypi.org/pypi/chromadb/json , https://docs.trychroma.com/docs/overview/getting-started , https://github.com/asg017/sqlite-vec , https://pypi.org/pypi/sqlite-vec/json , https://github.com/qdrant/qdrant-client

## 2. Graph databases

Kuzu status (important): the `kuzudb/kuzu` repo was **archived by the owner on Oct 10, 2025** (read-only). README: Kuzu "is working on something new"; past releases remain usable. License MIT. Last PyPI release `kuzu` 0.11.3 (2025-10-10, 7 MB wheel, no deps). No further fixes will come from upstream. Source: https://github.com/kuzudb/kuzu , https://pypi.org/pypi/kuzu/json

**Successor: Ladybug** ("formerly known as Kuzu" per its README), org LadybugDB, MIT, `pip install ladybug` 0.21.2 (2026-10-01; 0.22.0.dev nightlies up to 2026-10-17), 9 MB wheel, Python <3.15, active (6.7k commits, 1.9k stars, 117 open issues at fetch). Python: `import ladybug as lb; db = lb.Database("x.lbdb"); conn = lb.Connection(db); conn.execute("CREATE NODE TABLE ...")`, results via `get_all()`, `rows_as_dict()`, `get_as_df()`, iteration; `AsyncConnection` exists. Cypher DDL/COPY as in Kuzu. Native FTS and vector index claimed. Sources: https://github.com/LadybugDB/ladybug , https://docs.ladybugdb.com/client-apis/python/ , https://docs.ladybugdb.com/get-started/

| Option | Package / version | License | Wheel | Query language / API | Risks |
|---|---|---|---|---|---|
| Ladybug (Kuzu fork) | `ladybug` 0.21.2 | MIT | 9 MB | Cypher; Python API above | Young project/rename, 0.x versions, single org; Kuzu-API/on-disk-format compat NOT confirmed (migrate page not read); recursive path syntax not verified from docs (inherited from Kuzu, unverified). |
| Kuzu (frozen) | `kuzu` 0.11.3 | MIT | 7 MB | Cypher | Archived, no fixes; but stable, pinned, offline OK. Extensions (FTS/vector) were downloaded from a server: README says use 0.11.3 which bundles many, or a local extension server. |
| FalkorDBLite | `falkordblite` 0.11.0 (2026-10-19) | Python wrapper BSD; bundled FalkorDB server is **SSPLv1** | 35 MB (needs glibc >= 2.38; Ubuntu 24.04 ok) | Cypher via `from redislite.falkordb_client import FalkorDB; g = FalkorDB(path).select_graph("g"); g.query(...)`; runs an embedded Redis process | Beta (README classifier "4 - Beta"), one maintainer, spawns a server process (RAM/ports), SSPL on the engine (legal not assessed). |
| networkx + SQLite | `networkx` 3.7 (BSD-3, ~2 MB, Python>=3.12) + stdlib sqlite3 | BSD / public domain | 0 extra | Python graph algos (shortest path, BFS, ego graph); edges/claims/source anchors in SQLite tables | No Cypher; temporal/claim queries hand-written as SQL; fully in-memory graph when loaded (fine for Holmes corpus size, unmeasured). Zero maintenance risk. |
| DuckDB + DuckPGQ | `duckdb` 2.0.0 (2026-10-21, MIT, 23 MB) + community ext `duckpgq` | MIT (ext licence unverified) | 23 MB | SQL/PGQ: `CREATE PROPERTY GRAPH`, `FROM GRAPH_TABLE (g MATCH (a)-[k]->(b) COLUMNS (...))`, `ANY SHORTEST` | Extension is a CWI research project, installs via `INSTALL duckpgq FROM community` (needs network once, not offline-friendly); compat with duckdb 2.0.0 not confirmed (matrix blank). |

Sources: https://pypi.org/pypi/falkordblite/ , https://github.com/FalkorDB/falkordblite , https://github.com/FalkorDB/FalkorDB (SSPLv1) , https://duckdb.org/community_extensions/extensions/duckpgq.html , https://pypi.org/pypi/networkx/json

## 3. BM25

| Option | Version | License | Size | API | Notes |
|---|---|---|---|---|---|
| `bm25s` | 0.3.14 (2026-10-18) | MIT | 79 KB, numpy core (extras: PyStemmer, numba) | `bm25s.tokenize(corpus, stopwords="en")`, `r = bm25s.BM25(); r.index(tok)`, `r.retrieve(qtok, k=k)`, `r.save(dir)`, `BM25.load(dir, mmap=True)` | README claims large speedup over rank_bm25 (its own benchmark). In-memory sparse index, saved to disk. |
| `rank-bm25` | 0.2.2 (2022-02-16) | Apache-2.0 | 8 KB | pure Python/numpy | Unmaintained since 2022; slow per README comparison. Not recommended. |
| SQLite FTS5 | SQLite 3.45.1 (system) | public domain | 0 | `CREATE VIRTUAL TABLE t USING fts5(text, tokenize='porter unicode61')`; `WHERE t MATCH ? ORDER BY bm25(t)` (scores negative, lower = better; k1=1.2, b=0.75 hard-coded); phrase/NEAR/prefix queries | No extra dependency, same file as vectors, supports phrase and NEAR (useful for quoted-evidence lookup). Params not tunable. Query strings need escaping. |

Sources: https://github.com/xhluca/bm25s , https://pypi.org/pypi/bm25s/json , https://www.sqlite.org/fts5.html

## 4. Rerankers (CPU)

Sizes from HF API (https://huggingface.co/api/models/<id>). All Apache-2.0 except bge-reranker-base (MIT).

| Model | Params / file size | ONNX available | Language | Note |
|---|---|---|---|---|
| `BAAI/bge-reranker-v2-m3` | ~0.6B, 2.2 GB safetensors (F32) | none in repo (would need export) | multilingual | Best quality candidate, heavy for CPU/RAM; use as offline upper bound only. |
| `BAAI/bge-reranker-base` | 1.06 GB | yes fp32 1.06 GB | zh/en | Still heavy. |
| `cross-encoder/ms-marco-MiniLM-L6-v2` | 86 MB | yes, incl. qint8/avx2/avx512 22 MB | English | Recommended default; ships ready quantized ONNX. |
| `cross-encoder/ms-marco-MiniLM-L12-v2` | 127 MB | yes, int8 32 MB | English | Step up in quality, 2x cost. |
| `mixedbread-ai/mxbai-rerank-xsmall-v1` | 135 MB | quantized 83 MB | English | Alternative. |
| `jinaai/jina-reranker-v1-tiny-en` | 63 MB | int8 31 MB | English | Smallest; card licence per HF API apache-2.0. |

Runtime: `sentence-transformers` 6.2.0 (Apache-2.0). `CrossEncoder(model, backend="onnx")` after `pip install sentence-transformers[onnx]`; `model_kwargs={"file_name": "onnx/model_qint8_avx2.onnx"}` selects a quantized file; `model.predict([(q, passage), ...])` (doc: https://www.sbert.net/docs/cross_encoder/usage/efficiency.html). Caveat: sentence-transformers pulls torch (large, RAM). Lighter path: `onnxruntime` 1.31.0 (MIT, 23 MB) + `tokenizers` directly, or `flashrank` 0.2.10 (Apache-2.0, 18 KB, downloads its own models; not verified here). bge-reranker-v2-m3 via `FlagEmbedding.FlagReranker(...).compute_score` also documented on its card. Latency/RAM for each: NOT measured, must be benchmarked in Phase 1 after the other benchmark finishes.

## 5. Python MCP SDK

- Package `mcp`, latest **2.3.0** (2026-10-02), MIT, Python >=3.10. v1 line last seen pinned as `mcp==1.28.1`. Migration doc says "keep a `<2` upper bound until you've migrated". Deps: anyio, httpx2, pydantic>=2.12, starlette, uvicorn, sse-starlette, jsonschema, pyjwt, opentelemetry-api, mcp-types==2.3.0 (+ `[cli]` extra: typer, python-dotenv). Source: https://pypi.org/pypi/mcp/json , https://github.com/modelcontextprotocol/python-sdk , https://py.sdk.modelcontextprotocol.io/migration/
- **Breaking in v2**: `FastMCP` renamed `MCPServer`; import `from mcp.server.mcpserver import MCPServer, Context` (v1 path `mcp.server.fastmcp` raises ModuleNotFoundError). Most v1 tutorials online are stale. `fastmcp` on PyPI (4.1.3, Apache-2.0) is a separate project; not evaluated.
- Server (from README):
  ```python
  from mcp.server import MCPServer
  mcp = MCPServer("Demo")
  @mcp.tool()
  def add(a: int, b: int) -> int: ...
  if __name__ == "__main__":
      mcp.run()          # default transport stdio; "streamable-http" via run(transport=...)
  ```
  Inspector: `uv run mcp dev server.py` (needs `mcp[cli]`).
- Client (from docs_src/client_transports/tutorial004.py):
  ```python
  from mcp import Client, StdioServerParameters
  server = StdioServerParameters(command="uv", args=["run", "server.py"], env={...})
  async with Client(server) as client:
      tools = await client.list_tools()
      result = await client.call_tool("add", {"a": 1, "b": 2})   # result.structured_content
  ```
  The stdio child gets only a minimal env allow-list (HOME, PATH, ...); pass anything else via `env=`. `Client("http://host/mcp")` = Streamable HTTP. Docs: https://py.sdk.modelcontextprotocol.io/client/transports/ (raw: https://raw.githubusercontent.com/modelcontextprotocol/python-sdk/main/docs/client/transports.md). Hook for stdout: a stdio server must not print to stdout.

## 6. Recommendation

1. **Retrieval store: one SQLite file with FTS5 (BM25) + sqlite-vec (vectors), fusion (RRF) in Python.** Reasons: zero heavy deps (sqlite-vec ~160 KB, FTS5 already in system SQLite), tiny RAM, single artifact, phrase/NEAR for evidence quotes, trivially offline. Risk: sqlite-vec is pre-v1, so pin `==0.1.9` and wrap behind a `VectorStore` interface. **Fallback: LanceDB 0.40.0** (built-in hybrid + rerank hooks, scales better) if sqlite-vec recall/latency fails the eval gate; cost is ~70 MB wheel + pyarrow. Skip Chroma (heavy tree, nothing we need) and Qdrant local (documented as dev/test mode).
2. **BM25:** FTS5 as primary; `bm25s` 0.3.14 as comparison arm in the eval (tunable k1/b, stemming). Drop `rank-bm25` (unmaintained since 2022).
3. **Graph DB: do not pick Kuzu as the long-term choice; the agent definition calling it "candidate" must be updated by an ADR.** Upstream archived 2025-10-10. Preferred: **Ladybug (`ladybug` 0.21.2, MIT)** behind a thin `GraphStore` adapter, since it is the active continuation with Cypher; Phase 1 must verify (a) clean install size/RAM, (b) schema + variable-length path queries, (c) behavior with a pinned version. Fallback / equally valid for a small Holmes graph: **networkx 3.7 + SQLite** tables (no engine risk, no Cypher). `kuzu==0.11.3` frozen is the third option. Reject FalkorDBLite (SSPL engine, Redis subprocess, beta) and DuckPGQ (research extension, online install, 2.0.0 compat unconfirmed).
4. **Reranker:** `cross-encoder/ms-marco-MiniLM-L6-v2` quantized ONNX (22 MB) as default; evaluate L12 and `bge-reranker-v2-m3` (2.2 GB, likely too heavy) only as quality ceiling on the eval set. Prefer plain `onnxruntime`+`tokenizers` over sentence-transformers if we want to avoid torch in the runtime; decide after measuring.
5. **MCP:** `mcp>=2.3,<3` (pin exact), use `MCPServer` + stdio and `Client(StdioServerParameters(...))` for tests; do not copy v1 `FastMCP` snippets.

## 7. Open items for Phase 1 (not verified here)

- Ladybug: Kuzu on-disk/API compat, recursive path syntax, install footprint, import name confirmed as `ladybug` only from the get-started page.
- sqlite-vec Python helper API and ANN/brute-force behavior; metadata filtering.
- LanceDB FTS implementation (native vs tantivy).
- Measured RAM/latency for rerankers and stores (deferred because another benchmark is running).
- Chroma PersistentClient/telemetry, Qdrant local hybrid: not verified, low priority since not recommended.
- No docs/PRD.md exists in the repo; ADRs in docs/adr were not read for consistency with this doc.
