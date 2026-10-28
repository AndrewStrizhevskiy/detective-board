# Disclosure

What was computed where, what runs at demo time, and what is and is not verified.
Short and plain on purpose. Last updated 2026-10-27 (morning).

## What runs at demo time

The demo runs offline on the target laptop (ThinkPad X1, 7th gen, CPU only): the API and UI
(`just run`), local Ollama with the models below, the retrieval index and the knowledge graph
read from two precomputed files (`data/index/db.sqlite`, `data/graph/graph.sqlite`), the
rules R1-R3 and the MCP server. No network and no cloud model are used at demo time.
Recorded runs, if shown, are labelled as recordings in the UI (five real recordings of 2026-10-27 are in `web/replay/real-*.json`, made on the target laptop at commit d9709d0).

## What was precomputed on other hardware, and why

- Knowledge-graph extraction. Running the extraction model over all 596 chunks on the laptop
  CPU would take days. Extraction was split into shards and run on stronger machines (some with
  a GPU) with the same model tag, prompt version and options (temperature 0, seed 42,
  num_ctx 4096, num_predict 1536). The shard caches were merged, normalised and built into
  `graph.sqlite`. Outputs can differ slightly across hardware and Ollama versions
  (`docs/team/models.md`). Which machines ran which shard: TO BE FILLED (see table below).
- The laptop cache of 231 chunks (8 stories, qwen3:4b, prompt extract-2.1) was made on the laptop and seeds the server run; those chunks are cache hits there.
- Evaluation runs. Long evaluation runs (golden questions, contradiction cases, model
  comparisons) were run on stronger machines. The laptop was used for latency and memory.
- The retrieval index is built with `just index`; where it was built for the demo archive:
  TO BE FILLED.

Whether precomputing on other hardware is allowed by the organizers: yes, the organizers gave
their approval (reported by the team lead on 2026-10-26; the written reply is to be attached here:
TO BE FILLED with its date and wording). We say this on stage regardless.

## Answer modes

Text questions are answered in the default extractive mode (ADR-0009): the language model does not write the answer, it chooses one or two numbered sentences from the retrieved text (constrained JSON), and the answer is those sentences verbatim, labelled `source_text`. Contradiction and alibi questions are answered rule-first (ADR-0010): when a rule tool ran, the answer is a template over its result with no model call; an empty result produces an honest sentence with coverage numbers and never says the accounts are consistent. The older generative mode exists for comparison only. Pilot evidence: 12 questions, one run each, `docs/spike/results/api12-20261027-generative.md` and `api12-20261027-extractive.md`; "answered" there means a quoted sentence, not a correct one, and nobody has judged correctness. The bare-model comparison in the demo is a labelled recording of a real run (2026-10-23).

## Curated facts in the demo cases

The demo cases (Wisteria Lodge and Abbey Grange, rule R1, and the Boscombe Valley control) use curated facts:
a small set of "person, place, time" statements in `data/curated/presence_demo.jsonl`, each with a
verbatim quote, written and checked by the team (AI-assisted, to be re-checked by a human; the
re-check has not happened yet). They are used because the small extraction models do not resolve
"he" and "there" on these passages. The screen, the Why panel and the spoken answer say "curated"
wherever such a fact is an input. The file has seven facts (two for Wisteria Lodge, three for the Boscombe control, two for Abbey Grange). The two Abbey Grange facts have no clock time: both are placed "at the moment Sir Eustace entered the room", a relative time that the team asserts is one moment, so the finding is always labelled conditional and says "relative time, curated". The automatic extraction numbers are reported separately and
are not improved by, or mixed with, the curated facts. A finding built on curated facts shows what
the rules do when the facts are right, not what a model finds on its own.

What the automatic pipeline did on real data (first real run, one story, wisteria-lodge, after the deterministic repair): 107 events, 137 claims, 0 exact clock times, 0 story days, 1 usable presence proposition; rule R1 examined 19 pairs and could not decide 16. The precision of automatic presence facts has not been measured: TO BE FILLED after the department-server run.

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
  stronger machines or from the laptop CPU; each reported number states which. Measured on the
  target laptop (CPU): the 12-question answer checks (2026-10-23 retrieval-only; 2026-10-27 real-API
  generative and extractive), the prefill/TTFT levers (2026-10-26), the five recordings, the first
  real extraction run and the 64-chunk repair sample (from caches made on the laptop). Not yet
  measured anywhere: extraction of all 596 chunks, presence-fact precision, contradiction
  precision/recall on a real graph, and the qwen3:8b against qwen3:4b gold12 comparison; these
  belong to the department server (i7-12700K, 96 GB, RTX 4070 12 GB), which will be named next to
  each result. Per-result hardware for the final table: TO BE FILLED. The spike benchmarks in
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
