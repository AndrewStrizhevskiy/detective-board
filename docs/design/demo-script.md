---
status: DRAFT 1, 2026-10-22 (nothing executed; no model was run to write this)
owner: demo-director + ux-designer
show date: 2026-10-30, 7 minutes, English
---
# 7-minute demo script (location: docs/design/demo-script.md)

Read with: `docs/design/board-design.md` (screen), `docs/acceptance/acceptance.md` (AC-03, 05, 07, 09, 10, 11, 12, 16, 18, 19), `docs/data-schema.md` section 5 (trace events), `docs/mcp-contracts.md` (alibi tool).

## 0. What constrains this script

| Fact (source) | Consequence for the script |
|---|---|
| Generation 4-7 tok/s; qwen3:8b 4.3 tok/s (PRD 6, spike) | A 60-token answer takes 9-14 s to write. Never wait on it silently. |
| TTFT 15-30 s on a 300-word prompt; 3.8 s on a 52-token prompt (spike: qwen3:8b 29.5 s / 3.8 s) | Any step with a long evidence prompt is **REPLAY** unless it has been timed in rehearsal. Short-prompt steps may be LIVE. |
| Retrieval, graph query and MCP tool calls involve no LLM (mcp-contracts 2: tool never calls an LLM, 5 s timeout) | These are the "useful in 2-3 s" parts: trace rows, graph nodes, quote cards. |
| Heavy extraction is offline (c4 Flow A) | The graph already exists; the board only reveals the evidence subset. |
| Cold model load 15.4 s (spike) | Warm the model before going on stage. |

**Honesty rule:** every cached run shows the `REPLAY` badge (board-design 1.1) and the presenter says "this one is a stored run". A cached answer is never presented as live. Cache = the stored `trace_log` events of an earlier real run (data-schema section 4), keyed by normalised question + index manifest hash + model id + prompt version; replayed with original event order and each gap capped at 2 s. Replay is therefore the real output of the real system, only faster to start (AC-19).

**Live vs cached at a glance**

| # | Time | Question | Mode | Why |
|---|---|---|---|---|
| 1 | 0:35-1:35 | the dog in the night-time | REPLAY | long answer prompt |
| 2 | 1:35-3:05 | James McCarthy vs the gamekeeper | REPLAY (retrieval/graph part may run LIVE in parallel if timed in rehearsal) | two long quotes in prompt |
| 3 | 3:05-4:25 | Miss Dunbar's alibi | **LIVE** | deterministic MCP tool, short summary prompt |
| 4 | 4:25-5:15 | Reichenbach (out of corpus) | **LIVE** if refusal needs no LLM (request 1, board-design 8), else REPLAY | refusal is a rules path |
| 5 | 5:15-6:30 | Patience Moran, bare vs agent | bare LLM LIVE in terminal (short prompt), agent side REPLAY | bare prompt is ~30 tokens, no evidence |

Targets in this script (first visible event within 2-3 s, etc.) are goals; AC-12 and the latency metric are TBD until the performance pass (T-24).

## 1. Pre-show checklist (T-10 min)

1. Laptop on mains, power profile performance, other apps closed, **network off** (AC-13 proves offline operation; also Wi-Fi off removes a failure source).
2. `just` run recipe (name TBD, T-02) started; UI open at 1920x1080 full screen; theme chosen at the projector (light by default).
3. Warm the model: one throwaway question typed in the box (not on the script). Wait until `llm.result`. Cold load is 15.4 s; a warm model avoids it.
4. Caches present for Q1, Q2, Q5-agent (and Q3, Q4 as fallbacks): ask the five scripted questions once in this order, confirm the cache files exist, then restart the UI so the board is empty.
5. Terminal window, font 20 pt, in `/home/mendax/code/detective-board`, pre-loaded with the bare-model command (command TBD by agent-engineer: same model id as the agent, no retrieval, temperature 0, seed 42 as in the spike benchmarks).
6. Second tab/window with the recorded run (T-34) ready, paused at 0:00.
7. Clock visible to the presenter. Operator key sheet: `c` = serve cached answer for the current question (request to frontend, board-design 7), `Esc` = stop run, `g` = list view.

Rehearsal gate (AC-18): the number of clean rehearsals required is TBD; every rehearsal's per-step timings are recorded in this file's section 5 (empty today).

## 2. Storyline

Narrative: "A chat model will tell you anything about Sherlock Holmes. Our agent only says what it can quote. We will watch it work, break a witness's story, check an alibi, refuse a question it cannot answer, and then compare with a model that has no evidence."

### Step 0: Opening (0:00-0:35)

- **Screen:** empty board (board-design 7, Empty). Legend open.
- **Do:** nothing yet; point at the three columns left to right.
- **Say:** "Detective Board is an investigator agent over 20 Sherlock Holmes stories, running on this laptop with no network and a model of at most 8 billion parameters. This machine writes about five words a second, so you will see the agent *work* before it speaks. Left: every step it takes. Centre: the evidence board. Right: the answer, and the proof."
- **Audience sees:** empty board, legend (five shapes, three line styles).
- **Fallback:** none needed.

### Step 1: Simple lookup with proof (0:35-1:35)  REPLAY

- **Do:** click the first question chip (or type): `What was the curious incident of the dog in the night-time?`
- **Source in the corpus (verified in `data/clean/silver-blaze.txt`, chunk `silver-blaze-0022`):**
  > "To the curious incident of the dog in the night-time." / "The dog did nothing in the night-time." / "That was the curious incident," remarked Sherlock Holmes.
  Expected answer: the dog did nothing in the night-time; that was the curious incident (Holmes, Silver Blaze). The pass criterion is that the quoted sentences are verbatim and cite `silver-blaze-0022`. Same fact as `eval/spike_questions.jsonl` en-04.
- **Audience sees (target times from click):**
  - t+0.3 s: `run.start` row, clock ticking, badge `REPLAY`.
  - t+1-2 s: route chip `RETRIEVAL (rules)`; trace row `retrieve.vector: N chunks, fused top 5`; candidate-evidence cards appear in the answer panel with the Silver Blaze quote on top.
  - t+2-3 s: Silver Blaze story node and a Person node (Holmes) appear on the board; the quote card is highlighted in the quote panel (chunk text, span highlighted).
  - t+4-15 s: `llm.call` row with waiting counter; draft text streams muted "draft, not yet verified".
  - end: `selfcheck: quotes verified n/n`; label switches to "verified"; Q1 done.
- **Say:** "Simple question, so the router chose plain retrieval; you can see the choice and the reason here. These quotes arrived before the model wrote a word. Now the model writes, and the self-check confirms each quote is a verbatim substring of that chunk. Unverifiable quotes get dropped."
- **Fallback:**
  - No trace row after 3 s (AC-12 target TBD): say "retrieval is still ranking", wait to 6 s, then press `c`.
  - Model rambles or answer lacks the quote: press `c`; say "that one is a stored run".
  - Live retrieval fine but model slow: keep talking over the waiting counter; at t+20 s, press `c`.

### Step 2: Contradiction of testimony (1:35-3:05)  REPLAY

- **Do:** click chip / type: `Does James McCarthy's testimony contradict what the gamekeeper William Crowder saw?`
- **Source (verified in `data/clean/boscombe-valley-mystery.txt`):**
  - Crowder, as summarised by Holmes, chunk `boscombe-valley-mystery-0003`:
    > "The game-keeper adds that within a few minutes of his seeing Mr. McCarthy pass he had seen his son, Mr. James McCarthy, going the same way with a gun under his arm. To the best of his belief, the father was actually in sight at the time, and the son was following him."
  - James McCarthy, chunk `boscombe-valley-mystery-0007`:
    > "On my way I saw William Crowder, the game-keeper, as he had stated in his evidence; but he is mistaken in thinking that I was following my father. I had no idea that he was in front of me."
  Expected answer: yes, they conflict on one point: Crowder believes the son was following the father with the father in sight; James says he was not following and did not know his father was ahead. Caveat the answer must carry (honest reading): Crowder's evidence reaches us through Holmes's summary of the inquest, and James himself acknowledges Crowder's account and calls it a mistake; the conflict is real but it does not by itself say who is right.
- **Audience sees:**
  - t+1-3 s: route chips `GRAPH + RETRIEVAL`; trace `retrieve.graph: seed "James McCarthy"`; two Person nodes (James McCarthy, William Crowder) and two Claim nodes appear, laid out as a facing pair.
  - t+3-5 s: conflict edge draws between the claims with "!" badge and the label "conflicts"; quote panel shows quote A and quote B stacked, each highlighted in its chunk.
  - t+5-8 s: answer panel shows confidence bar and number (value: whatever the stored run holds; TBD, the confidence formula is not built) with a one-line reason; the two evidence cards sit side by side.
  - then: text streams, `selfcheck` stamps.
- **Say:** "Complex question: the router picked graph plus retrieval. The agent builds a small graph of who said what. Two claims, same event, one conflict edge. Click the red edge: here are both quotes in the book, with the highlighted spans. The confidence number is the agent's own estimate, not a probability; and note the caveat it adds: one witness is reported second-hand."
- **Click sequence:** click the red edge, then click node "William Crowder" (quote panel updates, selection ring moves), then click citation marker `[2]` in the answer.
- **Fallback:**
  - Graph shows no conflict edge (extraction missed it): the answer still carries both quotes; say "the graph did not link these two claims, the retrieval path did; the quotes are still the proof" and click evidence cards instead of the edge. Log it as a defect.
  - Wrong or missing quote: press `c`.
  - Agent reports "no contradiction" (AC-06 path): press `c`. Do not argue with it live.

### Step 3: Alibi check through an MCP tool (3:05-4:25)  LIVE

- **Do:** type `Can Miss Dunbar prove an alibi for the evening of the tragedy?` and press Enter. (Typed live on purpose: short prompt, the part that is deterministic.)
- **Source (verified in `data/clean/thor-bridge.txt`; the text has double spaces after full stops, quotes must match them):**
  - chunk `thor-bridge-0004` (Holmes summarising the case):
    > "Nor could she prove an alibi.  On the contrary, she had to admit that she was down near Thor Bridge--that was the scene of the tragedy--about that hour.  She couldn't deny it, for some passing villager had seen her there."
  - chunk `thor-bridge-0016` (Holmes recalling the note found on the dead woman):
    > "'I will be at Thor Bridge at nine o'clock.--G. Dunbar.'"
  Expected answer: the text gives her no alibi; it places her near the bridge at the relevant hour and the note names nine o'clock. The agent must **not** conclude guilt: in the same chunk Holmes answers "That really seems final." with "And yet, Watson--and yet!" (`thor-bridge-0004`), i.e. the story itself treats the missing alibi as misleading. A correct answer says "no alibi shown; that is not proof of guilt".
  The tool status (`supported | contradicted | unknown | insufficient_evidence`, mcp-contracts 3.2) depends on what the extraction and the time normaliser produced for this story. **Do not script the status.** Record it in rehearsal (section 5). The text "late in the evening" for the death is vague (`thor-bridge.txt` line 43), so `unknown` with low confidence is a plausible, honest result; if so, the line below applies.
- **Audience sees:**
  - t+0.3 s: `run.start`, route chip `MCP: alibi (rules)`.
  - t+1-3 s: trace `tool.call: timeline-alibi.check_alibi(story=thor-bridge, person=..., window=~21:00)` (arguments visible), then `tool.result: <status>, n anchors, <ms>` (target well under the 5 s tool timeout); Person node (Grace Dunbar), Place node (Thor Bridge), Event nodes appear; edge style per status.
  - t+3-5 s: evidence cards for the anchors with the quotes above.
  - t+5-30 s: `llm.call` (short prompt: tool result and two quotes) with waiting counter, then streaming; this is the longest wait of the demo, so the presenter talks (see Say).
  - end: `selfcheck`, verified ticks, confidence bar.
- **Say:** "Third kind of question: an alibi. The agent does not guess; it calls a tool over the Model Context Protocol. Look at the trace: tool name, arguments, result, in milliseconds. The tool never calls a language model and returns evidence with source anchors. While the model writes its summary: in the tool result you see which statements are the suspect's own claims and which are narrator statements; a claim is evidence of what was said, not of what happened."
  If the status is `unknown`/low confidence: "Notice what it did not do: it did not declare her guilty. The text gives her no alibi, and the tool says how sure it is."
- **Fallback:**
  - Tool times out (5 s) or returns `error`: trace shows the `tool.result ok=false` row; say "this is the designed failure: it continues without the evidence and says so"; if the answer is a refusal `tool_error`, that is also a valid on-script moment, then press `c` on the stored run.
  - Model stalls > 25 s on the summary: the tool result and quotes are already on screen; say "the evidence is the product, the sentence is cosmetic" and press `c` to load the stored summary.
  - Entity not resolved (`ambiguous`/`not_found`): press `c`.

### Step 4: Honest refusal (4:25-5:15)  LIVE if no-LLM refusal exists, else REPLAY

- **Do:** type `How did Holmes escape from Moriarty at the Reichenbach Falls?`
- **Why this question (verified):** `rg -i "reichenbach|falls|switzerland|meiringen" data/clean` finds no Reichenbach, no Switzerland, no Meiringen; Moriarty is mentioned exactly once, in `norwood-builder-0000`:
  > "London has become a singularly uninteresting city since the death of the late lamented Professor Moriarty."
  So the corpus supports one fact (Moriarty is dead) and nothing about the falls or an escape. The matching stories are not among the 20 selected (c4: 20 stories; PRD 5). Expected: refusal for the asked part, supported part quoted (AC-03 + AC-04), "Searched: ..." list, no invented narration.
  The question is chosen because a model with canon knowledge will happily narrate the falls (see Step 5 backup).
- **Audience sees:**
  - t+0.3 s: `run.start`; t+1-3 s: route chip `REFUSAL (rules)` or `RETRIEVAL` followed by `refusal`; trace shows the search queries and that top chunks scored below the threshold (threshold TBD).
  - answer panel: indigo banner "Refusal: not in the corpus", "Searched: Reichenbach, Falls, Moriarty ...", nearest rejected chunks collapsed, and the one supported quote from `norwood-builder-0000` marked "what the corpus does say".
  - the board stays almost empty: one Person node (Moriarty), no edges, with the explanation "only one mention".
- **Say:** "This is the question that makes ordinary chatbots shine and fail: they know the famous story from outside. Our 20-story corpus doesn't contain it. The agent says so, shows what it searched, and quotes the one thing it can: Moriarty is dead. No invention."
- **Fallback:**
  - Agent answers with content instead of refusing (self-check should drop unquoted claims; if not): press `Esc`, press `c` for the stored refusal, and say "the stored run shows the intended behaviour; this live run is a defect I will show in the eval report" (honest).
  - Refusal is slow (LLM-written): replay; say "refusal text is cached for timing".
  - Backup out-of-corpus question (no Holmes content at all, AC-03 example): `Who won the 2022 football World Cup?` Verified absent in the corpus by `rg -i "world cup" data/clean` (no hits; do not rely on this line, re-run `rg` before the show).

### Step 5: Bare LLM vs our agent, hallucination caught (5:15-6:30)  bare LIVE (terminal), agent REPLAY

- **Question (same for both):** `Who saw the McCarthys quarrelling by Boscombe Pool, and what did she do afterwards?`
- **Ground truth (verified, `boscombe-valley-mystery-0003`):**
  > "A girl of fourteen, Patience Moran, who is the daughter of the lodge-keeper of the Boscombe Valley estate, was in one of the woods picking flowers."
  > "She was so frightened by their violence that she ran away and told her mother when she reached home that she had left the two McCarthys quarrelling near Boscombe Pool"
  Facts to check: Patience Moran; fourteen; daughter of the lodge-keeper; picking flowers; saw father and son quarrelling at the border of the wood; ran home and told her mother.
- **Do:**
  1. (5:15) Switch to the terminal. Run the bare-model command with the question (same model, no retrieval, no corpus). TTFT is expected a few seconds (short prompt, 3.8 s for qwen3:8b on 52 tokens in the spike) and then 4-7 tok/s. Let it write ~3 lines.
  2. (5:45) While it writes, press Alt+Tab to the board, ask the same question; it replays the stored agent run: evidence cards with the Patience Moran quote appear within 2-3 s.
  3. (6:05) Take any specific claim from the bare answer (a name, an age, or a quoted sentence in quotation marks) and check it in front of the audience:
     `rg -F "<the invented phrase>" data/clean/` (about 1 s, no hits) and show the agent's own quote check: every agent quote `verified`.
- **What the audience should see:** left, a fluent confident paragraph (terminal); right, the agent's board with quote cards and "verified" ticks; then the red-handed moment: the bare answer's specific claim does not exist anywhere in the text (`rg` returns nothing).
- **Say:** "Same model, same laptop, same question. On the left it has no evidence; on the right it has to prove every sentence. Here the bare model says [read the specific wrong claim]. Let's search the 183,000 words: nothing. The agent's answer: Patience Moran, a fourteen-year-old picking flowers; here is the sentence; the self-check confirmed it."
- **Risk and the honest handling:** whether the bare model errs on this question is **unknown until rehearsal** (a model may know this story). In rehearsal, record the bare output at temperature 0, seed 42 (deterministic setting used in the benchmarks) and write the wrong claim into section 5. If the bare model is right, do not stage a fake error. Use, in order: (a) ask the bare model for the verbatim sentence rather than a summary ("quote the exact sentence"), where invented quotes are likely; the substring check then fails; (b) use the Step 4 question on the bare model: it will tell the Reichenbach story with confidence from outside the corpus, which is ungrounded rather than hallucinated, and the presenter must call it exactly that.
  Never present a result of one run as a general rate: say "one question, one run; the measured comparison is in the eval report" and point to the A/B table (numbers TBD, T-23).
- **Fallback:**
  - Bare model too slow (> 15 s to first token): play the recorded bare output (file from rehearsal) and say "recorded earlier on this laptop".
  - Terminal problem: show a screenshot from the backup slide.
  - Agent run fails: press `c`.

### Step 6: Close (6:30-7:00)

- **Screen:** board with the last run still visible; then the single results slide.
- **Say:** "What we measured: [A/B table: baseline RAG vs hybrid vs GraphRAG vs agent; numbers TBD until T-23/T-30, state them as measured, including the ones that are bad]. What we did not solve: [list from jury-faq]. Everything you saw ran offline on this laptop."
- **Fallback:** if numbers are not final, show only the structure and say "the final report is in the repository" (no invented numbers, ever).

### Segment 5b: where the agent guesses and where it proves (inside Step 3 or Step 6, about 40 s)  recording unless the Step 3 tool call is live

- **Screen:** the Step 3 (alibi) or Step 2 (contradiction) board, with the provenance legend open (board-design 1.6) and the "Why?" panel on the finding.
- **Do:** point at an `extracted` fact (chip "~", confidence shown), then at the `derived` finding (chip "="); click the finding to open its explanation: rule id, the facts used, the source quote of each. If the rehearsal produced a `conditional` finding, show its doubtful input.
- **Say:** "Two kinds of statements on this board. The model guesses: it reads the story and extracts facts, with a confidence; it can be wrong. The rules prove: given those facts, a rule such as 'one person cannot be in two places at once' gives the same answer every time, and here is exactly which facts and quotes it used. If the proof leans on a shaky guess, the board says conditional. The honest limit: if the model misread the story, the rule faithfully proves something from the misreading; that is why every input shows its quote."
- **Honesty:** the rule tests are deterministic and can be run on stage (`just test`, rules subset) only if they exist and are green by the freeze; otherwise do not mention them. Do not present a finding as true of the story, only as following from the stated facts.
- **Cut:** first thing to drop if running late after Step 1 (saves 40 s); never claim "proof" in slides without the explanation panel on screen.
- **Fallback:** if no `conditional` finding exists, skip it and say so rather than staging one.

## 3. Time budget and cuts

| Step | Start | Length | If running late |
|---|---|---|---|
| 0 Opening | 0:00 | 0:35 | shorten to 15 s |
| 1 Dog | 0:35 | 1:00 | **cut first** (saves 60 s); the router-path message moves into Step 2 |
| 2 Contradiction | 1:35 | 1:30 | never cut |
| 3 Alibi (MCP) | 3:05 | 1:20 | never cut (MCP requirement) |
| 5b Guess vs prove | inside Step 3 | 0:40 (taken from the Step 3 wait, total stays 7:00) | cut first after Step 1 |
| 4 Refusal | 4:25 | 0:50 | never cut (PRD: honest refusals) |
| 5 Bare vs agent | 5:15 | 1:15 | cut step 3 sub-action (b) first |
| 6 Close | 6:30 | 0:30 | 15 s minimum |

Cut order follows `docs/backlog.md` ("never cut: working demo, citations, honest refusals, quality measurements"). UI animations (A1-A8) can be turned off without changing this script (board-design 5).

## 4. Fallback ladder (applies to every step)

1. Narrate over the trace: the waiting counter proves it is working (AC-12). Allowed up to 6 s of silence from the screen, 25 s on the LLM-writing phase.
2. Press `c`: stored run, `REPLAY` badge. Say it out loud.
3. Play the recorded full run (T-34), starting at the matching timestamp.
4. Slides with screenshots of each step (last resort).
Never: re-ask the same question hoping for a different answer on stage; blame the model; show an unverified quote as verified.

## 5. Rehearsal log (to be filled; empty on purpose)

| Run | Date | Step 1 | Step 2 | Step 3 (tool status, ms) | Step 4 | Step 5 bare error found? (quote the wrong claim) | Total | Interventions |
|---|---|---|---|---|---|---|---|---|
| 1 | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |

Acceptance (AC-18/19): all scripted questions complete without manual fixes; the stored answers match on a second run. Required clean runs: TBD.

## 6. Data dependencies to verify before the freeze (blocking for this script)

0. Rules module (T-36), provenance badges and explanation panel (T-38) exist; otherwise segment 5b is dropped and the words "neuro-symbolic", "derived" and "proof" are not used on stage.

1. Graph contains Person nodes for Grace Dunbar, James McCarthy, William Crowder, Patience Moran with anchors in the chunks quoted above (extraction quality is not measured yet; gold set is 12 chunks labelled by an agent, not a human).
2. `check_alibi` returns anchors for Thor Bridge; time normalisation for "nine o'clock" / "late in the evening" exists (T-14 is P2, so possibly not).
3. Refusal path works without an LLM call, or Step 4 is REPLAY.
4. A contradiction detector exists (T-15, calling rule R1/R3) and finds the Crowder/James pair; otherwise Step 2 falls back to "show both quotes, agent compares" and the word "contradiction" is not claimed from the graph.
5. `c` key, REPLAY badge, `cached` flag, bare-model command: requests filed in `docs/backlog.md`.

## Decisions of 2026-10-22 (customer)

1. Every pre-recorded step is called a **recording** (not "live", not "replay of the agent") in slides, speech and the on-screen badge. Only steps that really run on the laptop during the talk may be called live.
2. The "bare LLM vs agent" comparison uses a question on which the bare model **really** errs, found by running the bare model on candidate questions in advance and keeping the exact transcript. The error is never staged. If no candidate fails reliably, the comparison is dropped or replaced by the verbatim-quote check, and this is stated honestly.
