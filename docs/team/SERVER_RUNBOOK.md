# Runbook: extraction on a GPU server (one session, 4-6 hours)

## TL;DR (two commands)

Facts from the admin: unrestricted internet (gigabit), direct attended access only, no VPN to install. The repo is
private and the server is a shared department machine: put NO GitHub credentials on it.

Before leaving (on the laptop, in the repo, on the commit to run):
```bash
scripts/make_server_archive.sh                                          # builds detective-board.tar.gz from HEAD (+COMMIT file) and verifies it in a clean copy (about 3 minutes)
# manual equivalent: git rev-parse HEAD > /tmp/COMMIT; git archive --format=tar.gz --add-file=/tmp/COMMIT -o detective-board.tar.gz HEAD
scp detective-board.tar.gz USER@SERVER:~/                              # or copy the file to a USB stick
```
On the server (use `tmux new -s extract` first, so a dropped terminal does not matter):
```bash
mkdir detective-board && tar xzf detective-board.tar.gz -C detective-board && cd detective-board   # from USB: copy it first
scripts/server_bootstrap.sh --with-8b  # 1: checks, uv, Ollama, server settings, models, tests, GPU proof; ends with PASS or FAIL + next step
scripts/server_run_all.sh              # 2: determinism -> concurrency probe -> gold12 -> full run -> merge/graph/report
scripts/server_progress.sh             # any time, from a second tmux window: counts per shard, chunks/min, ETA, last log lines
```
Decisions of 2026-10-26 (see docs/STATUS.md): the generic prompt stays extract-2.1 (v2.2 was worse); the gold12 phase now only
compares qwen3:4b with qwen3:8b on v2.1 (pick the better one for the full run: if qwen3:8b is clearly better on claims and
relations and fast enough, run the shards with `scripts/extract_shard.sh k N qwen3:8b` instead; the cache key includes the
model); after `finish` run the presence pass `scripts/server_presence.sh` (presence-2.1, needs the graph) with qwen3:8b and
qwen3:4b-instruct on the demo stories and check `truncated` in its report (raise `--num-predict` if outputs are cut).
Preview without changing anything: `scripts/server_bootstrap.sh --check-only`, `scripts/server_run_all.sh --dry-run`.
Short on time: `scripts/server_run_all.sh --skip-gold12`. Interrupted or a shard died: run the same command again (resumable).
Options: `--phase determinism,probe,gold12,run,finish`, `--streams N` (skips the probe), `--no-wait`, `--force`;
bootstrap: `--parallel N` (OLLAMA_NUM_PARALLEL, default 4), `--with-8b`. Logs and state: `data/cache/server/`.

What to copy back (the run ends by printing this list): `data/cache/extract-cache.sqlite`, `data/graph/graph.sqlite`,
`data/cache/server/report.md` (write anything unusual into its last section), and `data/cache/server/logs/`.
```bash
# on the laptop (or copy the files to a USB stick):
mkdir -p ~/server-out && scp USER@SERVER:'detective-board/data/cache/extract-cache.sqlite detective-board/data/graph/graph.sqlite detective-board/data/cache/server/report.md' ~/server-out/
scp -r USER@SERVER:detective-board/data/cache/server/logs ~/server-out/
```
Do not commit these binaries. Optional, only if scp/USB are impossible: a private GitHub release from the laptop
side (`gh release create <tag> <files> --repo OWNER/REPO --draft --title T --notes N`; syntax from
`gh release create --help`, assets are the file arguments). If `gh` must be used on the server at all, use a temporary
fine-grained token with release-upload permission only, type it with `read -rs GH_TOKEN; export GH_TOKEN` (never on the
command line, never in a file, never `gh auth login` on the shared machine), then `unset GH_TOKEN`, run `gh auth logout`
and delete the token on GitHub.

Cleanup checklist (before you leave): [ ] results copied and opened on the laptop; [ ] `ollama serve` stopped if it was
started by hand (`kill $(cat data/cache/server/ollama-serve.pid)`; a systemd service stays unless the admin says
otherwise); [ ] working copy removed if the admin asks (`rm -rf ~/detective-board ~/detective-board.tar.gz`);
[ ] no token anywhere (`gh auth status` says not logged in, token deleted on GitHub); [ ] no SSH keys or credentials
left on the machine; [ ] no VPN or other software installed beyond uv and Ollama.

How the Ollama server settings are applied (names from the official FAQ, verified 2026-10-26):
`OLLAMA_NUM_PARALLEL` (parallel requests per model, default 1) and `OLLAMA_KEEP_ALIVE` (for example `24h`).
systemd install: `sudo systemctl edit ollama`, add under `[Service]` the lines `Environment="OLLAMA_NUM_PARALLEL=4"` and
`Environment="OLLAMA_KEEP_ALIVE=24h"`, then `sudo systemctl daemon-reload && sudo systemctl restart ollama` (the bootstrap
does this when sudo works). Manual: `OLLAMA_NUM_PARALLEL=4 OLLAMA_KEEP_ALIVE=24h ollama serve` (the bootstrap starts it
that way when there is no systemd service). Without sudo the bootstrap prints the documented tarball steps
(`curl -fsSL https://ollama.com/download/ollama-linux-amd64.tar.zst | sudo tar x -C /usr`, user, systemd unit) for the admin.

The sections below are the manual fallback, the same steps one by one.

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
- Update 2026-10-27: unrestricted internet (gigabit), direct attended access only (no remote access); no offline bundle needed.
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
tar xzf detective-board.tar.gz -C detective-board && cd detective-board   # the archive from the TL;DR; do not clone the private repo here
cat COMMIT                                   # the commit hash (written by the laptop, goes into the report)
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

Bring back (scp/USB, see the TL;DR; no GitHub credentials on this machine): `data/cache/extract-cache.sqlite`, `data/graph/graph.sqlite`, the
shard logs, and `report.md` containing: commit hash, `ollama --version`, GPU, model IDs, seconds per chunk,
number of identical outputs in the determinism check, the sanity numbers, anything unusual.
Do NOT commit binaries to git; hand the files to the lead (release asset or shared drive).

## 5b. Presence pass (optional, after section 5; about 596 short requests per model)

A second, targeted extraction for R1/R3 ("person X at place P at time T", witness statements, denials; see
`docs/symbolic-layer.md` 11.3). It is not a phase of `server_run_all.sh` (it needs the finished graph and
two other models); it is its own script, resumable, with one cache, one graph copy and one predictions file per
model. Default prompt `presence-2` takes the candidate persons/places from the graph, so it MUST run AFTER the
generic extraction and graph build (`server_run_all.sh`); the script aborts if `graph.sqlite` is missing. Its quality is unmeasured until this run: read `eval.json` before believing anything.
```bash
ollama pull qwen3:8b && ollama pull qwen3:4b-instruct          # or add --pull below
scripts/server_presence.sh --limit 3 --dry-run                  # preview; then --limit 3 as a smoke test
scripts/server_presence.sh                                      # demo stories: wisteria-lodge boscombe-valley-mystery silver-blaze thor-bridge abbey-grange
scripts/server_presence.sh --all                                # then every story (demo chunks are cache hits)
scripts/server_presence.sh --literal                            # presence-2 strict variant: person/place must be in the quote
scripts/server_presence.sh --lenient                            # A/B: keep values not in the quote (LOW); no new model calls
scripts/server_presence.sh --verify --samples 3                 # RECOMMENDED (see below); own output files (-s3-verify)
```
**Recommended command: `scripts/server_presence.sh --verify --samples 3`** (both are off by default and their
quality is unmeasured; the point of the run is to measure them). `--verify` adds one short call per kept fact
(quote + the sentence before and after + the claim; the model answers a four-field enum, about 25 tokens): about
3-6 s per fact on this CPU, much faster on the GPU; fact counts are in the report (`funnel`, `verify_calls`). `--samples 3`
runs the presence call 3 times (seeds 42..44, temperature 0.3) and keeps facts found in at least 2: three times the
extraction time (the verifier then only sees the survivors). `--verify-model M` picks another verifier model,
`--verify-accept-partly` keeps "partly" facts with the failing place/time nulled (LOW). Everything is cached and resumable
(verifier keys have the prefix `verify:`). With `--samples 3` the samples use temperature 0.3, so they are new calls, not hits of an earlier plain run. `eval-s3-verify.json` has precision/recall per stage
(grounded, voted, verified) in `scores.<file>.stages`; the report has `funnel` (model, grounded, voted, verified),
`verify_rejected_by_detail` and `vote_below_majority`. Prompt wording: `prompts/extract/presence_verify_v1.txt`
(version in every fact's `verify.prompt_version`; to test another wording copy the file with a new version and pass
`--verify-prompt`).
Single model by hand: `uv run python -m detective_board.extract.presence --model qwen3:8b --chunks data/chunks.jsonl
--story wisteria-lodge --cache data/cache/presence-cache-qwen3_8b.sqlite --graph-db data/graph/presence-qwen3_8b.sqlite
--out data/cache/server/presence/qwen3_8b.jsonl` (the graph DB is a COPY of `graph.sqlite`; the pass writes into it and runs
the normaliser). Score without a model: `uv run python scripts/spike/presence_eval.py data/cache/server/presence/*.jsonl
--json data/cache/server/presence/eval.json`. Bring back `data/cache/server/presence/`, `data/cache/presence-cache-*.sqlite`
and `data/graph/presence-*.sqlite`. Write into the report: facts kept per model, `fact_survival_rate`, the strict-gold
recall (the gold has only 4 strict items), and the R1/R3 findings that the new graph gives
(`InProcessRulesClient(GraphStore(path)).call("find_contradictions", {"story": ...})`).

## 5c. Sentence index (optional, 5-10 minutes on a GPU; about 20 minutes on a laptop CPU)

The extractive answers can choose from sentences found by a hybrid search over the whole corpus instead of only
the sentences of the top chunks (`docs/api.md`, "Sentence index"). It needs only `bge-m3` (pull it if the
extraction models were pulled without it) and `data/chunks.jsonl`; no LLM runs.
```bash
ollama pull bge-m3
uv run python -m detective_board.index.sentences      # or `just sentences`; about 11000 sentences, resumable: run it again if the window dies
```
Progress goes to stderr (`embedded N/total`); it ends with `OK` and a count. Bring back
`data/index/sentences.sqlite` and `data/cache/sentences-emb.sqlite` (the embedding cache, so a rebuild on the
laptop costs nothing) together with the other files of section 5. Do not copy it onto a laptop whose
`data/chunks.jsonl` differs (the manifest holds the chunk file's sha256; a mismatch triggers a rebuild).

## 6. Cleanup

Use the cleanup checklist in the TL;DR. Stop `ollama serve`, delete the working copy and the pulled models if the admin asks, leave no keys or
tokens on the machine. Nothing in this repo contains secrets; never paste yours into logs or reports.

## If something fails

| Symptom | Likely cause | Action |
|---|---|---|
| `ollama pull` fails | no internet | use the copied model files (`~/.ollama/models`) |
| Very slow (over 60 s per chunk on a GPU) | CPU fallback or a shared GPU | `ollama ps`, `nvidia-smi`; restart `ollama serve` after fixing drivers |
| `merge` refuses entries | a different model, prompt or options | compare with `docs/team/models.md`; never use `--force` without telling the lead |
| Outputs differ strongly from the laptop in step 2 | different model build or Ollama version | check the model IDs and `ollama --version`; report before the full run |
| One shard dies | session limit or OOM | run the same command again (resumable) |
