# Runbook: extraction on a GPU server (one session, 4-6 hours)

Goal: produce the extraction cache for all 20 stories (596 chunks) with the SAME model, prompt and
options as the laptop, bring one file back, and build the graph from it. Nothing else runs on the server.
Read `docs/team/models.md` (tags and digests) and `docs/team/ASSIGNMENTS.md` (Package A) first.

What this is: batch INFERENCE with an existing open model. There is no training and no fine-tuning.
The final agent still runs on the laptop; the server only precomputes data. Say so when asked.

## Known facts about the department server (reply of the tech support, 2026-10-26)

- Hardware: i7-12700K, 96 GB DDR4-3200, RTX 4070 (12 GB VRAM). qwen3:4b needs about 3.5 GB, qwen3:8b about 5.5 GB, so
  both fit; several parallel requests fit as well.
- Access only inside the university network (MSTU); allocated from 2026-10-26 until Sunday 2026-11-01 evening;
  everything else is to be agreed separately with the tech support.
- Time slots: Tuesday 2026-10-27 from 14:30; Wednesday 2026-10-28 from 12:00 to 18:00. Message the tech support on
  Telegram before coming (confirm the slot).
- Update 2026-10-26 18:29 (tech support): 1 TB NVMe SSD, the server is "completely ours", any OS may be installed
  (currently ALT Linux). Decision: do NOT reinstall unless needed. Check `nvidia-smi` and `uname -r` first; keep ALT Linux
  if the NVIDIA driver works and CUDA is visible (Ollama's Linux installer targets generic x86_64 with systemd). If
  there is no working driver after about 20-30 minutes, install Ubuntu 24.04 LTS (the same distribution as the lead's
  laptop) and install the driver with the distribution's tool. Ask about: internet access, SSH/VPN from outside the
  university network (official access only), sudo, the room's opening hours, running unattended overnight.
- Still unknown (ask): the operating system, whether the internet is reachable from the server network (else bring the
  model files and wheels on a USB stick), whether Ollama/uv may be installed in a user directory, whether a process may
  stay in `tmux`/`screen` after the slot ends, until what hour the room is open on Tuesday.
- The Tuesday session is the main one: the heavy run must finish before the Wednesday freeze (18:00); Wednesday is the
  backup slot. Since the server stays available until Sunday, later reruns (prompt variants, evaluation runs) are possible
  but nothing after the freeze may change the demo build.
- Expected speed on this GPU is NOT measured yet. Measure seconds per chunk in step 2 and decide the plan from it
  (a rough guess: some tens of seconds per chunk per stream, so the full corpus in a few hours or less).

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

```bash
just gold12          # or: scripts/server_gold12.sh   (models x prompts; resumable; FORCE=1 reruns)
```
It runs both prompts (v2.0, v2.1) with qwen3:4b and qwen3:4b-instruct on the 12 hand-labelled chunks, prints each
command it runs and one comparison table, and writes `docs/spike/results/gold12-<stamp>.md` (the scorer is
`scripts/spike/score_pipeline.py`; options in `docs/team/README.md`). Pick the prompt/model with the best claims and relations numbers that keeps JSON
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
just graph                                           # merges nothing, runs scripts/run_extraction_priority.sh (all cache hits,
                                                     # no model calls), builds data/graph/graph.sqlite, then normalises it
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
