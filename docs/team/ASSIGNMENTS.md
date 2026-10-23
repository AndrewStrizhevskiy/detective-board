# Work packages (4 teammates)

Deadline for all four packages: **everything merged into `main` by 2026-10-27 18:00**. Freeze
2026-10-28 (fixes only). Rules: `CONTRIBUTING.md`. Models: `docs/team/models.md`.
Hours are estimates of focused work including review rounds. Hardware-dependent timings are
valid only on the target laptop (ThinkPad X1 7th gen); label anything else as such.
Zones come from `.claude/agents/*.md`; need a change outside yours: add an `R-nn` line to
`docs/backlog.md`.

Suggested start order (day 1 = 2026-10-23): A and C start the long GPU runs first, B and D
start on the laptop-free work.

---

## Package A: Extraction on strong hardware

- Branch: `feat/extract-gpu-shards` (cache + report), `exp/extract-prompt-<variant>` (variants)
- Estimate: 14 h (runs 6 h wall, mostly unattended; variants 8 h). Deadline: shards merged by 2026-10-25 18:00, variants decided by 2026-10-26 18:00, all merged by 2026-10-27 18:00.
- Zones: `src/detective_board/extract/`, `prompts/extract/` (nlp-extraction-engineer), plus the new `scripts/extract_shard*.{sh,py}` and `scripts/merge_extract_cache.py`; `docs/spike/results/` for result summaries. Not: graph, agent, web.

**Goal.** Produce the full extraction cache (596 chunks, 20 stories) on a GPU machine with the
same model tag, prompt, schema, temperature 0 and seed as the laptop, so the laptop never runs
the long extraction; then try to raise claim/relation quality.

**Deliverables**
1. Cache for `qwen3:4b` for all stories (and `gemma3:4b` or `qwen3:8b` if time allows), merged into `data/cache/extract-cache.sqlite` (not committed; shared as an archive with sha256).
2. `docs/spike/results/extract-gpu-<date>.md`: counts, speed (labelled "GPU box, not target laptop"), `ollama --version`, GPU, digests.
3. Determinism spot-check report: 3 chunks re-run on the laptop (orchestrator does the laptop side) vs GPU cache, using `merge_extract_cache.py verify`.
4. Prompt/schema variants with scores on the 12 gold chunks; recommendation with numbers.

**Acceptance criteria**
- `scripts/merge_extract_cache.py merge ...` prints `foreign=0`, `conflicts=0`; cache entry count = chunk count (596) for the model.
- `verify -n 3` on the agreed chunks: identical raw output, or a written explanation of every difference (differences are findings, not hidden).
- Variants evaluated with the same command as the baseline: `uv run python scripts/spike/score_extraction.py PRED.jsonl` and `scripts/spike/overlap_metric.py` on `eval/extraction_gold/` (12 chunks); a variant is proposed only if claims and relations recall improve without grounded rate dropping. A new prompt means a new prompt version (new cache key); the baseline cache stays valid.
- Valid-JSON rate, grounded rate, truncated count reported next to the baseline.

**First steps**
1. Setup per CONTRIBUTING; `ollama pull` models from `models.md`, check IDs.
2. `uv run python scripts/extract_shards.py plan 4` (balanced ~150 chunks per shard).
3. Run shards (split among machines, or sequentially on one): `scripts/extract_shard.sh 0 4 qwen3:4b` ... `3 4`. Resumable. Do not pass options that change the cache key.
4. Merge: `uv run python scripts/merge_extract_cache.py merge data/cache/extract-cache.sqlite data/cache/extract-cache-qwen3_4b-shard*.sqlite --model qwen3:4b` (add `--dry-run` first).
5. Verify against the laptop cache: `... verify LAPTOP.sqlite GPU.sqlite --model qwen3:4b -n 3`.
6. Variants on `exp/extract-prompt-*`; score; write up.

**Customer-visible risks**
- Different Ollama/GPU build gives different raw output: graph differs from what the orchestrator tuned the agent on. Mitigation: determinism check before replacing the laptop cache.
- A variant that raises claim counts but lowers grounding produces fake evidence in the contradiction demo. Grounded rate is a hard gate.
- Speed numbers from the GPU quoted as laptop speed (AC-12). Must be labelled.

---

## Package B: UI polish and e2e

- Branch: `feat/web-polish-r15`, `feat/web-e2e-playwright`
- Estimate: 16 h. Deadline: e2e merged by 2026-10-26 18:00, polish merged by 2026-10-27 18:00.
- Zones: UI source in `web/` (frontend-engineer zone is `src/detective_board/web/` or `web/`), `docs/design/` only for token fixes via request, `tests/e2e/` (new, with the test-automation-engineer's marker `e2e`), `tests/web_js/`. Not: api, agent.

**Goal.** Close backlog item R-15 and have a browser test that proves the demo path works
against the fake backend.

**Deliverables**
1. R-15 items from `docs/backlog.md`: dark theme view and contrast re-run (`python3 docs/design/contrast_check.py`), narrow layout, screen-reader pass, entity search/expand clicks, 429/degraded states in the browser, record/save-run; missing: 25-node cap with "+N more", A/B contradiction quotes, prefill wait estimate.
2. Playwright e2e (`tests/e2e/`, marker `e2e`) against `python -m detective_board.api --fake`: ask a question, trace events stream, answer with quotes, click quote highlights source, provenance badges and "Why?" panel, refusal case, REPLAY badge, degraded/429.
3. Accessibility notes: keyboard path through the demo, ARIA roles, contrast table in `docs/design/` (via request if outside zone).

**Acceptance criteria**
- `uv sync --group e2e && uv run playwright install chromium && uv run pytest -m e2e` green locally; `just test-web` green; `just lint test typecheck` green.
- Contrast check passes for light and dark; no text under WCAG AA at projector sizes defined in `docs/design/board-design.md`.
- Layout usable at 1366x768 and at a narrow width (set in the PR); screenshots attached to the PR (small PNGs, not committed if large).
- No CDN at runtime (offline check: block network in Playwright and the page still works).

**First steps**
1. `uv run python -m detective_board.api --fake`, open the printed URL, walk `docs/design/demo-script.md` steps 1-5.
2. Write the failing e2e test for step 1, then polish items in R-15 order of risk (degraded states first).
3. Re-run contrast check after every token edit.

**Customer-visible risks**
- Projector legibility and dark theme contrast: the jury reads the screen from a distance.
- UI frozen look while the model prefills (AC-12): the waiting counter must be there.
- Provenance badge or "Why?" panel showing "none attached" on real data (R-14 is the backend side; coordinate with the orchestrator).

---

## Package C: Eval and human review

- Branch: `feat/eval-run-eval`, `fix/eval-golden-review`
- Estimate: 18 h (human review 4 h, runner 8 h, runs 6 h on the strong machine). Deadline: review PR by 2026-10-25 18:00, runner merged by 2026-10-26 18:00, final heavy run by 2026-10-27 12:00, report merged by 2026-10-27 18:00.
- Zones: `eval/`, `scripts/eval/` (eval-engineer), `docs/spike/results/` for run outputs. Not: agent/retrieval code (request instead).

**Goal.** Trustworthy numbers: humans verify the golden and gold sets, then one runner
compares four configurations.

**Deliverables**
1. Human spot-check (a person, not Claude) of `eval/golden/*` (64 questions, 43 contradiction cases; at least 10 items per the README, the least certain 8 plus random ones) and `eval/extraction_gold/*` (all claims and relations of at least 4 of the 12 chunks). Corrections and a log (who, which ids, what changed) in a PR; update the "needs human review" status in both READMEs only after the check. Run `scripts/eval/validate_golden.py` and `validate_contradictions.py` after edits.
2. `eval/run_eval.py`: runs 4 configurations (bare LLM / vector only / vector+rerank / hybrid+graph) over `eval/golden/questions.jsonl`; metrics: faithfulness, citation correctness, refusal rate (out-of-corpus questions), hallucination rate, retrieval recall, table + chart output (markdown table, PNG chart or text bar chart, written to `docs/spike/results/eval-<ts>.md|json`); `--short` CI mode (small subset, fake/mocked LLM, no Ollama) wired to `just eval --short`.
3. Heavy run on the strong machine; the report states hardware, models, seeds, and which numbers are speed (not valid for the laptop) vs quality.
4. Separate table for rule-based contradiction detection (T-39), if time allows.

**Acceptance criteria**
- `uv run python eval/run_eval.py --short` runs offline in under 2 minutes, deterministic across two runs, covered by pytest (mocked).
- Each metric has a written definition in the runner docstring or `eval/README`; the judge (if an LLM is used) is named by tag and its bias noted.
- Report lists reviewed vs unreviewed items; metrics on unreviewed items are marked provisional.
- Corrections PR has per-item reasons; no gold quote left that is not a verbatim substring.

**First steps**
1. Read `eval/golden/README.md`, `eval/extraction_gold/README.md`, `docs/test-plan.md`, AC-14/AC-15.
2. Do the human review first (it gates every metric).
3. Check what `eval/run_answer_check.py` and the agent API already expose before writing the runner (agent-engineer owns the agent; use its public interface only).

**Customer-visible risks**
- Metrics computed on unreviewed gold look authoritative but are not; the jury asks "who checked the answers".
- LLM-as-judge inflating faithfulness; report with the judge model named.
- Small sample (64) gives wide intervals: do not claim differences smaller than the noise.

---

## Package D: Run, package and present

- Branch: `feat/ops-run-offline`, `feat/ops-package`, `docs/demo-slides`
- Estimate: 20 h. Deadline: `just run` and clean-machine test by 2026-10-26 18:00; package, recording tooling, slides, FAQ review merged by 2026-10-27 18:00.
- Zones: `justfile`, `Dockerfile`, compose, `.github/`, `pyproject.toml` only via the devops-engineer rules (small, reviewed changes), `docs/demo/`, `docs/design/demo-script.md` (read; edits by request), new `scripts/ops/`, `docs/ops/`, `docs/demo/slides/`. Not: application code.

**Goal.** Anyone can start the product with one command on a machine without network, and the
presentation survives a model hang.

**Deliverables**
1. `just run`: one command, offline, starts API and UI against local Ollama and prebuilt data (AC-13). Today the `run` recipe is a TODO.
2. No-network install: either Dockerfile + compose, or a documented venv + models archive (wheelhouse for `uv`, Ollama model blobs, data caches) with checksums.
3. Clean-machine test script (`scripts/ops/clean_machine_check.sh`) and a checklist in `docs/ops/`: fresh clone, network off, `just run`, ask one question, stop. Run on a VM or fresh user.
4. Backup screen-recording tooling (documented command for OBS or `ffmpeg`, naming, where files live) and the replay files for the UI (stored runs per R-02, coordinate format with the orchestrator/backend), tested via REPLAY badge.
5. Slides skeleton from `docs/design/demo-script.md` (outline, one slide per step, speaker notes), format agreed with the team (Markdown or pptx).
6. Review of `docs/demo/jury-faq.md`: every claim checked against code/results; unverified answers marked or removed.

**Acceptance criteria**
- Clean-machine check passes with the network physically off, checklist signed with date and machine name.
- `just run` documented in README (via the tech-writer request path) and works from a clean checkout after one documented preparation step.
- Replay of each scripted question works without a model running.
- FAQ review PR lists each changed answer with its evidence (file or measured number).

**First steps**
1. Read `docs/design/demo-script.md` sections 1 (pre-show checklist) and 4 (fallback ladder), AC-13, AC-18, AC-19.
2. Replace the `run` TODO in `justfile` with a recipe that calls `python -m detective_board.api` (check `--help` for flags).
3. Test with `unshare -n` or by disabling the network adapter.

**Customer-visible risks**
- Network down in the demo room, or a first-run download (model, wheel, font, CDN) that stalls: the single most likely live failure.
- Live model hang: replay and recording are the only recovery; both must be rehearsed.
- FAQ claims a number we have not measured on the target laptop.

---

## Orchestrator focus (not delegated)

- Agent integration: router, self-check and refusal gate, MCP tools wired to the symbolic rules, `Explanation` objects on trace events (R-14), API/agent glue.
- Extraction tuning on the laptop: schema-v2 fields (R-07, R-11), day resolution (R-08), determinism check of the GPU cache against laptop output, deciding which prompt variant ships.
- Performance measurements on the target laptop (ThinkPad X1 7th gen): latency, TTFT, RAM; the only numbers that go into STATUS/PRD (AC-12, AC-18). Rehearsals T-32.
- Merging PRs, resolving zone conflicts, freeze (T-28), final go/no-go.
