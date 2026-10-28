# Test plan

Owner: qa-lead. Tooling: pytest 9, pytest-cov, ruff, pyright (pinned in `pyproject.toml`, group `dev`).
Status 2026-10-22: Phase 0. Only spike scripts and `tests/test_ingest.py`, `tests/test_score_extraction.py` exist; everything below marked TODO is a plan, not a fact.

## 1. Test pyramid

| Layer | Share | What | Runs where | Speed |
|---|---|---|---|---|
| Unit | ~70% | chunking, ingest round-trip, schema validation (`extract/schema.py`), scoring, query planning, graph ops on tiny in-memory fixtures, prompt builders | CI, pre-push | <10 s total |
| Integration | ~20% | index build on a 3-5 chunk mini-corpus, retriever+graph+agent loop with mock LLM, MCP tool contracts (in-process) | CI | <60 s |
| Live | few | real Ollama + real models: structured-output smoke, one end-to-end question, memory/latency sanity | local only, `-m live` | minutes |
| E2E (UI) | handful | Playwright against the running app (only if a web UI ships; see 5) | CI nightly / local | slow |
| Eval | separate axis | answer/retrieval quality on `eval/` gold sets; a metric suite, not pass/fail unit tests | short in CI, full local | see 7 |

Rule: a bug found in a higher layer gets a regression test in the lowest layer that can reproduce it.

### 1.1 Rule tests (symbolic layer, planned, not written yet)

The rules R1-R3 (`src/detective_board/symbolic/`, `docs/symbolic-layer.md`) are the part of the product that claims exactness, so they get the strictest tests. Backlog T-37.

- Inputs are hand-built mini graphs (3-8 nodes) written in the test file or `tests/fixtures/symbolic/*.json`, each with the answer worked out by hand and a one-line comment saying why. No corpus text, no LLM, no `FakeLLM`, no network, no clock, no randomness.
- Required cases per rule. R1: clear overlap; disjoint; touching endpoints (end == start, decide and document whether this is an overlap); identical intervals; one interval inside another; unknown time (no finding, not an error); same place twice (no finding); different story days. R2: chain a<b<c implies a<c; 2-cycle; 3-cycle; self-order; duplicate edges; disconnected parts; empty graph; contradictory pair given as before and after. R3: claim equal to the fact; claim incompatible with the fact; claim about an unknown fact (no finding); fact itself low confidence (finding is `conditional`); two witnesses disagreeing.
- Each test asserts the finding, the rule id, the exact fact and edge ids in the explanation, the provenance label (`derived` / `conditional`) and that every explained input has an anchor.
- Determinism: each case runs twice in one test and the serialised results must be identical; iteration order of sets and dicts must not leak into output (sorted ids).
- Gate: **100% of rule tests green** and a branch-coverage floor on `symbolic/` higher than the global 80 (value fixed when the module lands). A red rule test blocks merge; no `skip`, no retry.
- MCP parity test: the `timeline-alibi` tool output equals the direct rules-module output on the same mini graph (AC-25).
- Contradiction detection quality on real text is not a unit test; it is a separate eval (T-39), reported apart from answer quality.

## 2. Deterministic LLM mock strategy

CI has no Ollama and no GPU/models; tests must be bit-reproducible.

- All LLM access goes through one narrow interface (`LLMClient.chat(messages, *, schema=None) -> str`), injected, never imported as a global. TODO: owner agent-engineer; qa-lead files the request in `docs/backlog.md`.
- `FakeLLM` (in `tests/fakes.py`) has three modes: (a) scripted: a queue of canned replies consumed in order, fails loudly on exhaustion or unexpected extra calls; (b) keyed: reply chosen by a hash of the normalized prompt, backed by a fixtures file `tests/fixtures/llm/*.json`; (c) recorded: fixtures captured once from a real run (`just test-live --record`, TODO) and replayed in CI.
- Mock replies for structured output must validate against the real pydantic/JSON schema, so schema drift breaks the test.
- Assert on the prompt too (contains evidence ids, no corpus text outside delimiters), not only on the output.
- No `time`, `random`, network, or wall-clock in unit tests: seed or inject. Embeddings in tests: a deterministic hash-based stub vector, never a real model.
- Corpus text is data, never instructions: include a prompt-injection fixture chunk ("ignore previous instructions...") and assert the agent output ignores it.

## 3. The `live` marker set

`live` = needs running Ollama (`localhost:11434`) and pulled models. Registered in `pyproject.toml` with `--strict-markers`. Excluded everywhere by `-m "not live"` (`just test`, CI). Run with `just test-live`.
Planned live tests (TODO): structured-output JSON validity per model; one question end-to-end with citations; tool-call round trip; model load/unload; RSS budget check (see 8).
Live tests must skip cleanly (not fail) when Ollama is down: a fixture does `pytest.skip` on connection error. Other markers: `e2e`, `slow`.

## 4. Coverage policy

- Gate: `--cov-fail-under=80` on `src/detective_board` (branch coverage), enforced in CI. 80 is a placeholder; revisit after the first real core modules land and set a per-package floor (core retrieval/graph/agent logic higher, glue lower).
- `scripts/` (spike, corpus) are outside the gate; anything promoted into `src/` comes under it.
- Coverage is a floor, not a goal: new code needs tests for behaviour and error paths; no tests that only execute lines.
- Ratchet: the threshold may be raised, never lowered, without a note in the PR.

## 5. E2E with Playwright

Applies only if a web UI exists (decision pending with frontend-engineer / product-owner). Verified against package indexes on 2026-10-22: `pytest-playwright` 0.10.0 on PyPI (depends on `playwright`; GitHub `microsoft/playwright-python` latest tag v1.64.0).
Install (not run here): `uv sync --group e2e && uv run playwright install chromium` (browser download, ~150 MB+; in CI add `--with-deps`). Run: `uv run pytest -m e2e`. Group `e2e` is declared in `pyproject.toml`, kept out of `dev` so default setup stays light.
Scope: ask a canned question against the app backed by `FakeLLM`, assert answer, citations panel, evidence graph render, error state when LLM is down. No live models in e2e.

## 6. Regression process

1. Every defect gets a failing test first (lowest sensible layer), then the fix; test name references the backlog id.
2. Eval regressions: any metric drop beyond tolerance (set per metric after the first baseline; placeholder: >2 pt absolute on retrieval hit@k, >3 pt on answer accuracy) blocks merge unless justified in the PR.
3. Baselines live in `eval/baselines/*.json` (TODO), updated only by an explicit commit with the reason.
4. Flaky test: quarantine within a day (`@pytest.mark.skip(reason=...)` + backlog item), never retry-until-green.
5. Spike results under `docs/spike/results/` are historical evidence; do not edit them. Runs invalidated by a bad setup are kept and renamed `_invalid_*`.

## 7. Eval in CI (shortened)

- Job `eval-short` in `.github/workflows/ci.yml` runs `eval/run_eval.py --short` (8 dev questions, FakeLLM, the fixture index, no network; deterministic, covered by `tests/eval/`).
- Short = fixed subset (~10-15 questions from `eval/spike_questions.jsonl` successors) with `FakeLLM`/recorded replies and a stub or small embedder: it tests the pipeline wiring and metric code, not model quality. Budget: <3 min.
- Full eval (real models, all questions, multiple seeds if sampling) runs locally via `just eval`; results committed under `docs/` or `eval/runs/` (ignored) with date, model tag, commit hash.
- Report numbers as they are; a red metric is reported, not hidden.

## 8. Known pitfalls from the spike (measurement validity)

- Ollama 0.35 runs each model in a `llama-server` child process. RSS must be sampled in that child (walk the process tree under the ollama server), not in the parent `ollama` PID. See `scripts/spike/_common.py` (`_ollama_pids`, `_rss_kib`) and `bench_rss.py`.
- Unload all other models before measuring (`keep_alive: 0` for everything in `/api/ps`, then wait until no runner process remains); otherwise RAM and latency are polluted. Runs measured without this are invalid (`docs/spike/results/_invalid_run*`).
- Thermal throttling: 7-8B models on CPU reached ~96 C and throttled; record temperature, discard or flag runs after sustained load, add cool-down between models, run repeats and report median, not best.
- Do not run benchmarks and the test suite at the same time (shared CPU/RAM skews both; also why CI-style checks wait while benches run).
- Cold vs warm: first call includes model load; separate load time from tokens/s.
- Quantization/tag must be recorded with every number (model tag + digest).
- Structured output: small models drift from schema; always validate and count invalid-JSON rate as a metric.

## 9. Risk-based priorities

0. Wrong or non-deterministic rule results (a `derived` label promises exactness): covered by section 1.1.
1. Citation/evidence correctness (hallucinated or wrong-source claims): highest user-visible risk. Tests: every claim in an answer maps to an existing chunk id; negative cases.
2. Structured extraction validity and gold-set scoring (`eval/extraction_gold`, `score_extraction.py`).
3. Retrieval recall on the question set (multi-hop across stories).
4. Prompt-injection from corpus text; MCP tool input validation (security-reviewer co-owns).
5. Resource budget: RAM/latency on the CPU-only target (<=8B models); `just run` works offline after first setup.
6. Ingest/data integrity: licences (`data/LICENSES.md`), round-trip of `chunks.jsonl`, no raw data committed.
7. UX polish: lowest.

## 10. Definition of done

A backlog item is done when:
- code merged with `just lint`, `just typecheck`, `just test` green locally and in CI;
- new behaviour has tests at the right layer; coverage gate not lowered;
- acceptance criterion from `docs/backlog.md` verified by actually running it, with the command and result noted;
- affected eval metrics run and not regressed (or the delta explained);
- docs/ADR updated; no TODO without a backlog id; no committed data/models/secrets;
- Conventional Commit message, no co-author or tool-attribution trailers.

## 11. Open requests (to file in docs/backlog.md by their owners)

- `LLMClient` interface + `FakeLLM` (agent-engineer / test-automation-engineer).
- `scripts/index/build.py`, `eval/run_eval.py --short` (done, issue #6), `python -m detective_board` entry (blocked on spike ADR).
- `uv lock` refresh after dev-group change (devops-engineer): CI uses `--locked` and fails until done.
