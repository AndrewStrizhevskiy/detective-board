# Disclosure

What was computed where, what runs at demo time, and what is and is not verified.
Short and plain on purpose. Last updated 2026-10-26.

## What runs at demo time

The demo runs offline on the target laptop (ThinkPad X1, 7th gen, CPU only): the API and UI
(`just run`), local Ollama with the models below, the retrieval index and the knowledge graph
read from two precomputed files (`data/index/db.sqlite`, `data/graph/graph.sqlite`), the
rules R1-R3 and the MCP server. No network and no cloud model are used at demo time.
Recorded runs, if shown, are labelled as recordings in the UI.

## What was precomputed on other hardware, and why

- Knowledge-graph extraction. Running the extraction model over all 596 chunks on the laptop
  CPU would take days. Extraction was split into shards and run on stronger machines (some with
  a GPU) with the same model tag, prompt version and options (temperature 0, seed 42,
  num_ctx 4096, num_predict 1536). The shard caches were merged, normalised and built into
  `graph.sqlite`. Outputs can differ slightly across hardware and Ollama versions
  (`docs/team/models.md`). Which machines ran which shard: TO BE FILLED (see table below).
- Evaluation runs. Long evaluation runs (golden questions, contradiction cases, model
  comparisons) were run on stronger machines. The laptop was used for latency and memory.
- The retrieval index is built with `just index`; where it was built for the demo archive:
  TO BE FILLED.

Whether precomputing on other hardware is allowed by the organizers: yes, the organizers gave
their approval (reported by the team lead on 2026-10-26; the written reply is to be attached here:
TO BE FILLED with its date and wording). We say this on stage regardless.

## Models

Tags and digests are the ones in `docs/team/models.md` (digests from `ollama list` on the
reference laptop, 2026-10-23).

| Tag | Role | Digest |
|---|---|---|
| `bge-m3:latest` | embeddings | `790764642607` |
| `qwen3:4b` | extraction | `359d7dd4bcda` |
| `qwen3:4b-instruct` | answer / agent | `0edcdef34593` |
| `gemma3:4b` | extraction / answer comparison | `68ceab7e468a` |
| `qwen3:8b` | upper-bound comparison (not in the demo) | `500a1f067a9f` |

Judge model: no LLM judge is used at demo time. Any model-based judging is evaluation only,
and the judge model is named next to each result that used one. Judge use so far: TO BE FILLED
(the answer check in `eval/run_answer_check.py` uses text proxies and a regex, not an LLM judge).
Licences of the models: `THIRD_PARTY_NOTICES.md`.

## Gold sets: written by an AI

`eval/golden/questions.jsonl` (64 questions) and `eval/golden/contradictions.jsonl`
(43 cases) were written by a Claude agent from the text in `data/clean/`, not by a human. The
validators prove only that quotes are verbatim substrings of the stories. The 12-chunk
extraction gold set is also agent-labelled. Dev/test split and protocol: `eval/golden/split.json`
and `eval/golden/README.md`.

Human review status (to be filled by the reviewers; until filled, nothing was reviewed):

| Set | Items reviewed by a human | Reviewer | Date | Changes made | Status |
|---|---|---|---|---|---|
| golden questions (64) | TO BE FILLED | TO BE FILLED | TO BE FILLED | TO BE FILLED | not reviewed |
| contradiction cases (43) | TO BE FILLED | TO BE FILLED | TO BE FILLED | TO BE FILLED | not reviewed |
| extraction gold (12 chunks) | TO BE FILLED | TO BE FILLED | TO BE FILLED | TO BE FILLED | not reviewed |

The test split was used by nobody for tuning. Test results, once reported, are one run per
frozen configuration with Wilson 95% intervals.

## Which numbers were measured where

- Speed and memory (time to first token, tokens per second, RSS, 16/8 GB profiles): valid only
  when measured on the target laptop in a clean window. Numbers from any other machine are
  labelled with that machine and are not used as final (`CONTRIBUTING.md`).
- Quality numbers (answer quality, contradiction detection, extraction scores) are mostly from
  stronger machines or from the laptop CPU; each reported number states which. Per-result
  hardware: TO BE FILLED when the final table exists. The spike benchmarks in
  `docs/spike/REPORT.md` state their own host.
- No number here is a claim about hardware it was not measured on.

## Corpus: source and licence

Twenty stories by Arthur Conan Doyle, from five Project Gutenberg plain-text ebooks
(#1661, #834, #108, #2350, #69700), fetched unmodified by `scripts/corpus/fetch.py`. Sources
and checks are in `data/LICENSES.md` (checked 2026-10-22). What that file supports, and no more:

- The stories were first published before 1931; the author died in 1930. They are in the
  public domain in the UK/EU and the US. Gutenberg's own headers for these ebooks give the US
  status; for other countries it advises checking local law.
- The Gutenberg header, footer and licence are removed in `data/clean` and `data/chunks.jsonl`.
  The raw files in `data/raw/` keep the full Project Gutenberg licence text and must be
  redistributed only with it.
- Credit: texts from Project Gutenberg (https://www.gutenberg.org). "Project Gutenberg" is a
  registered trademark. This project is not affiliated with, endorsed by or sponsored by
  Project Gutenberg or the Project Gutenberg Literary Archive Foundation.
- Legal review by a lawyer: none.

## Known limitations

Extraction errors pass into the symbolic layer, so a derived finding follows from the stated
facts, not necessarily from the story. Small gold sets give wide intervals. Items not built
are marked planned in the README and docs.
