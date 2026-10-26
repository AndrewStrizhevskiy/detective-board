# Runbook: extraction on a GPU server (one session, 4-6 hours)

Goal: produce the extraction cache for all 20 stories (596 chunks) with the SAME model, prompt and
options as the laptop, bring one file back, and build the graph from it. Nothing else runs on the server.
Read `docs/team/models.md` (tags and digests) and `docs/team/ASSIGNMENTS.md` (Package A) first.

What this is: batch INFERENCE with an existing open model. There is no training and no fine-tuning.
The final agent still runs on the laptop; the server only precomputes data. Say so when asked.

## 0. Questions for the server admin (before the session)

GPU model and VRAM; OS; Docker/root available or not; internet access (or a proxy) for `ollama pull`;
disk (20 GB free); maximum session length; may we keep a process in `tmux`; how do we connect and copy
files back (scp/rsync/USB); may several processes use the same GPU. Without internet: bring the model
files (copy `~/.ollama/models` from a laptop that has the models in `docs/team/models.md`) and the repo
as a zip plus the `uv` cache.

## 1. Environment (about 20 minutes)

```bash
nvidia-smi                                   # note the GPU model and VRAM in your report
git clone git@github.com:AndrewStrizhevskiy/detective-board.git && cd detective-board   # or unzip
git log --oneline | head -3                  # note the commit hash
curl -LsSf https://astral.sh/uv/install.sh | sh   # only if uv is missing (official installer)
uv sync                                      # Python deps, pinned in uv.lock
uv run pytest -q -m "not live"               # must be green (about 500 tests, no Ollama needed)
```

Install Ollama following the official Linux instructions (https://ollama.com/download/linux; check the
version with `ollama --version`; the reference laptop runs 0.35.0). Start the server (`ollama serve`,
in a `tmux` window) and check that it uses the GPU (`ollama ps` shows the processor after the first request).

```bash
ollama pull qwen3:4b && ollama pull qwen3:4b-instruct && ollama pull bge-m3
ollama list        # compare the ID column with docs/team/models.md; a different ID = different build
```

## 2. Determinism check against the laptop (10 minutes) - do this BEFORE the full run

The repo ships a partial laptop cache (`data/extraction/extract-cache-qwen3_4b-extract-2.1-partial.sqlite`,
26 chunks of boscombe-valley-mystery, prompt extract-2.1). Re-run 3 chunks here and compare raw outputs:

```bash
EXTRA_ARGS="--limit 3" scripts/extract_shard.sh 6 20 qwen3:4b      # shard 6 of 20 = boscombe-valley-mystery only
uv run python scripts/merge_extract_cache.py verify \
    data/extraction/extract-cache-qwen3_4b-extract-2.1-partial.sqlite \
    data/cache/extract-cache-qwen3_4b-shard6.sqlite --model qwen3:4b -n 3
```
Outputs may differ slightly across hardware (different float kernels); that is acceptable if the items are
equivalent in meaning, but write down how many of the 3 are byte-identical. Also note seconds per chunk
from the shard's final report: it decides the plan in section 4.

## 3. Quality check of the prompt on the 12 gold chunks (30-60 minutes, before the long run)

`scripts/server_gold12.sh` (if present on your commit; see `docs/spike/results/gold12-*.md` afterwards)
runs both prompts (v2.0, v2.1) with qwen3:4b and qwen3:4b-instruct on the 12 hand-labelled chunks and prints
one comparison table. Pick the prompt/model with the best claims and relations numbers that keeps JSON
validity at 100% and quote grounding at or above 0.9. Defaults on the laptop were qwen3:4b and prompt v2.1
(prompt changes alter the cache key; if you change the default prompt or model, tell the team BEFORE running
the full corpus, because every shard must use the same choice).

## 4. The full run

Plan the split once: `uv run python scripts/extract_shards.py plan 4` (balanced by chunk count).

- One GPU: run 2-4 shard processes in parallel against the same Ollama server (one `tmux` window each);
  check the Ollama documentation for the concurrency settings (for example the number of parallel
  requests) before starting, and compare seconds per chunk with 1, 2 and 4 processes on the first
  chunks; keep the setting that finishes sooner.
- Several GPUs or several servers: one shard per GPU.

```bash
tmux new -s extract
scripts/extract_shard.sh 0 4 qwen3:4b      # window 1; then 1, 2, 3 in other windows
```
It is resumable: if a window dies, run the same command again (finished chunks are cache hits).
Watch progress: `uv run python scripts/merge_extract_cache.py count data/cache/extract-cache-qwen3_4b-shard*.sqlite`
(total must reach 596). Check every 20-30 minutes. If the speed is below about 60 seconds per chunk on a GPU,
something is wrong (CPU fallback, another process on the GPU): check `ollama ps` and `nvidia-smi`.

## 5. Merge, build the graph, bring results back

```bash
uv run python scripts/merge_extract_cache.py merge data/cache/extract-cache.sqlite \
    data/cache/extract-cache-qwen3_4b-shard*.sqlite --model qwen3:4b      # add --dry-run first
uv run python scripts/merge_extract_cache.py count data/cache/extract-cache.sqlite    # expect 596
scripts/run_extraction_priority.sh qwen3:4b 20      # all cache hits: builds data/graph/graph.sqlite (no model calls)
uv run python -m detective_board.extract.normalise data/graph/graph.sqlite
```
Sanity numbers to write into the report: chunks extracted, items kept and dropped (and why), share of events
with a time, share of claims with a proposition, stories with zero events.

Bring back (copy with scp/rsync/USB): `data/cache/extract-cache.sqlite`, `data/graph/graph.sqlite`, the
shard logs, and `report.md` containing: commit hash, `ollama --version`, GPU, model IDs, seconds per chunk,
number of identical outputs in the determinism check, the sanity numbers, anything unusual.
Do NOT commit binaries to git; hand the files to the lead (release asset or shared drive).

## 6. Cleanup

Stop `ollama serve`, delete the working copy and the pulled models if the admin asks, leave no keys or
tokens on the machine. Nothing in this repo contains secrets; never paste yours into logs or reports.

## If something fails

| Symptom | Likely cause | Action |
|---|---|---|
| `ollama pull` fails | no internet | use the copied model files (`~/.ollama/models`) |
| Very slow (over 60 s per chunk on a GPU) | CPU fallback or a shared GPU | `ollama ps`, `nvidia-smi`; restart `ollama serve` after fixing drivers |
| `merge` refuses entries | a different model, prompt or options | compare with `docs/team/models.md`; never use `--force` without telling the lead |
| Outputs differ strongly from the laptop in step 2 | different model build or Ollama version | check the model IDs and `ollama --version`; report before the full run |
| One shard dies | session limit or OOM | run the same command again (resumable) |
