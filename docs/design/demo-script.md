---
status: DRAFT 2, 2026-10-26 (rewrite of DRAFT 1; nothing was executed to write it, every number is copied from a file named next to it)
owner: demo-director + ux-designer
show date: 2026-10-30, 7 minutes, English
---
# 7-minute demo script (location: docs/design/demo-script.md)

Read with: `docs/ROADMAP.md` (schedule, risks), `docs/HANDOFF.md` (state of the code), `docs/design/board-design.md` (screen), `docs/spike/REPORT.md` and `docs/spike/results/answers-20261023-v3.md` (numbers), `docs/symbolic-layer.md` section 11.1 (Wisteria case), `eval/golden/contradictions.jsonl` (c001, c042), `eval/golden/questions.jsonl` (g001, g047).

## 0. What constrains this script

| Fact (source) | Consequence |
|---|---|
| CPU-only i7-8665U. Answer check with the real agent, qwen3:4b-instruct, 12 questions: time to first token **42.0 s end to end** (routing + retrieval + prefill + first token), 59.5 s total per question, 6.0 tok/s, 1110 prompt tokens (answers-20261023-v3.md). g001 alone: first token 49.5 s, total 54.7 s (`answers-20261023-v3-qwen3_4b-instruct.jsonl`). | Never promise 15-30 s. Every live LLM answer is preceded by about 40-50 s of waiting. That wait is filled with trace rows, quote cards and the architecture slide. |
| The retrieval gate refuses before any LLM call (0.01 s for g047). Graph queries and MCP tool calls call no LLM (`docs/mcp-contracts.md`). | These parts are fast and may be live. |
| Nothing has yet run end to end on a real extracted graph; the real graph and the real stdio MCP server over it do not exist yet (ROADMAP state of 2026-10-25, backlog R-19). | Step 2 is conditional on the Tuesday integration (section 6). Its fallbacks are named, not hoped for. |
| Cold model load 8-15 s (REPORT section 3). | Warm the model before going on stage. |

**Honesty rules (customer decisions of 2026-10-22, kept).** A pre-recorded step is called a **recording** in slides, speech and on the badge (`RECORDING`); only what really runs on the laptop during the talk is called live. A stored run of the real system (key `c`) is also announced as a stored run. A bare-LLM error is never staged; the one used here was produced by a real run (section 2, step 0). All timings below are targets until measured on Tuesday.

**Live vs recording at a glance**

| # | Time | Content | Mode |
|---|---|---|---|
| 0 | 0:00-0:30 | Bare-LLM failure on g001, then the g001 agent question | bare = **RECORDING**; agent = **LIVE** (starts at 0:02) |
| 1 | 0:30-1:30 | Architecture slide; board shows the g001 run finishing | slide; board **LIVE** |
| 2 | 1:30-3:30 | Wisteria Lodge R1 (c001), conditional finding, MCP trace | **LIVE, no LLM wait** (rules + MCP only) |
| 3 | 3:30-4:15 | Gate refusal (g047) | **LIVE**, no LLM call |
| 4 | 4:15-5:15 | Bare vs agent on g001, verbatim-quote check | bare = **RECORDING**; `rg` check **LIVE** |
| 5 | 5:15-6:15 | Measurements slide | slide |
| 6 | 6:15-7:00 | Limits and close | slide |

Order differs from DRAFT 1 only by what the customer review asked for (R1 first, no McCarthy/Crowder step, no Thor Bridge step); the one adjustment of the reviewed order is in step 1 (the architecture slide is shown for about 40 s, then the board returns for the answer, because the answer arrives at about 0:45-0:55, see step 1).

## 1. Pre-show checklist (T-10 min)

1. Laptop on mains, performance profile, other apps closed, network off, charger and cooling as in ROADMAP risks.
2. `just run` (recipe exists: `uv run python -m detective_board.api`) on the real index and graph; UI full screen at 1920x1080.
3. Warm the model with one throwaway question not on the script; wait for `llm.result`.
4. The stored run of g001 exists (for key `c`) and the stored runs for step 2 and step 3 exist as fallbacks; then restart the UI so the board is empty. (Stored runs and key `c` are backlog R-02/R-03: if not merged, the ladder skips straight to the full recording.)
5. Terminal in `/home/mendax/code/detective-board`, font 20 pt, command for step 4 in shell history.
6. Full recording (all steps) open in a second window, paused at 0:00; screenshot slides ready.
7. Operator key sheet: `c` = stored run for the current question, `Esc` = stop, `g` = list view. Clock visible to the presenter.

## 2. Running order

Fallback ladder, same for every step (details in section 4): **(1) narrate over the trace; (2) press `c` for the stored run; (3) play the full recording; (4) screenshots.**

### Step 0: Hook (0:00-0:30)

- **Exact question (agent, LIVE, typed at 0:02):** `What kind of snake killed Dr. Grimesby Roylott?` (golden g001; gold: "A swamp adder"; gold quote "It is a swamp adder!" cried Holmes; "the deadliest snake in India.", `speckled-band`).
- **Shown:** first, the **RECORDING** of the bare model (qwen3:4b-instruct, no retrieval, no system prompt, same question, temperature 0, seed 42, 2026-10-23 run; `answers-20261023-v3-BARE-qwen3_4b-instruct.jsonl`, id g001, first token 1.4 s, 300 tokens cut by the limit, 48.7 s). The screen shows the first lines, verbatim:

  > Dr. Grimesby Roylott was not killed by a snake in the story of *The Hound of the Baskervilles* or any of Arthur Conan Doyle's Sherlock Holmes stories.
  >
  > In fact, Dr. Grimesby Roylott is a character from *The Hound of the Baskervilles*, but he is not actually killed by a snake. Instead, he is a villainous character who is ultimately **murdered by a snake** — but only in a symbolic or fictional sense.
  >
  > Wait — correction: **Dr. Grimesby Roylott is not a character in *The Hound of the Baskervilles*.**

  The rest of the 300 tokens keeps contradicting itself and ends mid-word ("...he is a doctor who is **murdered"). Roylott is in *The Speckled Band*, killed by a swamp adder (g001 gold). The recording is labelled `RECORDING`, with date and model id. At 0:25 the screen switches to the board, where the agent run has been going since 0:02: trace rows, route chip, quote cards.
- **Said (about 2 sentences):** "This is a small model with no evidence, recorded earlier on this laptop: it states with confidence that Roylott was not killed by a snake, and puts him in the wrong story. Now the same question to our agent, live: you will see it work for the next forty seconds before it writes a word."
- **Live or recording:** bare = recording; agent = live.
- **Fallback ladder:** (1) if the board shows no trace row after 3 s, say "retrieval is still ranking" and keep talking; (2) `c` for the stored g001 run (announce it); (3) full recording from 0:00; (4) screenshot of the bare transcript and of the finished agent answer.
- **Pass criterion (measure Tuesday, 3 runs):** first trace row within 3 s of Enter (AC-12 target, not yet measured); retrieval quote card with `speckled-band-0030` visible before the LLM call; the recording file plays without a click delay. The bare transcript is re-recorded on Tuesday with the same settings; if it no longer shows the error, step 0 and step 4 are replaced by the quote check alone and this is said honestly (customer decision 2).

### Step 1: Architecture slide (0:30-1:30)

- **Exact question:** none (the g001 run continues in the background).
- **Shown:** one slide, three words: **LLM guesses, rules prove, real MCP.** Left: the model reads the stories and extracts facts with a verbatim quote and a confidence (label `extracted`). Middle: deterministic rules R1-R3 derive findings from those facts (label `derived`, or `conditional` when the proof rests on a shaky guess). Right: a tool server speaking the Model Context Protocol over stdio, which never calls a model. At about 1:10 the presenter returns to the board: by then the g001 answer should be on screen (first token expected near 0:45-0:55 = 0:02 + the 42-50 s measured in the answer check, writing 30 tokens at 6 tok/s = about 5 s more) with `selfcheck: verified` and the quote card.
- **Said (about 2 sentences):** "The language model only guesses: it reads and proposes facts, each with a quote, and it can be wrong. The rules and the tool server do the proving, the same way every time, and every conclusion lists the quotes it stands on. While we talked, the board finished the snake question: a swamp adder, with the sentence from the book."
- **Live or recording:** slide; the board behind it is live.
- **Fallback ladder:** (1) if the answer is late, stay on the slide and say "the model is still reading its evidence, about forty seconds is normal on this CPU", return to the board at 1:20 regardless; (2) `c` for the stored g001 run at 1:25 if still no answer; (3) full recording from 0:30; (4) screenshot of the finished answer.
- **Pass criterion (Tuesday):** on 3 runs the g001 status is `answered` with `verified` and cites `speckled-band-0030` (that is what the answer check produced: `The snake that killed Dr. Grimesby Roylott was a swamp adder [1: "It is a swamp adder!"].`), and the first token arrives no later than 0:02 + 60 s. Record the measured first-token times in section 5; if the 3-run mean is above 55 s, move the return to the board to 1:30.

### Step 2: Wisteria Lodge, rule R1 (1:30-3:30)

- **Exact question (golden contradiction c001):** `Is there a conflict about where Aloysius Garcia was at about one o'clock on the night he died?`
- **Shown (all without waiting for an LLM sentence):**
  - Trace: route chip `GRAPH + MCP (rules)`; a `tool.call` row `timeline-alibi.find_overlaps` (or `check_alibi`, whichever the router calls; name written in section 5 after rehearsal) with its arguments, then a `tool.result` row with its time in **milliseconds** (the tool never calls an LLM).
  - Board: Person node Aloysius Garcia and two events (in the bedroom at Wisteria Lodge, dead on Oxshott Common), joined by a conflict edge with the stamp `= DERIVED R1` drawn as **conditional** (dashed, `=? CONDITIONAL`, board-design 1.6).
  - Finding and Why panel (click the edge): rule R1 "one person, one place, one interval", then the numbered inputs, each with its quote and source anchor. The four gold quotes of c001 are the expected inputs: Scott Eccles "He apologised for having disturbed me so late, saying that it was nearly one o'clock." and "I could swear to it that it was he who addressed me in my bedroom at that very hour."; Inspector Baynes "He had been there since one o'clock. There was rain about that time, and his death had certainly been before the rain."; Inspector Gregson "He was found dead this morning upon Oxshott Common, nearly a mile from his home."
  - The `conditional` flag, with the doubtful input ringed.
- **Said (about 2 sentences):** "One man cannot be in his bedroom and dead a mile away at one o'clock, and the rule R1 says exactly that, listing the four quotes it used; the tool call took this many milliseconds and no model was involved. The finding is marked conditional because the proof rests on 'nearly one' and 'since one', both read as 01:00, and on a story day that we fixed by hand; if the extraction had misread the text, the rule would faithfully prove something from the misreading, which is why every input shows its quote."
  The presenter must state the hand-curated day (symbolic-layer.md 11.1: "the text says 'on the night of his death', which the day resolver does not read"). This is a conclusion that follows from the stated facts, not a claim that it is true in the story; Holmes only hints at an explanation (altered clocks), so the gold finding is the conflict, not its resolution (c001 notes).
- **Live or recording:** live, with no LLM answer needed. If the stack also starts an LLM call, the presenter does not wait for it: press `Esc` once the Why panel is open (the finding does not depend on the sentence).
- **Fallback ladder:** (1) the graph route is slow or the tool row is late: narrate "the tool call is in flight, the trace shows its arguments", up to 6 s; (2) `c` for the stored c001 run (RECORDING badge, announced); (3) full recording from 1:30; (4) screenshots of the finding, the Why panel and the trace. Named fallback if the real stdio MCP over the real graph is not merged by Tuesday 12:00 (ROADMAP risk): serve the stdio server from the single-story FactBase file for Wisteria Lodge and say "this server holds one story"; if the real R1 finding is not `violated` on the real graph, use the stored run and say so.
- **Pass criterion (Tuesday):** on 3 runs against the real graph, R1 returns `violated` for the Garcia pair, flagged conditional, with at least the Eccles "nearly one" quote and the Baynes "since one" quote as inputs; the MCP `tool.result` time is under 5 s (the tool timeout) and the measured value is written in ms in section 5; the Why panel opens; no LLM call is needed for the finding. Also record whether the router sends this question to the graph route (HANDOFF: the router has no graph step for contradiction questions yet).

### Step 3: Live gate refusal (3:30-4:15)

- **Exact question (golden g047):** `What was the creature that haunted the Baskerville family on the Devonshire moor?`
- **Why this question (checked in the files):** the answer check shows g047 refused by the retrieval gate **before any LLM call**: reason "top chunks cover 0.17 of the question terms, need 0.25", total 0.01 s, answer text "In these materials there is nothing about this." (`answers-20261023-v3-qwen3_4b-instruct.jsonl`); `rg -il baskerville data/clean` returns no file (re-run before the show). The other out-of-corpus golden question g056 (Colonel Ross's fee) is **not** usable live: it passed the gate and cost an LLM call of 47 s, then declined. The DRAFT 1 question (Reichenbach / Moriarty) has **not been run through the gate** and is uncertain (Moriarty is mentioned once in the corpus, `norwood-builder-0000`, which can raise the support score); it is therefore not the live question. If it is tried on Tuesday and the gate refuses it with no LLM call, it may replace g047; the named fallback is g047.
- **Shown:** `run.start`, route chip, a `refusal` row with the gate reason and scores, the "Searched" list, no `llm.call` row, indigo refusal banner; the board stays empty. The bare model, asked the same thing, answered from memory ("a large, spectral hound", `answers-20261023-v3-BARE-qwen3_4b-instruct.jsonl`, g047): this is canon knowledge, not corpus evidence, and the presenter calls it exactly that, not a hallucination.
- **Said (about 2 sentences):** "This question is about a famous novel that is not among our 20 stories. The agent checks whether its evidence covers the question, finds it does not, and refuses in a hundredth of a second without calling the model; a bare model happily tells the story from memory."
- **Live or recording:** live.
- **Fallback ladder:** (1) if the refusal row is late, narrate the gate ("it is ranking, then checking coverage"); (2) `c` for the stored refusal; (3) full recording from 3:30; (4) screenshot. If the live run does NOT refuse and calls the LLM: press `Esc`, press `c`, and say plainly that the thresholds are provisional (R-13) and this live run missed.
- **Pass criterion (Tuesday, 3 runs on the real index):** status `refused`, code `no_evidence`, no `llm.call`, total under 1 s. Re-check after the R-13 threshold tuning, because min_score 0.018 and min_support 0.25 may change.

### Step 4: Bare vs agent, and the verbatim-quote check (4:15-5:15)

- **Exact question:** `What kind of snake killed Dr. Grimesby Roylott?` (same as step 0).
- **Shown:** side by side, the bare **RECORDING** from step 0 (labelled) and the agent's finished g001 answer from step 0 (the live run, or the stored one if `c` was used, labelled). Then the live check in the terminal, which is the part that does not depend on trusting anyone:
  1. `rg -F "It is a swamp adder!" data/clean/speckled-band.txt` prints the book line (checked on 2026-10-26: one hit): the agent's quote is a verbatim substring.
  2. `rg -il "baskerville" data/clean` prints nothing (checked on 2026-10-26: no file): the bare answer set Roylott in a book that is not in the corpus.
  Both commands take about 1 s. The board's `selfcheck: quotes verified n/n` row is shown next to the terminal.
- **Said (about 2 sentences):** "The bare model's answer is fluent and wrong; the agent's answer is one sentence with a quote that you can find in the book with a one-second search. 'Verified' here means the quote is verbatim and lexically supports the claim, not that the claim is true; the check is mechanical, and I will say below what it does not cover."
  One question, one run: not a rate. The measured comparison is on the next slide; on the three out-of-corpus and adversarial questions the bare model behaved as required on 1 of 3, the agent on 2 of 3 (answers-20261023-v3.md).
- **Live or recording:** bare = recording; agent answer = the step 0 run; `rg` commands = live.
- **Fallback ladder:** (1) terminal slow: run the first command only; (2) `c` for the stored agent run; (3) full recording from 4:15; (4) screenshot of the terminal output.
- **Pass criterion (Tuesday):** both `rg` commands give the stated result on the demo laptop (path and file names correct, text file present offline); the bare recording and the agent answer are on screen together without a window-switch longer than 3 s.

### Step 5: Measurements slide (5:15-6:15)

- **Exact question:** none.
- **Shown:** one slide with the numbers below and their caveats on the same slide. Every row names its file.

| What | Number | Caveat on the slide | File |
|---|---|---|---|
| 12-question answer check, qwen3:4b-instruct, retrieval-only path | behaviour correct 8/12; answered and verified 5 of 10 answerable; gold chunk cited 5/10; gate-refused without LLM 2/12; first token 42.0 s, total 59.5 s | n=12, one run, no human judging, AI-written gold set, graph and MCP off, so this is not a test of the rules | `answers-20261023-v3.md` |
| Control c042 (McCarthy vs gamekeeper, "following my father") | the rules do **not** flag it: gold says it is not a conflict of observed facts | regression test on the real quotes, not yet run on a real extracted graph; gold itself is low-confidence and a labelling decision for a human | `eval/golden/contradictions.jsonl`; `docs/symbolic-layer.md` 11.1 |
| Retrieval pilot, hybrid RRF k=30, bge-m3 | hit@5 0.97 on 35 questions; the gold chunk is in the top 4 for 70 of 86 answerable questions (81%) | tuned on the same questions, so optimistic; pilot | `arms-20261023-080849.md`; `evidence-20261023-093201.md` |
| Extraction pilot, qwen3:4b | strict F1 entities 0.55, claims 0.31, relations 0.18 on 12 chunks; 6.6% of qwen3:4b quotes are not verbatim (1 - 0.934; 7-21% across the six models) and are dropped or re-anchored | 12 chunks, AI-labelled gold, differences are noise | `REPORT.md` section 6 |
| Precompute | the full-corpus extraction is 24-30 h of exclusive CPU (projection 29.7 h for qwen3:4b = 596 chunks x 179.7 s); it is run on **stronger hardware**, not on this laptop, and the finished graph is shipped to the laptop (state on the day: written in section 5) | disclosed on stage; this laptop only answers questions | `REPORT.md` section 7; `HANDOFF.md` section 3 |

  Add to the slide only after Tuesday, from the actual runs: the contradiction precision/recall and the A/B table of `eval/run_eval.py` (it does not exist today). If they do not exist on Tuesday, the slide shows only the rows above and says "not yet measured".
- **Said (about 2 sentences):** "These are pilot numbers on small sets that an AI wrote, so a difference of one question is noise: five of ten answerable questions answered and verified, retrieval puts the right chunk in the top four for about four in five. The rules do not flag the control case where two witnesses differ only about intent, and the graph itself is precomputed on stronger machines because extraction takes 24 to 30 hours on this CPU."
- **Live or recording:** slide.
- **Fallback ladder:** (1) skip the caveat column aloud but keep it on the slide; (2) n/a (no run); (3) n/a; (4) the same slide as a PDF.
- **Pass criterion:** every number on the slide equals the cited file (a pre-show `rg` of each number against its file; list kept in section 5); the permission to precompute on other hardware has been asked of the organizers (ROADMAP, Sunday) and the answer is written in section 5, or the slide says "asked, no answer".

### Step 6: Limits and close (6:15-7:00)

- **Exact question:** none.
- **Shown:** one slide, five limits and one sentence: (1) the real extracted graph and the real MCP over it were integrated only on Tuesday; (2) the gold sets were written by an AI and are not human-reviewed; (3) only 4 genuine R1 cases and 3 R2 cases exist in the corpus, so the rules are demonstrated, not statistically validated; (4) a small model: the answer prompts are short (1110 tokens) for speed; (5) "verified" means verbatim and lexically supported, not true. Close: "Everything you saw ran on this laptop with the network off; the graph was precomputed on other hardware."
- **Said (about 2 sentences):** "What it does not do: it cannot tell you a quote is true, only that it is in the book and supports the sentence, and when the model misreads a story, the rules reason faithfully from the misreading. What it does do is show every step, every quote and every condition, so that you can check it in a second."
- **Live or recording:** slide.
- **Fallback ladder:** none needed; if late, say limits (2) and (5) only.
- **Pass criterion:** finishes at or before 7:00 in all three rehearsals; no number on the slide that is not in section 5's checklist.

## 3. Removed and why

- **McCarthy vs Crowder rule step (DRAFT 1 step 2).** Gold c042 (Boscombe Valley) is a *consistent control*: both witnesses agree James went the same way with a gun; they differ only about whether he was deliberately following, which Crowder gives as his belief. The rules correctly do **not** flag it (symbolic-layer.md 11.1), so a step called "contradiction" would either show nothing or be a lie. It moves to the measurements slide (and to the FAQ) as the control the rules pass. Gold note: c042 is low-confidence and conflicts in spirit with g027, which treats the pair as a conflict between accounts; a human has to decide the label.
- **Thor Bridge alibi step (DRAFT 1 step 3).** The expected `check_alibi` status was never recorded, the extraction and time normalisation for the story were unverified, and the quotes depend on the text's double spaces; the "late in the evening" death time is vague, so `unknown` was the likely result. It would have used the longest LLM wait of the demo for a result we could not predict. Its role (a real MCP call visible in ms) is taken by step 2.
- **Dog in the night-time step (DRAFT 1 step 1)** and the **Reichenbach step**: replaced by the hook and the g047 refusal. Reichenbach stays a possible swap for step 3 only if Tuesday shows the gate refuses it without an LLM call.
- **Segment 5b (guess vs prove)** is folded into the architecture slide and step 2.

## 4. Fallback ladder (applies to every step)

1. Narrate over the trace. The waiting counter proves it is working. Allowed: 6 s of silence from the screen, 25 s in the LLM-writing phase (never longer than the architecture slide covers in step 1).
2. Press `c`: stored run, badge `RECORDING`, say "this one is a stored run".
3. Play the full recording at the matching timestamp (step start times as in section 0).
4. Screenshot slides.
Never: re-ask the same question hoping for a different answer; blame the model; show an unverified quote as verified; call a stored run live.

## 5. Rehearsal plan and log

**Run 0, Tuesday 2026-10-27 (integration day, target laptop, nothing else running):** measure every pass criterion above, three times each, and fill the log. Pick or reject the Reichenbach swap. Re-record the bare g001 transcript.

**Rehearsal 1, Thursday 2026-10-29:** full run with a timer, all live parts live, recordings as recordings; record per-step times and every intervention. Fix wording and fallbacks. **Rehearsal 2, Thursday 2026-10-29 (second laptop or after a reboot):** same, and in addition force one failure per step (disconnect the tool, kill Ollama mid-prefill) to practise rungs 2-4. **Rehearsal 3, Friday 2026-10-30 morning, on the show laptop:** exact setup, offline, charger, thermal check; a clean run under 7:00 with no intervention is the go criterion (ROADMAP G4/G5). Also rehearse the 5-minute cut once.

| Run | Date | Step 0 first trace row (s) | Step 1 g001 first token (s) | Step 2 R1 result, MCP ms, conditional? | Step 3 refusal, ms | Step 4 rg results | Total | Interventions |
|---|---|---|---|---|---|---|---|---|
| 0 | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| 1 | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| 2 | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| 3 | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |

Number checklist for the slides (each filled with the file hit): TBD.

## 6. Dependencies to verify on Tuesday (blocking for step 2)

1. `graph.sqlite` built from the real extraction, with Garcia, Scott Eccles, Baynes and Gregson and their events and quotes for Wisteria Lodge; the day of the two events resolved (hand-curated, disclosed).
2. Real stdio MCP server over the graph (R-19) merged; otherwise the single-story FactBase server and the sentence "this server holds one story".
3. A router path from the c001 question to the graph route (HANDOFF section 4, item 3).
4. R1 on the real graph returns `violated`, conditional (the unit test uses the curated passage only).
5. Stored runs, `c` key, `RECORDING` badge (R-02/R-03) merged; otherwise rungs 2 is replaced by rung 3.
6. Permission on precompute on other hardware: asked of the organizers (ROADMAP); the stage statement is made regardless.

## 7. Five-minute cut

Use when the slot is shortened or rehearsal 2 runs over. Same steps, same fallbacks; only the lengths change.

| Time | Content | Cut |
|---|---|---|
| 0:00-0:30 | Hook: bare RECORDING on g001, start the live agent question | none |
| 0:30-1:00 | Architecture slide, 30 s; return to board at 0:50 for the answer | slide shortened to the three words |
| 1:00-2:45 | Wisteria R1 (1:45): trace in ms, finding, Why panel with two quotes (Eccles, Baynes), conditional flag | show two of the four quotes; keep the hand-curated-day sentence |
| 2:45-3:15 | Gate refusal g047 | none |
| 3:15-4:00 | Bare vs agent merged with the check: skip replaying the bare recording (already seen at 0:00); run only the `rg -F "It is a swamp adder!"` check | second `rg` and the side-by-side dropped |
| 4:00-4:40 | Measurements slide: only the 12-question row, c042, and precompute | retrieval and extraction pilot rows stay on the slide, not spoken |
| 4:40-5:00 | Limits (2), (5) and the close sentence | other limits stay on the slide |

Cut order inside the full version if running late: (1) step 5 spoken caveats, (2) the second `rg` in step 4, (3) the Why panel quotes beyond two. Never cut: step 2 (the rules and the MCP trace), step 3 (honest refusal), the "verified does not mean true" sentence.
