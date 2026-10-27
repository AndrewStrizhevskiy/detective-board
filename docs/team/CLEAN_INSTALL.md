# Clean install from the offline archive

For anyone on the team, not only the author of the archive: install Detective Board on a Linux
x86_64 laptop with **the network off**, check it, and start the demo. Aim: under 15 minutes, most
of it copying and the check (UNVERIFIED until the first clean-install record). This file is shipped in the archive as `INSTALL.md`.

The archive is built with `scripts/pack_offline.sh --tag <tag>` (on Linux x86_64, with the models
pulled and the data built) and contains: the repo at the tag with the `web/replay` recordings, the
index, sentence index and graph, `uv`, a Python 3.12 build, a uv cache with every locked package
(`uv-cache/`), the Ollama binary, the
models `bge-m3`, `qwen3:4b-instruct`, `qwen3:4b` (IDs as in `docs/team/models.md`), `MANIFEST`
and `SHA256SUMS`.

## You need

- The USB stick with `detective-board-offline-<ref>.tar` and `detective-board-offline-<ref>.tar.sha256`.
- A Linux x86_64 laptop with about 2.5 x the archive size free (the archive plus the unpacked copy)
  and 16 GB RAM (8 GB works with the 4B models, slower).
- `curl`, `tar`, `sha256sum` (present on any desktop Linux). Nothing else: no Python, no Ollama,
  no `uv` needs to be installed. `just` is optional.
- Nothing may be running on ports 8765 and 11435 during the check, or 8000 and 11434 for the demo
  (stop a system Ollama with `sudo systemctl stop ollama`).

## Checklist

Tick each step and note the time; the record goes into `docs/perf/clean-install-<date>.md`
(template below).

1. [ ] **Network off.** Unplug the cable and turn Wi-Fi off (airplane mode). `curl -m 3 https://pypi.org`
   must fail.
2. [ ] **Copy and check the archive.**
   ```bash
   cp /media/$USER/<stick>/detective-board-offline-<ref>.tar* ~/
   cd ~ && sha256sum -c detective-board-offline-<ref>.tar.sha256    # must print OK
   tar -xf detective-board-offline-<ref>.tar
   cd detective-board-offline-<ref>
   cat MANIFEST                                                     # commit, versions, model IDs
   ```
3. [ ] **Run the check.** It verifies every file, installs the Python environment from the
   packed uv cache, runs the fast tests, starts Ollama from the archive, compares the model IDs, starts
   the API like `just run` does and asks the three scripted demo questions plus a second refusal.
   ```bash
   ./verify_offline.sh --require-offline
   ```
   Expected: every line `PASS`, last line `RESULT: PASS`. The first run takes the longest
   (environment install plus the model loads); logs are in `verify-logs/`. If a step fails, the
   line names its log file; do not continue to the demo with a FAIL.
4. [ ] **Start the demo** (two terminals, both in `detective-board-offline-<ref>`):
   ```bash
   # terminal 1: Ollama from the archive
   OLLAMA_MODELS="$PWD/ollama-models" OLLAMA_HOST=127.0.0.1:11434 ollama/bin/ollama serve

   # terminal 2: the API and the UI
   export PATH="$PWD/bin:$PATH" UV_OFFLINE=1 UV_PYTHON_DOWNLOADS=never UV_CACHE_DIR="$PWD/uv-cache" UV_LINK_MODE=copy
   cd detective-board
   uv run --no-sync python scripts/preflight.py          # Ollama and both models answer
   uv run --no-sync python -m detective_board.api        # http://127.0.0.1:8000
   ```
   With `just` installed, `just run` in `detective-board/` does the same two commands. It calls
   `uv run` without `--no-sync`; with the variables above that resolves from the packed cache and
   needs no network (tested on macOS with the real lock; UNVERIFIED on the laptop until the first
   clean-install record says so).
5. [ ] **Ask the scripted questions** in the browser at http://127.0.0.1:8000
   (`docs/design/demo-script.md`):
   - `What kind of snake killed Dr. Grimesby Roylott?` → answered with the quote "It is a swamp adder!".
   - `Is there a conflict about where Aloysius Garcia was at about one o'clock on the night he died?`
     → the dashed conflict edge, R1, conditional; the Why panel opens.
   - `What was the creature that haunted the Baskerville family on the Devonshire moor?` → refused,
     no `llm.call` row in the trace.
   - Recordings work without a model: menu **Recordings**, or key `c` after a question.
6. [ ] **Stop.** `Ctrl+C` in both terminals; `verify_offline.sh` stops its own Ollama and API.
   Written outside the unpacked folder: only the Ollama key pair `~/.ollama/id_ed25519*` (Ollama
   creates it on first start). Inside: `detective-board/.venv`, new entries in `uv-cache/`, `verify-logs/`.

Done when the checklist passes **twice, on two different laptops**, each with a record.

## If something fails

| Symptom | Likely cause | What to do |
|---|---|---|
| `sha256sum -c` reports FAILED | copy damaged | copy again from the stick; if it fails again, the stick copy is bad |
| `uv sync offline` FAIL, "Network connectivity is disabled, but the requested data wasn't found in the cache" | the packed cache lacks a wheel for this platform | the archive was built on another platform or Python; rebuild on Linux x86_64 |
| `ollama` FAIL, "address already in use" | a system Ollama is running | `sudo systemctl stop ollama`, or `--ollama-port N` |
| `ollama: model IDs differ` | wrong model build packed | rebuild the archive; `pack_offline.sh` refuses IDs that differ from `docs/team/models.md` |
| `api` FAIL on c001 | the graph has no curated facts for Wisteria Lodge | the archive's graph is not the demo graph; rebuild with the right `data/graph/graph.sqlite` |
| `network: the internet is reachable` | the network is still on | step 1 |

## Record template

Copy to `docs/perf/clean-install-<YYYY-MM-DD>-<machine>.md`, fill in, commit.

```markdown
# Clean install, <YYYY-MM-DD>, <machine>

- Archive: detective-board-offline-<ref>.tar, sha256 <first 12 hex>, MANIFEST commit <sha7>
- Machine: <model>, <CPU>, <RAM>, <distribution and version>; target laptop: yes / no
- Network off by: cable unplugged + airplane mode / `unshare -rn`
- Who: <name> (not the archive author: yes / no)

| Step | Result | Time |
|---|---|---|
| 2 copy + checksum + unpack | | |
| 3 verify_offline.sh | RESULT: | |
| 4 demo start | | |
| 5 g001 / c001 / g047 / recordings | | |
| 6 stop | | |

verify_offline.sh summary (paste the lines after "== verify_offline"):

Problems and fixes:
```
