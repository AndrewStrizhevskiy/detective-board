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

IF IT GOES WRONG: fallback URL http://127.0.0.1:8000/?replay=replay/real-wisteria-r1-curated.json (1.4 s). Failure line: "The tool call is slow; here is the stored run of the same question, labelled as a recording." Never say the model found this.
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
"What we measured, with its caveats on the slide. Twelve control questions through the real API on the laptop, one run: the extractive mode quoted a sentence for six of the ten answerable questions and refused both out-of-corpus ones, each model call in eight to twenty seconds. 'Answered' means a quoted sentence, not a correct one; nobody has judged correctness yet. In the earlier retrieval-only check, five of ten were answered and verified. Retrieval puts the right chunk in the top four for seventy of eighty-six answerable questions. These are pilot numbers on small sets written by an AI, so one question is noise. The full evaluation table with intervals is not here yet, and I will not invent it."

NUMBERS: every cell has a file in numbers.md. Fill the TBD row from issue #16 / #6 before the final deck; if it is still TBD on the day, say "not yet measured".

IF IT GOES WRONG: slide only. If late, say only the first row and the TBD row.
-->

<!-- _class: small -->

# Measured quality (pilot, caveats included)

| What | Result | n | Caveat |
|---|---|---|---|
| Real API, extractive mode, 2026-10-27 | quoted sentence for **6 of 10** answerable; **2 of 2** out-of-corpus refused; **8.1-20.2 s** per model call | 12 questions, 1 run | "answered" is not "correct"; no human judging |
| Retrieval-only check, 2026-10-23 | **5 of 10** answered and verified; behaviour correct **8 of 12**; bare model vs agent on refusal-type questions **1 of 3** vs **2 of 3** | 12 questions, 1 run | AI-written gold; graph and rules off |
| Gold chunk within top 4 | **70 of 86 = 81%** | 86 questions | retrieval only, no LLM |
| Full graph from the department server, 2026-10-27 | **596 of 596** chunks, 20 of 20 stories, 2157 claims, 1698 events; rules: **0 findings in 19 of 20 stories** (only the curated Garcia R1) | 596 chunks, 1 run | extraction quality not scored beyond the 12 gold chunks; presence pass not run |
| Real stack on the full graph, laptop, 2026-10-28 | **5 of 6** dev questions answered with a quoted sentence in **30-43 s**; 1 refused (g009, multi-hop) | 6 questions, 1 run | not a clean window; answered is not correct |
| Final eval table with intervals | **TBD (issue #16/#6)** | TBD | - |
| Contradiction precision / recall on the real graph | **TBD (issue #16/#6)** | TBD | not measured yet |

---

<!--
Slide 8, 5:05-5:30 (25 s). Running total 5:30.

SAY (about 60 words):
"The constraints. It runs offline, on the CPU of this laptop, with models of eight billion parameters or less: a four-billion answer model, a four-billion extraction model, and an embedding model. Decoding is fixed: temperature zero, seed forty-two. Reading speed on this CPU is about twenty-one tokens a second, which is why the model never writes the answer."

NUMBERS: ~21 tokens/s prefill = docs/perf/ttft-levers-2026-10-26.md (1 run per variant); peak RSS 3195 MiB = llm-20261022-171202.md (n=3 runs). Measured 2026-10-28 (docs/perf/laptop-20261028.md): 30.3-43.2 s per answered question, peak RSS of all llama-server processes 5017 MB, package temperature up to 92 C; one run, not a clean window, not final.

IF IT GOES WRONG: slide only.
-->

# Constraints met

- **Offline**: network off during the demo; no cloud model
- **CPU-only**: no GPU on the demo laptop; prefill about **21 tokens/s**
- **Models <= 8B**: qwen3:4b-instruct (answers), qwen3:4b (extraction), bge-m3 (embeddings); peak RSS of the answer model **3195 MiB**
- **Reproducible**: temperature 0, seed 42; `just run` serves the demo; laptop run 2026-10-28: **30-43 s** per answer, **5.0 GB** peak, **92 C** (single run, not final); one-command rebuild: **TBD**

---

<!--
Slide 9, 5:30-6:10 (40 s). Running total 6:10. MANDATORY DISCLOSURE. Read it, do not paraphrase away any of the four points.

SAY (about 100 words):
"Four things you must know. One: the knowledge graph was precomputed on other hardware, with the same models; the organizers allowed this. This laptop only answers questions. Two: the Garcia facts are curated, checked by the team and labelled curated everywhere; the human re-check is still pending. Three: the gold sets were written by an AI and are not yet reviewed by a human; the review date is to be filled. Four: rule R3 has no positive example in our corpus, so it is implemented but not demonstrated. Everything shown is measured, and 'verified' does not mean true."

NUMBERS: server hardware and the hours of extraction are not on the slide; if asked: i7-12700K, 96 GB, RTX 4070 12 GB (STATUS.md). Hardware per result: TBD (docs/DISCLOSURE.md).

IF IT GOES WRONG: slide only. If late, keep points 1 and 3.
-->

<!-- _class: small -->

# Disclosure and honest limits

1. **Precomputed on other hardware.** The graph extraction was run elsewhere with the same models, prompt and decoding settings; allowed by the organizers. This laptop answers questions offline.
2. **Curated facts.** The Garcia (Wisteria Lodge) facts were curated by the team, AI-assisted, and are labelled `curated` on screen and in the answer. Human re-check: pending.
3. **Gold sets written by an AI**, not yet reviewed by a human. Review date: **TBD (gold-review report)**.
4. **R3 positives are absent in the corpus** (no witness claim with person, place and time against a fact). Only 4 genuine R1 and 3 R2 cases.
5. Measured numbers only. **Verified = verbatim and lexically supported, not true.** A wrong extracted fact still passes into the rules.

---

<!--
Slide 10, 6:10-6:30 (20 s). Running total 6:30.

SAY (about 50 words):
"What is next: a human review of the gold sets and of the curated facts; the graph of all twenty stories and the measured precision of the automatic facts; contradiction precision and recall on a real graph, with intervals. The principle stays: the model guesses, the rules prove, and every step shows its quotes. Thank you; questions."

NUMBERS: none.

IF IT GOES WRONG: slide only. Then Q&A from docs/demo/jury-faq.md; backup slides B1-B6 follow.
-->

# What is next

- Human review of the gold sets and of the curated facts
- Graph of all 596 chunks; measured precision of automatic presence facts
- Contradiction precision / recall on the real graph, with intervals (**TBD, issue #16/#6**)
- Exact times and story days from text: the weak link of R1 and R3

**The model guesses. The rules prove. Every step shows its quotes.**

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
- Recording: `?replay=replay/real-boscombe-control.json` (28.7 s at original timing)

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
