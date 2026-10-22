# ADR-0004: Symbolic layer (deterministic rules over the extracted graph)

- Status: Proposed
- Date: 2026-10-22
- Deciders: tech-lead, graph-engineer
- Provisional parts: effort estimates are judgement, not measured. Ladybug query behaviour on our schema is unverified (docs only, nothing installed or run). pyDatalog 0.22.x maturity is unverified (nothing installed). Which graph engine holds the data is still open (ADR-0002).

## Context

Product decision: the system is neuro-symbolic. The LLM extracts knowledge from text (probabilistic, errors possible), the graph stores it, and rules draw deterministic, checkable conclusions with an explanation (facts, edges, source quotes). Spec of the layer: `docs/symbolic-layer.md`. Minimum rules: R1 one person cannot be at two different places in overlapping time; R2 before/after is transitive and acyclic; R3 a witness claim incompatible with an established fact is a contradiction.

Constraints: Python 3.12.3, CPU-only, local, a benchmark-sensitive machine, 2-3 days of effort, graph size per story is tens to a few hundred events (20 stories, 596 chunks). The storage engine is not final (ADR-0002: Ladybug vs networkx+SQLite, SQLite `g_node`/`g_edge` is the schema of record). `timeline-alibi` (ADR-0003) is a stdio server that must be deterministic and never call an LLM; the agent needs the same logic.

Facts checked from official pages (WebFetch, 2026-10-22; nothing was installed):

- pyDatalog 0.22.4 (PyPI, released 2026-06-13): LGPL (classifier; `license` field empty), `requires_python >=3.8`, one maintainer (pcarbonn), cp312 manylinux x86_64 wheel 3.0 MB (pure-Python wheel 0.56 MB), no hard dependencies (SQLAlchemy/pymongo are extras). PyPI text: "I have restarted support of this package in June 2026"; the previous visible release was 0.17.3 (2022-11-26), and 0.21.0 to 0.22.4 were uploaded within four days in June 2026. Docs show recursion, stratified negation as failure and arithmetic comparison literals in rule bodies; the docs page makes no statement on Python 3.12 or on maintenance. Python 3.12 is covered only by the existence of cp312 wheels. Proof/explanation tracing is not documented.
- clingo 5.8.2 (PyPI, 2026-08-14): MIT, `requires_python >=3.6`, cp312 manylinux x86_64 wheel 2.26 MB, depends on `cffi`. Answer-set solver: integrity constraints are natural, but explanations (why a model is rejected) are not built in.
- Ladybug (docs.ladybugdb.com, Match clause): variable-length patterns `-[:Label*min..max]->`; default `WALK` (nodes/relationships may repeat), `TRAIL`, `ACYCLIC` modifiers; `SHORTEST` / `ALL SHORTEST`; predicates on relationship properties inside the pattern (`(r, n | WHERE ...)`, but no predicate mixing node and relationship); max hops default 30. Python: `lb.Database(":memory:")` is documented; a read-only open flag is **not** documented on the fetched page.
- Ladybug availability of the engine itself is not settled (ADR-0002).

## Options

Scoring: 5 = best. Effort = author's estimate for R1-R3 with explanations and tests.

| Criterion | (a) Plain Python rules over an in-memory fact view | (b1) pyDatalog | (b2) clingo (ASP) | (b3) hand-rolled mini Datalog | (c) Queries inside Ladybug (Cypher) |
|---|---|---|---|---|---|
| Determinism | 5: pure functions, sorted iteration | 4: deterministic semantics; evaluation order/tabling internals not ours | 3: stable models may be several; need optimisation or `--models 1` discipline and a fixed seed/config | 5 if written carefully | 4: deterministic results, but row order only with ORDER BY; engine upgrades may change plans |
| Explainability (facts, edges, quotes) | 5: the rule code builds the `Explanation` itself | 2: answers only; proof tree must be rebuilt by us (undocumented) | 2: explanations need meta-encoding, hard to map to quotes | 4: provenance is a design goal of the engine, but we write it | 3: `RETURN` of path nodes/rels is possible; time arithmetic, aliases and confidence propagation end up in Python anyway |
| Testability (mini-graph unit tests) | 5: plain `pytest`, no engine | 4 | 3 | 4 | 3: needs a DB instance per test, tests depend on engine |
| Install size / deps | 5: 0 | 4: 3 MB wheel, LGPL (import-only use, review needed) | 4: 2.3 MB + cffi, MIT | 5: 0 | 5 if Ladybug is chosen anyway; 0 value if networkx fallback wins |
| Effort 2-3 days | 5: about 2 days | 3: about 3 days, most of it spent on explanations and data loading into the global KB | 2: more than 3 days (new paradigm, time encoding, explanations) | 3: about 3 days (engine + rules + provenance) | 3: about 2-3 days, plus Ladybug DDL and the R3 logic still in Python |
| Risk | Low. Risk is that rule count grows and code becomes ad hoc | Medium: single maintainer, revival in June 2026, LGPL, global state **[U]**, no explanation support | Medium: skills/learning curve, mismatch with "quote every fact" requirement | Medium: bugs in our own engine | High: depends on ADR-0002 (engine and read-only mode unverified), duplicates logic if networkx fallback is picked; WALK semantics need care for cycle detection |

Notes:

- (c) can detect R2 cycles with `MATCH (a)-[:BEFORE*1..30]->(a)` per the documented syntax, but this was not run, and `time_norm` relative resolution, alias canonicalisation, three-valued logic and the `conditional` propagation (`docs/symbolic-layer.md` section 3) are not expressible in a pattern. It remains useful as an optional candidate-selection accelerator, not as the rule engine.
- (b1)/(b2) express R2 (recursion) elegantly but R1 and R3 are arithmetic and alias reasoning with three outcomes (`unknown` is the common case), where Datalog's closed-world negation is the wrong default.
- A Datalog backend can be added later behind the same interface, because the fact view is already normalised (spec section 7).

## Decision

Choose (a): rules are plain, pure Python functions over an immutable in-memory `FactBase` loaded from the graph store (`GraphStore` adapter; SQLite `g_node`/`g_edge` is the source, so the layer is independent of the Ladybug/networkx decision). Each rule is a registered `Rule` with an id and a version, returns `Finding` objects carrying a three-valued verdict and an `Explanation` (facts, edges, quotes, extracted dependencies). The only code the agent and the `timeline-alibi` MCP server import for rule logic is `detective_board.symbolic` (single source of truth; spec section 8). No LLM, no network, no ontology language, no new runtime dependency (`networkx` is optional and not required: closure and cycle search are about 40 lines on a few hundred nodes).

Why: zero install, the highest determinism and explainability (the rule builds the explanation from the facts it read), trivially unit-testable with hand-built graphs, independent of the storage decision, and it fits 2 days. It meets the product decision (rules are deterministic and verifiable) without a rule language the team would have to learn.

What would reverse it: more than about 8 rules, or a requirement for user-authored rules at runtime, or rules needing joins/recursion beyond transitive closure, would justify moving the same `FactBase` to Datalog (b3 first, because it keeps provenance under our control; b1 only after a check of its explanation support and licence). A measured precision problem on the gold alibi/contradiction cases caused by rule logic (not by extraction) would be handled inside (a).

## Consequences

- Positive: no new dependency; every conclusion is reproducible from a graph snapshot digest plus rule versions; MCP tools and the agent cannot diverge.
- Negative: rules are code, not data; adding a rule means a Python function and tests. Explanations are hand-written per rule (a shared `Explanation` builder limits this).
- Limitation stated plainly (also in the spec): the layer is exactly as reliable as the extracted facts. Extraction errors pass into the layer; the layer cannot detect a hallucinated but grounded quote. Mitigation is the `conditional` flag and the `depends_on_extracted` list, not correctness.
- Follow-up: requests to other zones (spec section 9): `time_norm` interval fields, structured `Claim` proposition, place gazetteer. Re-check after Phase 1 measurements decide ADR-0002.
- `docs/adr/README.md` gets one row; no other ADR is changed.
