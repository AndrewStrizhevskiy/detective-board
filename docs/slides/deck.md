---
marp: true
theme: default
paginate: true
size: 16:9
title: Detective Board - where the agent guesses, and where it proves
description: 6:30 talk, 10 main slides plus backup. Source of every number is listed in numbers.md.
style: |
  section { font-size: 28px; }
  section h1 { font-size: 40px; }
  section.small { font-size: 22px; }
  section.tiny { font-size: 18px; }
  blockquote { font-size: 24px; }
  table { font-size: 22px; }
  .rec { color: #8a5a00; font-weight: bold; }
---

<!--
Slide 1, 0:00-0:35 (35 s). Running total 0:35.

SETUP: slides full screen; board (browser) and terminal in other windows, warmed, network off. The g001 agent question is typed in the board but NOT sent yet.

SAY (about 85 words):
"Language models answer fluently, with no proof. This is a small model, recorded earlier on this laptop, asked who killed Dr. Roylott. It says he was not killed by a snake, puts him in the wrong book, and then contradicts itself. The right answer is a swamp adder, from The Speckled Band. Today I show an agent that guesses in one place and proves in another, and I will tell you which is which."

ACTION at the end of this slide: switch to the board, press Enter on the g001 question (about 10 s to the answer), come back to the slides. It will be done by slide 4.

NUMBERS: bare transcript = answers-20261023-v3-BARE-qwen3_4b-instruct.jsonl, id g001, n=1 question, 1 run, 300 tokens, cut by the token limit. The text is verbatim; it is a RECORDING of a real run, never staged.

IF IT GOES WRONG: the transcript is on this slide, so nothing to play. If the board does not take Enter, skip the live start and use slide 4 fallback (replay).
-->

# Fluent is not proven

A small model, no evidence, asked: *What kind of snake killed Dr. Grimesby Roylott?*

> Dr. Grimesby Roylott was not killed by a snake in the story of *The Hound of the Baskervilles* or any of Arthur Conan Doyle's Sherlock Holmes stories. [...] Wait - correction: **Dr. Grimesby Roylott is not a character in *The Hound of the Baskervilles*.**

<span class="rec">RECORDING</span> - qwen3:4b-instruct, no retrieval, temperature 0, seed 42, run of 2026-10-23, 1 question. Answer in the book: a swamp adder (*The Speckled Band*).

---

<!--
Slide 2, 0:35-1:05 (30 s). Running total 1:05.

SAY (about 75 words):
"The idea is a split of labour. The language model only reads: it extracts facts and proposes sentences, and it can be wrong. A graph stores each fact with the exact quote it came from. Deterministic rules then prove what follows, the same way every time. And the text answers by quoting: the answer is the book's own sentence. So where the model guesses, you see a label; where a rule proves, you see the quotes."

LABELS to point at: extracted (model, probabilistic), derived (rule, deterministic, with explanation), conditional (rule, but the input is doubtful).

NUMBERS: none on this slide.

IF IT GOES WRONG: nothing to fail. If late, drop the sentence on labels.
-->

# The idea: LLM guesses, rules prove

| Part | Does | Label |
|---|---|---|
| **LLM** | reads the stories, extracts facts with a verbatim quote and a confidence | `extracted` |
| **Graph** | stores every fact with its quote and source anchor | - |
| **Rules R1-R3** | derive findings the same way every time; each lists the quotes it used | `derived` / `conditional` |
| **Text** | answers are sentences of the book, not model prose | `source_text` |

R1: one person, one place, one interval. R2: event order has no cycle. R3: a witness claim against an established fact.

---

<!--
Slide 3, 1:05-1:40 (35 s). Running total 1:40.

SAY (about 85 words):
"One picture. Offline, the model extracts facts from twenty stories into a graph; a hybrid index finds passages. At question time the agent routes the question. A text question goes to retrieval, and the model only chooses numbered sentences. A rule question goes to a tool server over MCP, a separate process that calls the same rules and never calls a model. Everything runs on this laptop, on the CPU, with the network off."

POINT AT: the MCP box (separate process), the rules box (no LLM), the board UI (every step shown in the trace).

NUMBERS: none on this slide. Diagram follows docs/architecture/c4.md and README.md; it is plain text so it exports offline.

IF IT GOES WRONG: this is a slide. If the board is needed early, it is behind this slide in the next window.
-->

# Architecture on one picture

```
 20 stories --> LLM extraction (offline) --> GRAPH (facts + quotes)
      |                                          |
      v                                          v
 hybrid index                          RULES R1-R3 (no LLM)
 (BM25 + embeddings)                             ^
      |                                          |
      +--------> AGENT (router, self-check) <--MCP stdio--> timeline-alibi
                          |
                          v
        BOARD UI: graph, trace, answer, Why panel
```

Full diagrams: `docs/architecture/c4.md` (mermaid, renders on GitHub).

---

<!--
Slide 4, 1:40-2:30 (50 s). Running total 2:30. LIVE DEMO 1.

SCREEN: switch to the board. The g001 answer is already there (started at the end of slide 1), with the route chip, the quote card and "selfcheck: verified".

SAY (about 125 words):
"The same question to our agent, started live a minute ago. It took about ten seconds. The model did not write this answer: it chose one numbered sentence from the retrieved text, and the answer is that sentence, word for word. Now the part that does not depend on trusting anyone." [terminal] "A one-second search of the book finds the line. The quote is a verbatim substring of the story. 'Verified' here means exactly that, and that it supports the sentence. It does not mean the claim is true, and I come back to that."

TERMINAL: rg -F "It is a swamp adder!" data/clean/speckled-band.txt  (one hit). Optional second: rg -il "baskerville" data/clean  (no output).

NUMBERS: 9.3 s for g001, extractive mode, 1 run of 12 questions = api12-20261027-extractive.md. Do not say "always".

IF IT GOES WRONG: see docs/design/demo-script.md, step 0 and step 4. Fallback URL: http://127.0.0.1:8000/?replay=replay/real-g001-agent.json&speed=4 (RECORDING badge; say "this is a stored run"). Failure line: "The model is still choosing its sentence; to keep to time, here is the stored run of the same question, labelled as such."
-->

# Demo 1: a question, a verbatim quote

**Q:** What kind of snake killed Dr. Grimesby Roylott?

> From the sources: [1: "“It is a swamp adder!” cried Holmes; “the deadliest snake in India."]

`selfcheck: verified` - `speckled-band-0030` - the model only picked the sentence

```
$ rg -F "It is a swamp adder!" data/clean/speckled-band.txt
```

*Verified = verbatim in the book and supports the sentence. Not = true.*

---

<!--
Slide 5, 2:30-3:40 (70 s). Running total 3:40. LIVE DEMO 2. The longest step; do not cut the word "curated".

SCREEN: board. Type the c001 question. Answer is instant (rule-first, no model call).

SAY (about 175 words):
"Now a rule. Wisteria Lodge: was Garcia in two places at about one o'clock? First, a disclosure: for this case the facts are curated. Our team wrote them down from the book with the quote for each, because our small model cannot yet tell who 'he' is in these sentences. It is on the slide, in the answer, and in the Why panel. The automatic numbers are separate. Watch the trace: the tool call to the MCP server, and its time in milliseconds; no model was involved. The rule R1 says one man cannot be in his bedroom and dead on Oxshott Common at one o'clock, and lists the two quotes it used. It is drawn dashed, conditional, because the proof rests on 'nearly one' and 'since one' both read as one o'clock, and on two places we resolved by hand. If we misread the text, the rule would prove something from the misreading, which is why every input shows its quote."

CLICK: the dashed conflict edge, open the Why panel, read the two quotes.

NUMBERS: none spoken except milliseconds read from the screen (not pre-measured: TBD rehearsal log). On the full 20-story server graph (graph-sanity-20261028.md) 52.5% of events have a normalised time, 4.5% a story day, 0.7% of claims a presence proposition, and the rules find 0 contradictions in 19 of 20 stories; the only finding is this curated one. Say it if asked.

IF IT GOES WRONG: fallback URL http://127.0.0.1:8000/?replay=replay/real-wisteria-r1-curated.json (1.1 s). Failure line: "The tool call is slow; here is the stored run of the same question, labelled as a recording." Never say the model found this.
-->

# Demo 2: Wisteria Lodge, rule R1

**Q:** Is there a conflict about where Aloysius Garcia was at about one o'clock on the night he died?

- Eccles: "*...saying that it was **nearly one** o'clock.*" (Garcia at Wisteria Lodge) - `curated`
- Baynes: "*He had been there **since one** o'clock.*" (Garcia dead on Oxshott Common) - `curated`
- **R1 violated, `= DERIVED`, drawn `conditional`** - tool call in ms, no model

**Curated facts: checked by the team, AI-assisted, human re-check pending. The automatic extraction is measured separately.**

---

<!--
Slide 6, 3:40-4:15 (35 s). Running total 4:15. LIVE DEMO 3.

SCREEN: board. Type the g047 question. The refusal row appears at once; no llm.call row; the board stays empty.

SAY (about 85 words):
"A question about a famous novel that is not among our twenty stories. The agent checks whether its evidence covers the question. It does not, so it refuses, in a fraction of a second, without calling the model. A bare model would happily tell the story from memory; that is canon knowledge, not evidence from our corpus. An honest 'nothing about this' is the correct output here."

NUMBERS: gate: top chunks cover 0.17 of the question terms, need 0.25 (answers-20261023-v3-qwen3_4b-instruct.jsonl, g047, 0 LLM calls, 0.01 s); 0.2 s in the 12-question real-API run (api12-20261027-extractive.md). Thresholds are provisional.

IF IT GOES WRONG: if it does not refuse and calls the model: stop it with Esc, then http://127.0.0.1:8000/?replay=replay/real-refusal-baskerville.json . Failure line: "The thresholds are provisional and this live run missed; here is the stored run." Second refusal if time: replay/real-refusal-fee.json (22.6 s, passes the gate, model chooses NONE).
-->

# Demo 3: an honest refusal

**Q:** What was the creature that haunted the Baskerville family on the Devonshire moor?

> In these materials there is nothing about this.

- Gate: top chunks cover **0.17** of the question terms, need **0.25** - refused before any LLM call
- Bare model, same question: a confident answer from memory (canon, not corpus evidence)

---

<!--
Slide 7, 4:15-5:05 (50 s). Running total 5:05.

SAY (about 125 words):
"What we measured, with its caveats on the slide. Thirty test questions, run once, the expected ranges written down before the run. By a strict mechanical test, the answer must contain half of the key facts of the reference answer: ten percent for the bare model, thirty-seven for vector search only, forty-three for our agent. Retrieval clearly beats the bare model, and that is significant. Our agent is slightly ahead of plain vector search, but two questions out of thirty is within noise. Where it clearly helps: it quotes the right sentence in sixty-one percent of the answered questions against thirty-nine, and out-of-corpus questions are all refused. The rules found nothing on the automatically extracted graph, zero of twelve; the findings you saw come from facts entered by the team. Small sets written by an AI, one run; I will not round them up. And what did not work, we show: a model judge for contradictions flagged eight of nine controls, so it is off."

NUMBERS: every cell has a file in numbers.md (rows 5-11 and 30-33). The test split was NOT run; do not claim test results.

IF IT GOES WRONG: slide only. If late, say only the dev-split row and the 0/14 row.
-->

<!-- _class: small -->

# Measured quality (test split first, caveats included)

| What | Result | n | Caveat |
|---|---|---|---|
| **Test split, run once and preregistered, 2026-10-28** (final configuration, not tuned on these questions) | behaviour correct: bare **3/30 = 10%** [3, 26], vector-only **11/30 = 37%** [22, 54], hybrid+graph (the agent) **13/30 = 43%** [27, 61]; agent vs bare p = 0.006 (11 vs 1); agent vs vector 2 vs 0, p = 0.5, not significant; gold sentence quoted: agent 11/18 = 61%, vector 7/18 = 39%; out-of-corpus refused 6/6 | 30 questions, 1 run | mechanical proxy; AI-written gold; expected ranges written before the run (`test-preregistration-20261028.md`) and met |
| How to read the three configurations | the "vector-only" configuration is OUR pipeline (same quoted-sentence answers, refusals and self-check) with candidates from the best chunks only; "hybrid+graph" adds the sentence index and the rule tools. It is not an outside system, and the graph does not take part in plain fact answers; the rules and the graph matter for conflict, alibi and chronology questions | - | explains why the two are close; the real contrast is with the bare model |
| Retrieval and refusals, same run | gold chunk in top 4: vector **18/27 = 67%**, hybrid **21/27 = 78%**; out-of-corpus refused: bare 4/7, vector 7/7, hybrid+graph 6/7; false refusals of answerable questions 20/27, 8/27, 7/27; the quoted sentence is the gold one: vector 13/19 = 68%, agent 10/20 = 50% | 27 answerable, 7 out-of-corpus | the agent's gain is in retrieval and honest refusal; its answer sentence is picked worse than the vector baseline's |
| Contradiction detection, rules only, automatic facts | dev recall **0/14**, false positives **0/9**; **test recall 0/12 [0, 24], false positives 0/8** | 23 dev + 20 test cases, 1 run each | on the automatic graph the rules find nothing; the findings in the demo come from curated facts |

Tried and did not work (shown on purpose): a model judge for contradictions (1 of 14 found, 8 of 9 controls wrongly flagged), choosing the culprit from a list (an innocent named in 2 of 8), the whole-case question before the reveal (0 of 16). FAQ, section A.

---

<!--
Slide 8, 5:05-5:30 (25 s). Running total 5:30.

SAY (about 60 words):
"The constraints. It runs offline, on the CPU of this laptop, with models of eight billion parameters or less: a four-billion answer model, a four-billion extraction model, and an embedding model. Decoding is fixed: temperature zero, seed forty-two. Reading speed on this CPU is about twenty-one tokens a second, which is why the model never writes the answer."

NUMBERS: ~21 tokens/s prefill = docs/perf/ttft-levers-2026-10-26.md (1 run per variant); peak RSS 3195 MiB = llm-20261022-171202.md (n=3 runs). Measured 2026-10-29 (docs/perf/laptop-20261029.md): median 28 s per answered question (18.6-44.1 s, 18 different questions, three series), peak RSS of all llama-server processes 6.3 GB, package temperature 98-100 C; not a clean window, no 8 GB profile.

IF IT GOES WRONG: slide only.
-->

# Constraints met

- **Offline**: network off during the demo; no cloud model
- **CPU-only**: no GPU on the demo laptop; prefill about **21 tokens/s**
- **Models <= 8B**: qwen3:4b-instruct (answers), qwen3:4b (extraction), bge-m3 (embeddings); peak RSS of the answer model **3195 MiB**
- **Reproducible**: temperature 0, seed 42; `just run` serves the demo; laptop, three series of 6 questions, 2026-10-29: median **28 s** per answer (19-44 s), **6.3 GB** peak, **98-100 C** (not a clean window); one-command offline install: `verify_offline.sh` passed on one laptop (not yet on a second)

---

<!--
Slide 9, 5:30-6:10 (40 s). Running total 6:10. MANDATORY DISCLOSURE. Read it, do not paraphrase away any of the four points.

SAY (about 100 words):
"Four things you must know. One: the knowledge graph was precomputed on other hardware, with the same models; the organizers allowed this. This laptop only answers questions. Two: the facts behind the red conflicts are curated, entered by the team with their quotes and labelled curated everywhere; the human re-check is still pending. Three: the gold sets were written by an AI and are not reviewed by a human; that review has not been done, and to be filled. Four: rule R3 has no positive example in our corpus, so it is implemented but not demonstrated. Everything shown is measured, and 'verified' does not mean true."

NUMBERS: server hardware and the hours of extraction are not on the slide; if asked: i7-12700K, 96 GB, RTX 4070 12 GB (STATUS.md). Hardware: laptop numbers on the demo laptop; extraction numbers on the department server.

IF IT GOES WRONG: slide only. If late, keep points 1 and 3.
-->

<!-- _class: small -->

# Disclosure and honest limits

1. **Precomputed on other hardware.** The graph extraction was run once on a department GPU server with the same open models, prompt and decoding settings; allowed by the organizers. No model was trained. This laptop answers questions offline.
2. **Curated facts.** Eight facts (Garcia and Scott Eccles at Wisteria Lodge, Lady Brackenstall at Abbey Grange, Boscombe control) were entered by the team with a verbatim quote, AI-assisted, and are labelled `curated` on screen and in the answer. Human re-check: pending.
3. **Gold sets written by an AI**, not reviewed by a human; the metric is mechanical. Review: **not done**. The test split was run once, expected ranges written beforehand.
4. **The rules find nothing on the automatic facts** (0 of 12 test cases): the red conflicts in the demo rest on curated facts. The weak link is extracting who-was-where-when.
5. Measured numbers only. **Verified = verbatim and lexically supported, not true.**

---

<!--
Slide 10, 6:10-6:30 (20 s). Running total 6:30.

SAY (about 50 words):
"What is next: a human review of the gold sets and of the curated facts; better extraction of who was where and when, by fine-tuning the small extractor and measuring it on human-checked facts; and evidence cards, so a case can be argued before the reveal. The principle stays: the model guesses, the rules prove, and every step shows its quotes. Thank you; questions."

NUMBERS: none.

IF IT GOES WRONG: slide only. Then Q&A from docs/demo/jury-faq.md; backup slides B1-B6 follow.
-->

# What is next

- Human review of the gold sets and of the curated facts
- Better extraction of who-was-where-when (fine-tune the small extractor on a server, measured on human-checked facts): the weak link of R1 and R3
- Evidence cards per chunk and a competing-hypotheses matrix, so that a case can be argued before the reveal (today: 0 of 16)
- Repeat the measurements on a second machine and with an 8 GB profile

**The model guesses. The rules prove. Every step shows its quotes.**

---

<!-- _class: small -->
<!--
Backup B7. Earlier and development numbers (Q&A only). Every row has its file in numbers.md.
-->

# B7. Earlier and development numbers

| What | Result | n | Caveat |
|---|---|---|---|
| Real API, extractive mode, 2026-10-27 | quoted sentence for **6 of 10** answerable; **2 of 2** out-of-corpus refused; **8.1-20.2 s** per model call | 12 questions, 1 run | "answered" is not "correct"; no human judging |
| Retrieval-only check, 2026-10-23 | **5 of 10** answered and verified; behaviour correct **8 of 12**; bare model vs agent on refusal-type questions **1 of 3** vs **2 of 3** | 12 questions, 1 run | AI-written gold; graph and rules off |
| Gold chunk within top 4 | **70 of 86 = 81%** | 86 questions | retrieval only, no LLM |
| Full graph from the department server, 2026-10-27 | **596 of 596** chunks, 20 of 20 stories, 2157 claims, 1698 events; rules: **0 findings in 19 of 20 stories** (only the curated Garcia R1) | 596 chunks, 1 run | extraction quality not scored beyond the 12 gold chunks; presence pass not run |
| Real stack on the full graph, laptop, 2026-10-28 | **5 of 6** dev questions answered with a quoted sentence in **30-43 s**; 1 refused (g009, multi-hop) | 6 questions, 1 run | not a clean window; answered is not correct |
| Dev split, three configurations, 2026-10-28 (eval runner, mechanical proxy, rescored) | behaviour correct: bare **4/34 = 12%** [5, 27], vector-only **15/34 = 44%** [29, 61], hybrid+graph (the agent) **12/34 = 35%** [21, 52]; retrieval beats the bare model (McNemar p 0.001 and 0.02); **vector-only vs the agent: 3 vs 0, p 0.25, not significant, the agent is not better** | 34 questions, 1 run | proxy = key-fact coverage >= 0.5 of the expected answer; AI-written gold; test split not run |
| Agent after tuning the candidate list (12 sentences from the index + 3 each from the 4 best chunks; chosen on dev from 3 experiments), 2026-10-28 | behaviour correct **14/34 = 41%** [26, 58]; gold sentence quoted **13/22 = 59%**; out-of-corpus refused **7/7**; false refusals **5/27**; all citations correct 9/22 | 34 questions, 1 run, hybrid+graph only | tuned on the same 34 dev questions: optimistic; vector-only 15/34 = 44% on the original run, so the gap to it is now one question; test split not run |

---

<!-- _class: small -->
<!--
Backup B1. NOT part of the 6:30. Use in Q&A ("why curated?", "does the automatic pipeline find it?").

NUMBERS: STATUS.md, 2026-10-27 morning; REPORT.md Addendum A2 repeats them. Presence-2.1 per-model fact counts are in presence21-c001-20261027.md (n=3 chunks, 1 run, precision unmeasured).
-->

# B1. Why curated: what the automatic pipeline found

First real run, one story (wisteria-lodge), after the deterministic repair:

- **107** events, **137** claims
- **0** exact clock times, **0** story days, **1** usable presence proposition
- R1 examined **19** pairs and could not decide **16**

Presence pass on the 3 chunks of case c001 (1 run each): qwen3:4b-instruct **7** facts, **1** kept (and the kept one is wrong); qwen3:8b **15** facts, **11** kept, key fact right, several wrong persons or places. Precision unmeasured.

Therefore the demo case uses five curated facts. They show what the rules do when facts are right, not what a model finds alone.

---

<!--
Backup B2. Extraction quality. NOT part of the 6:30.

NUMBERS: prompt-v2-2-20261026.md, 12 gold chunks, 1 run, AI-written gold. v2.2 was NOT adopted (ADR-0012). The v2.1 column is the production prompt.
-->

# B2. Extraction pilot (12 chunks)

| qwen3:4b | prompt v2.1 (used) | prompt v2.2 (not adopted) |
|---|---|---|
| strict F1 entities | 0.557 | 0.000 |
| strict F1 claims | 0.200 | 0.283 |
| strict F1 relations | 0.136 | 0.026 |
| claims with polarity=deny | 91% | 12% |
| events with participants | 0% | 33% |

Caveats: 12 chunks, AI-labelled gold, differences are noise. A deterministic repair step after v2.1 is used (ADR-0012). Source: `docs/spike/results/prompt-v2-2-20261026.md`.

---

<!--
Backup B3. Retrieval. NOT part of the 6:30.

NUMBERS: arms-20261023-080849.md (n=35, tuned on the same questions, optimistic); evidence-20261023-093201.md (n=86).
-->

# B3. Retrieval pilot

| Arm (bge-m3, 35 questions) | hit@1 | hit@5 |
|---|---|---|
| Hybrid RRF k=30, bm25:vec 0.5:1 | 0.63 | 0.97 |
| Hybrid k=10, 1:1 | 0.60 | 0.91 |

Gold chunk within top k, 86 answerable questions: top 3 **63/86 = 73%**, top 4 **70/86 = 81%**, top 5 **72/86 = 84%**.

Caveat: k and weights were tuned on the same 35 questions, so 0.97 is optimistic. No reranker needed at hit@5.

---

<!--
Backup B4. Speed. NOT part of the 6:30. Answers "why is it slow / why not generative?".

NUMBERS: perf file one run per variant; answers-20261023-v3.md and api12-*.md n=12, 1 run.
-->

# B4. Speed on this CPU

- Prefill: about **21-22 tokens/s**; threads, batch size, context length change nothing beyond noise (1 run per variant)
- Only the system-prompt prefix cache helped: **42.7 s** vs **52.7 s** for a 1080-token prompt
- Generative answers: **45.7-140.8 s** per model call (real API, 12 questions); retrieval-only check: first token **42.0 s**, **59.5 s** per question
- Extractive answers (the model only chooses sentences): **8.1-20.2 s**

This is why the model chooses a sentence instead of writing one (ADR-0009).

---

<!--
Backup B5. The control case. NOT part of the 6:30.

NUMBERS: none measured; the claim is qualitative (eval/golden/contradictions.jsonl c042, docs/symbolic-layer.md 11.1). The gold itself is low-confidence.
-->

# B5. The control case the rules must not flag

Boscombe Valley, case c042: both witnesses agree on what James did; they differ only on whether he was deliberately following. That is intent, not an observed fact.

- The rules correctly do **not** flag it (a regression test on three curated facts, not a real extracted graph)
- The control is weaker than its label: a human must decide the gold label
- Recording: `?replay=replay/real-boscombe-control.json` (25.3 s at original timing)

---

<!--
Backup B6. Answer modes and failure honesty. NOT part of the 6:30.

NUMBERS: api12-20261027-extractive.md, 12 questions, 1 run.
-->

# B6. Where the extractive mode still fails

Same 12 questions, one run:

- g007 and g016 are answerable but refused (the model chooses NONE)
- g057 (adversarial, correct premise expected) refused
- g062 (Russian) refused by the gate; Russian is optional
- The 4B model is wording-sensitive: one rewritten clause flipped g001 to NONE, so the selection prompt is frozen

"Answered" is not "correct": nobody has judged the answers.
