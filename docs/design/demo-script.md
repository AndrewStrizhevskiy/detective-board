---
status: DRAFT 4, 2026-10-27 (adds section 2a, operator cards matched to the 6:30 deck in docs/slides/deck.md; DRAFT 3 text below is kept; DRAFT 2 updated to the final behaviour: extractive answers, rule-first, curated facts; nothing was executed to write it, every number is copied from a file named next to it)
owner: demo-director + ux-designer
show date: 2026-10-30, 7-minute slot, deck timed to 6:30, English
---
# 7-minute demo script (location: docs/design/demo-script.md)

**Which timing wins.** The deck `docs/slides/deck.md` is timed to 6:30 (slots: 0:35, 0:30, 0:35, 0:50, 1:10, 0:35, 0:50, 0:25, 0:40, 0:20). Section 2a below maps the steps of section 2 onto the deck and gives, per step, the live path, the recording fallback, the spoken line and the failure line. The step times in section 0 and 2 are the DRAFT 3 targets for a 7:00 run and are superseded by 2a where they differ.

Read with: `docs/ROADMAP.md` (schedule, risks), `docs/HANDOFF.md` (state of the code), `docs/design/board-design.md` (screen), `docs/spike/REPORT.md` and `docs/spike/results/answers-20261023-v3.md` (numbers), `docs/symbolic-layer.md` sections 11.1 and 11.4 (Wisteria case, curated facts), ADR-0009..0011, `docs/spike/results/api12-20261027-extractive.md`, `eval/golden/contradictions.jsonl` (c001, c042), `eval/golden/questions.jsonl` (g001, g047).

## 0. What constrains this script

| Fact (source) | Consequence |
|---|---|
| CPU-only i7-8665U; prefill about 21 tokens/s, only the system-prefix cache helps (`docs/perf/ttft-levers-2026-10-26.md`). The generative answer took 42.0 s to the first token and 59.5 s per question in the 2026-10-23 check (`answers-20261023-v3.md`) and 45.7-140.8 s in the real-API run of 2026-10-27 (`api12-20261027-generative.md`). | **LLM composition is no longer in the demo path.** Text answers use the extractive mode (the model only chooses numbered sentences; ADR-0009): 8.1-20.2 s per question in the 12-question run (`api12-20261027-extractive.md`), g001 9.3 s there and 10.8 s in the recording `web/replay/real-g001-agent.json`. The time-to-first-token worry of DRAFT 2 is gone for the main steps; the fallback ladder stays. |
| The retrieval gate refuses before any LLM call (0.01 s for g047). Graph queries and MCP tool calls call no LLM (`docs/mcp-contracts.md`). | These parts are fast and may be live. |
| The real stack ran on 2026-10-27 on the laptop (real index, graph of 20 stories and 596 chunks from the department-server run (2026-10-27), curated demo facts, real Ollama); five real recordings exist (`web/replay/real-*.json`, commit d9709d0). On real data the rules find nothing automatically (no exact times or days); the Wisteria R1 finding rests on curated facts (ADR-0011). | Step 2 shows a curated-fact finding and says so. Its fallbacks are named, not hoped for. |
| Cold model load 8-15 s (REPORT section 3). | Warm the model before going on stage. |

**Honesty rules (customer decisions of 2026-10-22, kept).** The Wisteria finding is built on curated facts and is called that, on the slide, in speech and in the answer (`Curated:` line). A pre-recorded step is called a **recording** in slides, speech and on the badge (`RECORDING`); only what really runs on the laptop during the talk is called live. A stored run of the real system (key `c`) is also announced as a stored run. A bare-LLM error is never staged; the one used here was produced by a real run (section 2, step 0). All timings below are targets until measured on Tuesday.

**Live vs recording at a glance**

| # | Time | Content | Mode |
|---|---|---|---|
| 0 | 0:00-0:30 | Bare-LLM failure on g001, then the g001 agent question | bare = **RECORDING**; agent = **LIVE** (starts at 0:02, answer in about 30 s on this laptop: 25-43 s measured, `docs/perf/laptop-20261028.md`; narrate over the trace or press `c`) |
| 1 | 0:30-1:30 | Architecture slide; board shows the finished g001 answer | slide; board **LIVE** |
| 2 | 1:30-3:30 | Wisteria Lodge R1 (c001), conditional finding on **curated** facts, MCP trace | **LIVE, instant** (rules + MCP only, no LLM) |
| 3 | 3:30-4:15 | Gate refusal (g047) | **LIVE**, no LLM call |
| 4 | 4:15-5:15 | Bare vs agent on g001, verbatim-quote check | bare = **RECORDING**; `rg` check **LIVE** |
| 5 | 5:15-6:15 | Measurements slide | slide |
| 6 | 6:15-7:00 | Limits and close | slide |

Order differs from DRAFT 1 only by what the customer review asked for (R1 first, no McCarthy/Crowder step, no Thor Bridge step). Since the extractive mode the g001 answer is on the board at about 0:12-0:15, so the architecture slide no longer has to cover a 40-50 s wait; it is shown for about 40 s and the board then simply shows the finished answer. No step of the main path waits for an LLM to write text.

## 1. Pre-show checklist (T-10 min)

1. Laptop on mains, performance profile, other apps closed, network off, charger and cooling as in ROADMAP risks.
2. `just run` (recipe exists: `uv run python -m detective_board.api`) on the real index and graph; UI full screen at 1920x1080.
3. Warm the model with one throwaway question not on the script (the extractive selection call still needs the model resident; cold load 8-15 s, REPORT section 3).
4. The recordings exist in `web/replay/` (`real-g001-agent.json`, `real-wisteria-r1-curated.json`, `real-refusal-baskerville.json`, `real-boscombe-control.json`, `real-refusal-fee.json`) and serve as the stored runs for key `c` (listed in `web/replay/index.json`, regenerated with `python3 scripts/replay_index.py` after every `scripts/record_run.py`); then reload the UI so the board is empty. Check the **Recordings** menu in the header lists them. If key `c` fails, rung 2 is the `?replay=` URL of section 2a in a second browser tab.
5. Terminal in `/home/mendax/code/detective-board`, font 20 pt, command for step 4 in shell history.
6. Full recording (all steps) open in a second window, paused at 0:00; screenshot slides ready.
7. Operator key sheet: `c` = stored run for the current question (badge `RECORDING`, gaps over 2 s shortened), `c` again = back to live, `Esc` = stop, `g` = list view. After Enter the question box releases the keyboard, so `c` works during a live run. If the live run gets no data for 90 s the screen says "Connection lost" and offers the stored run of the same question. Clock visible to the presenter.

## 2. Running order

Fallback ladder, same for every step (details in section 4): **(1) narrate over the trace; (2) press `c` for the stored run; (3) play the full recording; (4) screenshots.**

### Step 0: Hook (0:00-0:30)

- **Exact question (agent, LIVE, typed at 0:02, answered in about 30 s: 25-43 s measured):** `What kind of snake killed Dr. Grimesby Roylott?` (golden g001; gold: "A swamp adder"; gold quote "It is a swamp adder!" cried Holmes; "the deadliest snake in India.", `speckled-band`).
- **Shown:** first, the **RECORDING** of the bare model (qwen3:4b-instruct, no retrieval, no system prompt, same question, temperature 0, seed 42, 2026-10-23 run; `answers-20261023-v3-BARE-qwen3_4b-instruct.jsonl`, id g001, first token 1.4 s, 300 tokens cut by the limit, 48.7 s). The screen shows the first lines, verbatim:

  > Dr. Grimesby Roylott was not killed by a snake in the story of *The Hound of the Baskervilles* or any of Arthur Conan Doyle's Sherlock Holmes stories.
  >
  > In fact, Dr. Grimesby Roylott is a character from *The Hound of the Baskervilles*, but he is not actually killed by a snake. Instead, he is a villainous character who is ultimately **murdered by a snake** — but only in a symbolic or fictional sense.
  >
  > Wait — correction: **Dr. Grimesby Roylott is not a character in *The Hound of the Baskervilles*.**

  The rest of the 300 tokens keeps contradicting itself and ends mid-word ("...he is a doctor who is **murdered"). Roylott is in *The Speckled Band*, killed by a swamp adder (g001 gold). The recording is labelled `RECORDING`, with date and model id. At 0:25 the screen switches to the board, where the agent run (started at 0:02) has already finished: route chip, retrieval quote card, the answer `From the sources: [1: "“It is a swamp adder!” cried Holmes; “the deadliest snake in India."]` (extractive mode: the model chose that sentence from a numbered list; the text is verbatim by construction). Timing: 9.3 s in the 12-question run, 10.8 s in the recording `web/replay/real-g001-agent.json`.
- **Said (about 2 sentences):** "This is a small model with no evidence, recorded earlier on this laptop: it states with confidence that Roylott was not killed by a snake, and puts him in the wrong story. Now the same question to our agent, live: in about ten seconds it picks one sentence from the book and shows it, word for word."
- **Live or recording:** bare = recording; agent = live.
- **Fallback ladder:** (1) if the board shows no trace row after 3 s, say "retrieval is still ranking" and keep talking; (2) `c` for the stored g001 run (`real-g001-agent.json`, announce it); (3) full recording from 0:00; (4) screenshot of the bare transcript and of the finished agent answer.
- **Pass criterion (measure Tuesday, 3 runs):** first trace row within 3 s of Enter (AC-12 target, not yet measured); status `answered`, the swamp-adder sentence cited from `speckled-band-0030`, total under 20 s (one run so far: 9.3 s and 10.8 s; the 4B model is wording-sensitive, so the selection prompt must not be edited; if g001 returns NONE use `c`); the recording file plays without a click delay. The bare transcript is re-recorded on Tuesday with the same settings; if it no longer shows the error, step 0 and step 4 are replaced by the quote check alone and this is said honestly (customer decision 2).

### Step 1: Architecture slide (0:30-1:30)

- **Exact question:** none (the g001 answer is already on the board).
- **Shown:** one slide, three words: **LLM guesses, rules prove, tools behind MCP.** Left: the model reads the stories and extracts facts with a verbatim quote and a confidence (label `extracted`). Middle: deterministic rules R1-R3 derive findings from those facts (label `derived`, or `conditional` when the proof rests on a shaky guess). Right: the tool functions that an MCP server exposes (`check_alibi`, `find_contradictions`); the agent calls them over stdio (subprocess `timeline-alibi`) against the graph; the tools never call a model. At about 1:10 the presenter returns to the board, where the g001 answer has been on screen since about 0:12 with `selfcheck: verified` and the quote card.
- **Said (about 2 sentences):** "The language model only guesses: it reads and proposes facts, each with a quote, and it can be wrong. The rules and the tool server do the proving, the same way every time, and every conclusion lists the quotes it stands on. The snake question you saw a minute ago was answered that way: the model only picked a sentence, the sentence is the book's own."
- **Live or recording:** slide; the board behind it is live.
- **Fallback ladder:** (1) if the answer is not on the board, stay on the slide and say "the model is still choosing its sentence, about ten to twenty seconds is normal on this CPU", return to the board at 1:20 regardless; (2) `c` for the stored g001 run at 1:25 if still no answer; (3) full recording from 0:30; (4) screenshot of the finished answer.
- **Pass criterion (Tuesday):** on 3 runs the g001 status is `answered` with `verified` and cites `speckled-band-0030` with the sentence "It is a swamp adder!" cried Holmes (as in the recording), total under 20 s. Record the measured totals in section 5.

### Step 2: Wisteria Lodge, rule R1 (1:30-3:30)

- **Exact question (golden contradiction c001):** `Is there a conflict about where Aloysius Garcia was at about one o'clock on the night he died?`
- **Shown (all without waiting for an LLM sentence):**
  - Trace: route chip `GRAPH + MCP (rules)`; a `tool.call` row `timeline-alibi.find_overlaps` (or `check_alibi`, whichever the router calls; the recording shows `find_contradictions`; the measured ms are written in section 5 after rehearsal) with its arguments, then a `tool.result` row with its time in **milliseconds** (the tool never calls an LLM).
  - Board: Person node Aloysius Garcia and two events (in the bedroom at Wisteria Lodge, dead on Oxshott Common), joined by a conflict edge with the stamp `= DERIVED R1` drawn as **conditional** (dashed, `=? CONDITIONAL`, board-design 1.6).
  - Finding and Why panel (click the edge): rule R1 "one person, one place, one interval", then the numbered inputs, each with its quote, its source anchor and the word **(curated)** in its summary. With the curated facts the inputs are two quotes: Scott Eccles "Some time later Garcia looked in at my door ... saying that it was nearly one o'clock." and Inspector Baynes "He had been there since one o'clock. There was rain about that time, and his death had certainly been before the rain." (The other gold quotes of c001, Eccles "I could swear ... at that very hour" and Gregson "found dead this morning upon Oxshott Common", are the context a reader needs to resolve "he" and "there"; they are not rule inputs.)
  - **Slide text for this step: "Curated facts: checked by the team, AI-assisted, human re-check done by LitrumCoder on 2026-10-29. The automatic extraction is measured separately (slide: measurements)."** The curated marker is on screen three ways: the answer text ends with the line `Curated: 2 of the facts it rests on were entered and checked by the team (AI-assisted, human re-check done by LitrumCoder on 2026-10-29); they are not output of the automatic extraction.`, the input summaries in the Why panel end in `(curated)`, and the slide carries the word. (There is no separate badge on the board node; if one is added, update this line.) The recording `web/replay/real-wisteria-r1-curated.json` shows exactly this run (0.3 s).
  - The `conditional` flag, with the doubtful input ringed.
- **Said (about 3 sentences):** "For this case the facts are curated: our team wrote them down from the book, with the quote for each, because the small model we run cannot yet tell who 'he' is in these sentences; it is on the slide and in the Why panel, and the automatic numbers come later, measured separately. One man cannot be in his bedroom and dead a mile away at one o'clock, and the rule R1 says exactly that, listing the two quotes it used; the tool call took this many milliseconds and no model was involved. The finding is marked conditional because the proof rests on 'nearly one' and 'since one', both read as 01:00, and on two places that we resolved by hand from the sentences before; if we had misread the text, the rule would faithfully prove something from the misreading, which is why every input shows its quote."
  On real extracted data alone this finding does not appear: the automatic pipeline has no exact times or days (first real run: 0 exact times, 0 days, 1 usable proposition, R1 examined 19 pairs and could not decide 16; REPORT Addendum A2), and the presenter says so if asked. The presenter must say the word "curated" aloud and name the hand-resolved parts (the day key and the "he"/"there" of the Baynes line; symbolic-layer.md 11.4). Never present this finding as something the model found. This is a conclusion that follows from the stated facts, not a claim that it is true in the story; Holmes only hints at an explanation (altered clocks), so the gold finding is the conflict, not its resolution (c001 notes).
- **Live or recording:** live and instant (0.3 s in the recording). Contradiction and alibi questions are answered rule-first (`AgentConfig.rule_first`): the sentence is a template over the finding, streamed at once, and no model is called, so there is no 40-60 s wait and nothing to interrupt. The same question on a graph where the rule finds nothing yields the honest sentence "The rule engine found no violation ... This does not show that the accounts are consistent" with coverage numbers, never "no conflict".
- **Fallback ladder:** (1) the graph route is slow or the tool row is late: narrate "the tool call is in flight, the trace shows its arguments", up to 6 s; (2) `c` for the stored c001 run (RECORDING badge, announced); (3) full recording from 1:30; (4) screenshots of the finding, the Why panel and the trace. Named fallback if the real stdio MCP over the real graph is not merged by Tuesday 12:00 (ROADMAP risk): serve the stdio server from the single-story FactBase file for Wisteria Lodge and say "this server holds one story"; if the real R1 finding is not `violated` on the real graph, use the stored run and say so.
- **Pass criterion (Tuesday):** on 3 runs against the real graph, R1 returns `violated` for the Garcia pair, flagged conditional, with at least the Eccles "nearly one" quote and the Baynes "since one" quote as inputs; the MCP `tool.result` time is under 5 s (the tool timeout) and the measured value is written in ms in section 5; the Why panel opens; no LLM call is made (the `enriched_query` row says `rule-first`) and the answer appears within a second. Also record whether the router sends this question to the graph route (HANDOFF: the router has no graph step for contradiction questions yet).

### Step 3: Live gate refusal (3:30-4:15)

- **Exact question (golden g047):** `What was the creature that haunted the Baskerville family on the Devonshire moor?`
- **Why this question (checked in the files):** the recording `web/replay/real-refusal-baskerville.json` shows g047 refused in 0.2 s; the 2026-10-23 answer check shows g047 refused by the retrieval gate **before any LLM call**: reason "top chunks cover 0.17 of the question terms, need 0.25", total 0.01 s, answer text "In these materials there is nothing about this." (`answers-20261023-v3-qwen3_4b-instruct.jsonl`); `rg -il baskerville data/clean` returns no file (re-run before the show). The other out-of-corpus golden question g056 (Colonel Ross's fee) is **not** a gate refusal: it passes the gate, the model is called and chooses NONE, so it is refused plainly but only after 15.7 s (recording `web/replay/real-refusal-fee.json`; 19.4 s in the 12-question run). In the generative mode it used to degrade into "closest passages"; the extractive mode fixed that (ADR-0009). It is a usable second refusal only if time allows. The DRAFT 1 question (Reichenbach / Moriarty) has **not been run through the gate** and is uncertain (Moriarty is mentioned once in the corpus, `norwood-builder-0000`, which can raise the support score); it is therefore not the live question. If it is tried on Tuesday and the gate refuses it with no LLM call, it may replace g047; the named fallback is g047.
- **Shown:** `run.start`, route chip, a `refusal` row with the gate reason and scores, the "Searched" list, no `llm.call` row, indigo refusal banner; the board stays empty. The bare model, asked the same thing, answered from memory ("a large, spectral hound", `answers-20261023-v3-BARE-qwen3_4b-instruct.jsonl`, g047): this is canon knowledge, not corpus evidence, and the presenter calls it exactly that, not a hallucination.
- **Said (about 2 sentences):** "This question is about a famous novel that is not among our 20 stories. The agent checks whether its evidence covers the question, finds it does not, and refuses in a hundredth of a second without calling the model; a bare model happily tells the story from memory."
- **Live or recording:** live.
- **Fallback ladder:** (1) if the refusal row is late, narrate the gate ("it is ranking, then checking coverage"); (2) `c` for the stored refusal; (3) full recording from 3:30; (4) screenshot. If the live run does NOT refuse and calls the LLM: press `Esc`, press `c`, and say plainly that the thresholds are provisional (R-13) and this live run missed.
- **Pass criterion (Tuesday, 3 runs on the real index):** status `refused`, code `no_evidence`, no `llm.call`, total under 1 s. Re-check after the R-13 threshold tuning, because min_score 0.018 and min_support 0.25 may change.

### Step 4: Bare vs agent, and the verbatim-quote check (4:15-5:15)

- **Exact question:** `What kind of snake killed Dr. Grimesby Roylott?` (same as step 0).
- **Shown:** side by side, the bare **RECORDING** from step 0 (labelled) and the agent's finished g001 answer from step 0 (the live run, or the stored one if `c` was used, labelled). On the board this is key `b`: the bare answer (`web/replay/bare/g001.json`, NO SOURCES, RECORDING) takes the trace column next to the agent's board and answer (`docs/demo/bare-vs-agent.md`). Then the live check in the terminal, which is the part that does not depend on trusting anyone:
  1. `rg -F "It is a swamp adder!" data/clean/speckled-band.txt` prints the book line (checked on 2026-10-26: one hit): the agent's quote is a verbatim substring. In extractive mode the answer IS that sentence, so the check shows the whole answer is the book's text.
  2. `rg -il "baskerville" data/clean` prints nothing (checked on 2026-10-26: no file): the bare answer set Roylott in a book that is not in the corpus.
  Both commands take about 1 s. The board's `selfcheck: quotes verified n/n` row is shown next to the terminal.
- **Said (about 2 sentences):** "The bare model's answer is fluent and wrong; the agent's answer is one sentence from the book that you can find with a one-second search. 'Verified' here means the quote is verbatim and lexically supports the claim, not that the claim is true; the check is mechanical, and I will say below what it does not cover."
  One question, one run: not a rate. The measured comparison is on the next slide; on the three out-of-corpus and adversarial questions the bare model behaved as required on 1 of 3, the agent on 2 of 3 (answers-20261023-v3.md).
- **Live or recording:** bare = recording; agent answer = the step 0 run; `rg` commands = live.
- **Fallback ladder:** (1) terminal slow: run the first command only; (2) `c` for the stored agent run; (3) full recording from 4:15; (4) screenshot of the terminal output.
- **Pass criterion (Tuesday):** both `rg` commands give the stated result on the demo laptop (path and file names correct, text file present offline); the bare recording and the agent answer are on screen together without a window-switch longer than 3 s.

### Step 5: Measurements slide (5:15-6:15)

- **Exact question:** none.
- **Shown:** one slide with the numbers below and their caveats on the same slide. Every row names its file.

| What | Number | Caveat on the slide | File |
|---|---|---|---|
| Real-API run of the same 12 questions, 2026-10-27, graph on, curated facts loaded | generative path: 45.7-140.8 s per model-calling question, refusals of g056/g057 degraded to "closest passages"; extractive path: 8.1-20.2 s, g001 answered, g047/g056/g057 refused, g007 and g016 still refused (NONE), g062 refused by the gate | n=12, one run, "answered" is not "correct", no human judging, the 4B model is wording-sensitive | `api12-20261027-generative.md`, `api12-20261027-extractive.md` |
| 12-question answer check, qwen3:4b-instruct, retrieval-only path (older, generative) | behaviour correct 8/12; answered and verified 5 of 10 answerable; gold chunk cited 5/10; gate-refused without LLM 2/12; first token 42.0 s, total 59.5 s | n=12, one run, no human judging, AI-written gold set, graph and MCP off, so this is not a test of the rules | `answers-20261023-v3.md` |
| Control c042 (McCarthy vs gamekeeper, "following my father") | the rules do **not** flag it: gold says it is not a conflict of observed facts. The control is weaker than its label: the disagreement is about intent, which no rule checks | regression test on the real quotes and three curated Boscombe facts, not a real extracted graph; gold itself is low-confidence and a labelling decision for a human | `eval/golden/contradictions.jsonl`; `docs/symbolic-layer.md` 11.1 |
| Retrieval pilot, hybrid RRF k=30, bge-m3 | hit@5 0.97 on 35 questions; the gold chunk is in the top 4 for 70 of 86 answerable questions (81%) | tuned on the same questions, so optimistic; pilot | `arms-20261023-080849.md`; `evidence-20261023-093201.md` |
| Real extraction readiness (first real run, wisteria-lodge, after repair) | 107 events, 137 claims, 0 exact times, 0 story days, 1 usable proposition; R1 examined 19 pairs, could not decide 16 | one story; the automatic rules find nothing on real data, which is why the demo case uses curated facts; precision of automatic presence facts unmeasured | `symbolic-layer.md` 11.1a, `REPORT.md` Addendum A2 |
| Extraction pilot, qwen3:4b | strict F1 entities 0.55, claims 0.31, relations 0.18 on 12 chunks; 6.6% of qwen3:4b quotes are not verbatim (1 - 0.934; 7-21% across the six models) and are dropped or re-anchored | 12 chunks, AI-labelled gold, differences are noise | `REPORT.md` section 6 |
| Precompute | the full-corpus extraction is 24-30 h of exclusive CPU (projection 29.7 h for qwen3:4b = 596 chunks x 179.7 s); it is run on **stronger hardware**, not on this laptop, and the finished graph is shipped to the laptop (state on the day: written in section 5) | disclosed on stage; this laptop only answers questions | `REPORT.md` section 7; `HANDOFF.md` section 3 |

  Add to the slide only after the server run, from the actual runs: the contradiction precision/recall and the A/B table of `eval/run_eval.py` (the runner exists, issue #6; its numbers need the real run on dev, then the frozen test split). If they do not exist on Tuesday, the slide shows only the rows above and says "not yet measured".
- **Said (about 2 sentences):** "These are pilot numbers on small sets that an AI wrote, so a difference of one question is noise: five of ten answerable questions answered and verified, retrieval puts the right chunk in the top four for about four in five. The rules do not flag the control case where two witnesses differ only about intent, and the graph itself is precomputed on stronger machines because extraction takes 24 to 30 hours on this CPU."
- **Live or recording:** slide.
- **Fallback ladder:** (1) skip the caveat column aloud but keep it on the slide; (2) n/a (no run); (3) n/a; (4) the same slide as a PDF.
- **Pass criterion:** every number on the slide equals the cited file (a pre-show `rg` of each number against its file; list kept in section 5); the permission to precompute on other hardware has been asked of the organizers (ROADMAP, Sunday) and the answer is written in section 5, or the slide says "asked, no answer".

### Step 6: Limits and close (6:15-7:00)

- **Exact question:** none.
- **Shown:** one slide, five limits and one sentence: (1) the Wisteria finding rests on curated facts; the automatic extraction finds no exact times or days on real data; (2) the gold sets were written by an AI and are not human-reviewed; (3) only 4 genuine R1 cases and 3 R2 cases exist in the corpus, so the rules are demonstrated, not statistically validated; (4) a small model that is wording-sensitive: it only chooses sentences, and some answerable questions (g007, g016) still end in a refusal; (5) "verified" means verbatim and lexically supported, not true. Close: "Everything you saw ran on this laptop with the network off; the graph was precomputed on other hardware."
- **Said (about 2 sentences):** "What it does not do: it cannot tell you a quote is true, only that it is in the book and supports the sentence, and when the model misreads a story, the rules reason faithfully from the misreading. What it does do is show every step, every quote and every condition, so that you can check it in a second."
- **Live or recording:** slide.
- **Fallback ladder:** none needed; if late, say limits (2) and (5) only.
- **Pass criterion:** finishes at or before 7:00 in all three rehearsals; no number on the slide that is not in section 5's checklist.

## 2a. Operator cards (match docs/slides/deck.md)

Base URL for replays: `http://127.0.0.1:8000/` (`just run`, port 8000). A replay plays at its original timing unless `&speed=N` (faster) or `&cap=S` (maximum gap in seconds) is added; the badge reads `RECORDING`. Recording durations from the file meta (`seconds`, re-recorded on the full 20-story graph on 2026-10-28 with the tuned candidate settings (extract_sentence_k 12, safety chunks 4 x 3)): g001 25.6 s, wisteria R1 1.1 s, Baskerville refusal 0.1 s, fee refusal 1.4 s (prefix cache; a cold run is about 23 s), Boscombe control 25.3 s. The g001 and Boscombe recordings take about 25 s at original timing, so add `&speed=4` for them (older text in section 0 quoting 10.8 s is outdated). Open the replay tabs in advance in a second browser window.

Rule for every failure line: say that it is a stored run, never blame the model, never call a recording live.

| Slide (time) | Step | Live path | Recording fallback (`?replay=`) | Spoken line | Failure line |
|---|---|---|---|---|---|
| 1 (0:00-0:35) | Hook: bare model error | none; the transcript is on the slide and is itself the recording of the 2026-10-23 run. At the end of the slide: switch to the board, type `What kind of snake killed Dr. Grimesby Roylott?`, Enter, switch back | none needed for the bare model; for the agent run see slide 4 | "Language models answer fluently, with no proof. This is a small model, recorded earlier on this laptop: it says Roylott was not killed by a snake and puts him in the wrong book. The right answer is a swamp adder." | "The board did not take the question; I will show the stored run of it in a minute." |
| 2, 3 (0:35-1:40) | Idea, architecture | slides; the board with the running g001 answer is behind them | none | "The model only reads and proposes; a graph stores facts with their quotes; rules prove; the text answers by quoting. The tool server is a separate process and never calls a model." | "If the g001 answer is not there yet: the model is still choosing its sentence, ten to twenty seconds is normal on this CPU." (return to the board at 1:35 regardless) |
| 4 (1:40-2:30) | Demo 1: question with verbatim quote | board with the g001 answer; terminal: `rg -F "It is a swamp adder!" data/clean/speckled-band.txt` (one hit); optional `rg -il "baskerville" data/clean` (no output) | `?replay=replay/real-g001-agent.json&speed=4` | "The same question to our agent, started a minute ago. The model chose one numbered sentence; the answer is that sentence, word for word; a one-second search finds it in the book. Verified means verbatim and supporting, not true." | "The model is still choosing its sentence; to keep to time here is the stored run of the same question, labelled as such." If `rg` is slow: run the first command only. If g001 returns NONE: same line, stored run |
| 5 (2:30-3:40) | Demo 2: Wisteria Lodge, R1, curated | board: `Is there a conflict about where Aloysius Garcia was at about one o'clock on the night he died?`; trace shows `tool.call` and `tool.result` in ms; click the dashed edge, open Why | `?replay=replay/real-wisteria-r1-curated.json` | "For this case the facts are curated: our team wrote them from the book with a quote for each, because the small model cannot yet tell who 'he' is. The tool call took this many milliseconds and no model was involved. One man cannot be in his bedroom and dead on Oxshott Common at one o'clock; the finding is conditional because the proof rests on 'nearly one' and 'since one' and on two places we resolved by hand." | "The tool call is slow; here is the stored run of the same question, labelled as a recording." If the finding is not `violated`: stored run, and say "the live graph did not reproduce it; this is the recorded run". If the trace shows `timeline-alibi[in-process]`: "the server did not start as a subprocess; the same functions ran in-process" |
| 6 (3:40-4:15) | Demo 3: honest refusal | board: `What was the creature that haunted the Baskerville family on the Devonshire moor?` Expect refusal, no `llm.call` row, board stays empty | `?replay=replay/real-refusal-baskerville.json`; second refusal only if time: `?replay=replay/real-refusal-fee.json` (22.6 s, passes the gate, model chooses NONE) | "A famous novel that is not among our twenty stories. The agent checks whether its evidence covers the question, finds it does not, and refuses without calling the model. A bare model would tell the story from memory." | If it does not refuse and calls the model: `Esc`, then the replay: "The thresholds are provisional and this live run missed; here is the stored run." |
| 7 (4:15-5:05) | Measured quality | slide | none; the same slide as PDF | "Pilot numbers on small sets that an AI wrote: six of ten answerable questions got a quoted sentence in the extractive run, both out-of-corpus questions were refused; answered is not correct. The final table with intervals is not here yet." | "That row is not measured yet, so I do not give a number." (for any `TBD` row) |
| 8 (5:05-5:30) | Constraints | slide | none | "Offline, CPU-only, models of eight billion parameters or less, fixed decoding. About twenty-one tokens a second of reading speed is why the model never writes the answer." | n/a |
| 9 (5:30-6:10) | Disclosure and limits | slide (mandatory; read all four points) | none | "The graph was precomputed on other hardware with the same models, allowed by the organizers. The Garcia facts are curated, checked by the team and re-checked by a human. The gold sets were written by an AI, review date to be filled. Rule R3 has no positive in the corpus." | If late: keep points 1 and 3 |
| 10 (6:10-6:30) | Next, close | slide | none | "Human review of the gold sets and curated facts, the full graph, contradiction precision and recall with intervals. The model guesses, the rules prove, every step shows its quotes." | n/a |

Whole-system failures (any step): (a) browser or UI frozen: switch to the second window, open the replay of the current step, continue the spoken line; (b) Ollama down or killed: the gate refusal and rule-first steps (5, 6) still work without the model; for step 4 use the replay and say "the model server stopped; this is the stored run"; (c) laptop dead: slides alone carry the transcript, the answer line, the two quotes and the refusal text; say so and continue with slide 7 on paper if needed; (d) over time by more than 20 s at slide 6: skip the `rg` check and drop the second sentence of slide 7.

**Two more recordings (2026-10-28, after the relative-time and chronology work):**
- `?replay=replay/real-abbey-grange-r1-curated.json` (1.0 s): a SECOND red conflict, Lady Brackenstall bound to the chair at the head of the table versus standing at the window, both at the moment Sir Eustace entered. It is a conditional R1 finding on two curated facts whose time is relative (not a clock time); say so, and say that Holmes later shows she was bound only after the death.
- `?replay=replay/real-garcia-timeline.json` (0.2 s): a chronology answer for Garcia from the graph (no model). Say that only events with a date stated in the text are ordered; the rest follow the narration, which need not be the order in which things happened.
- `?replay=replay/real-scene-board.json` (1.4 s, 561 events): the alibi-exclusion board for the Garcia scene (Oxshott Common, one o'clock): of 24 persons of the story one is "excluded by testimony" (Scott Eccles: his own account puts him in his room at the Lodge at nearly one o'clock; conditional, curated), the others are "not excluded", which here means only that the graph is silent. Say it that way. Never say "suspect" or "innocent"; the board makes no verdict about guilt.

Not in the deck (kept for questions): Boscombe control `?replay=replay/real-boscombe-control.json` (25.3 s; backup slide B5).

## 3. Removed and why

- **McCarthy vs Crowder rule step (DRAFT 1 step 2).** Gold c042 (Boscombe Valley) is a *consistent control*: both witnesses agree James went the same way with a gun; they differ only about whether he was deliberately following, which Crowder gives as his belief. The rules correctly do **not** flag it (symbolic-layer.md 11.1), so a step called "contradiction" would either show nothing or be a lie. It moves to the measurements slide (and to the FAQ) as the control the rules pass. Gold note: c042 is low-confidence and conflicts in spirit with g027, which treats the pair as a conflict between accounts; a human has to decide the label.
- **Thor Bridge alibi step (DRAFT 1 step 3).** The expected `check_alibi` status was never recorded, the extraction and time normalisation for the story were unverified, and the quotes depend on the text's double spaces; the "late in the evening" death time is vague, so `unknown` was the likely result. It would have used the longest LLM wait of the demo for a result we could not predict. Its role (a real MCP call visible in ms) is taken by step 2.
- **Dog in the night-time step (DRAFT 1 step 1)** and the **Reichenbach step**: replaced by the hook and the g047 refusal. Reichenbach stays a possible swap for step 3 only if Tuesday shows the gate refuses it without an LLM call.
- **Segment 5b (guess vs prove)** is folded into the architecture slide and step 2.

## 4. Fallback ladder (applies to every step)

1. Narrate over the trace. The waiting counter proves it is working. Allowed: 6 s of silence from the screen, 45 s for the model's sentence selection in g001 (measured 25-43 s).
2. Press `c`: stored run, badge `RECORDING`, say "this one is a stored run". Press `c` again to return to live. If the key does not respond, open the `?replay=` tab of the step (section 2a). Rehearse the connection-lost path with `?stall=5` in the address (5 s instead of 90 s).
3. Play the full recording at the matching timestamp (step start times as in section 0).
4. Screenshot slides.
Never: re-ask the same question hoping for a different answer; blame the model; show an unverified quote as verified; call a stored run live.

## 5. Rehearsal plan and log

**Run 0, Tuesday 2026-10-27 (integration day, target laptop, nothing else running):** measure every pass criterion above, three times each, and fill the log. Pick or reject the Reichenbach swap. Re-record the bare g001 transcript.

**Rehearsal 1, Thursday 2026-10-29:** full run with a timer, all live parts live, recordings as recordings; record per-step times and every intervention. Fix wording and fallbacks. **Rehearsal 2, Thursday 2026-10-29 (second laptop or after a reboot):** same, and in addition force one failure per step (disconnect the tool, kill Ollama mid-prefill) to practise rungs 2-4. **Rehearsal 3, Friday 2026-10-30 morning, on the show laptop:** exact setup, offline, charger, thermal check; a clean run under 7:00 with no intervention is the go criterion (ROADMAP G4/G5). Also rehearse the 5-minute cut once.

| Run | Date | Step 0 first trace row (s) | Step 0 g001 total (s) | Step 2 R1 result, MCP ms, conditional? | Step 3 refusal, ms | Step 4 rg results | Total | Interventions |
|---|---|---|---|---|---|---|---|---|
| 0 | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| 1 | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| 2 | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| 3 | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |

Number checklist for the slides (each filled with the file hit): TBD.

## 6. Dependencies to verify on Tuesday (blocking for step 2)

1. `graph.sqlite` built from the real extraction, with Garcia, Scott Eccles, Baynes and Gregson and their events and quotes for Wisteria Lodge; the curated facts of `data/curated/presence_demo.jsonl` loaded (`python -m detective_board.extract.curated --graph-db data/graph/graph.sqlite`), which carry the day of the two events (hand-curated, disclosed).
2. The stdio MCP server over the real graph (R-19) is done: with `data/graph/graph.sqlite` present the app spawns the `timeline-alibi` server as a subprocess that opens the graph read-only and serves all stories; tests show stdio and in-process results are byte-identical on the curated Wisteria/Garcia graph and the rule-first Garcia answer text is unchanged. Check `/api/health` `mcp.mode` is `stdio` before going on stage. Recordings made before the merge show `timeline-alibi[in-process]`; if the trace ever shows that label live, the subprocess failed to start and the same functions ran in-process: say so. Not verified here: a run against real Ollama or the full graph.
3. A router path from the c001 question to the graph route (HANDOFF section 4, item 3).
4. R1 on the real graph returns `violated`, conditional (the unit test uses the curated passage only).
5. Stored runs, `c` key, `RECORDING` badge (R-02/R-03): done in the UI from the files in `web/replay/` (issue #7); the backend `trace_log` cache of R-02 is not built, so a stored run exists only for a recorded question.
6. Permission on precompute on other hardware: asked of the organizers (ROADMAP); the stage statement is made regardless.

## 7. Five-minute cut

Use when the slot is shortened or rehearsal 2 runs over. Same steps, same fallbacks; only the lengths change.

| Time | Content | Cut |
|---|---|---|
| 0:00-0:30 | Hook: bare RECORDING on g001, start the live agent question | none |
| 0:30-1:00 | Architecture slide, 30 s; the g001 answer is already on the board | slide shortened to the three words |
| 1:00-2:45 | Wisteria R1 (1:45): trace in ms, finding, Why panel with two quotes (Eccles, Baynes), conditional flag | show two of the four quotes; keep the "curated" sentence (slide and spoken) |
| 2:45-3:15 | Gate refusal g047 | none |
| 3:15-4:00 | Bare vs agent merged with the check: skip replaying the bare recording (already seen at 0:00); run only the `rg -F "It is a swamp adder!"` check | second `rg` and the side-by-side dropped |
| 4:00-4:40 | Measurements slide: only the 12-question row, c042, and precompute | retrieval and extraction pilot rows stay on the slide, not spoken |
| 4:40-5:00 | Limits (2), (5) and the close sentence | other limits stay on the slide |

Cut order inside the full version if running late: (1) step 5 spoken caveats, (2) the second `rg` in step 4, (3) the Why panel quotes beyond two. Never cut: step 2 (the rules and the MCP trace), step 3 (honest refusal), the "verified does not mean true" sentence.
