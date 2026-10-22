# Investigation board: design

Status: DRAFT 1, 2026-10-22. Owner: ux-designer. Inputs: `docs/PRD.md`, `docs/acceptance/acceptance.md` (AC-10, 11, 12, 16), `docs/architecture/c4.md`, `docs/data-schema.md` (graph nodes/edges, trace events), `docs/mcp-contracts.md`. Nothing here is implemented yet; the UI framework is undecided (c4.md L2), so all specs are framework-neutral and use the tokens in `docs/design/tokens.css`. Numbers marked TBD depend on measurements that do not exist yet.

Design premise (from PRD section 6): generation is 4-7 tok/s and first token on a 300-word prompt takes 15-30 s (spike: qwen3:8b 29.5 s on a 406-token prompt at 13.8 prompt tok/s; 3.8 s on a 52-token prompt). So the screen must be useful before the model speaks: the trace, the graph and the retrieved quotes come from non-LLM steps and must appear first. The answer text is the last thing to arrive and is shown as unverified until the self-check passes.

## 1. Information architecture

Reference canvas 1920x1080 (projector); minimum supported 1280x720. One screen, no routes, no modals during a run.

```
+----------------------------------------------------------------------------------+
| QUESTION BAR  [ question input.......................................] [Ask]      |
|  route chip(s) | run badge LIVE / REPLAY | elapsed clock | theme | motion on/off   |
+--------------------+------------------------------------------+-------------------+
| TRACE PANEL   (3/12)| BOARD / GRAPH CANVAS          (5/12)     | ANSWER PANEL (4/12)|
| ordered events     |  nodes appear as evidence is found        | status + confidence|
| one row per step   |  edges: relation / support / conflict     | answer text        |
| timings, tool args |  legend (collapsible) + "list view"       | inline quotes [n]  |
| waiting counter    |                                           +-------------------+
|                    |                                           | QUOTE PANEL        |
|                    |                                           | story, chunk,      |
|                    |                                           | highlighted span   |
+--------------------+------------------------------------------+-------------------+
| STATUS STRIP: model id | prompt tokens est | gen tok/s | graph n nodes / m edges    |
+----------------------------------------------------------------------------------+
```

Reading order for the audience, left to right, is the order things happen: trace (what the agent does) -> board (what it found) -> answer and proof (what it concludes and why it can be trusted). Everything is linked by one shared selection (see 1.5).

### 1.1 Question bar
- Single-line input, Enter submits. While a run is active, the button becomes Stop (cancels the run; trace gets `run.end status=error`-style "cancelled by user" row, a UI-side event).
- Route chips appear when the `route` event arrives: `RETRIEVAL`, `GRAPH`, `MCP: alibi`, `REFUSAL` (data-schema `route.routes`). Several chips are allowed (router may pick several). Each chip also states the method (`rules`/`llm`), taken from the event.
- Run badge: `LIVE` (computed now) or `REPLAY` (served from cache, see demo-script). REPLAY is mandatory honesty: a cached answer is never shown as live. It uses `--db-replay-bg/--db-replay-text`.
- Elapsed clock since `run.start`; it keeps ticking so the screen never looks frozen (AC-12).
- Demo mode only: a row of question chips under the input with the scripted questions, so the presenter clicks instead of typing. Hidden outside demo mode.

### 1.2 Trace panel (left, AC-10)
One row per event of `docs/data-schema.md` section 5, appended as it arrives, newest at the bottom, auto-scroll pinned unless the user scrolls up (then a "jump to latest" pill appears).

Row anatomy: `[time since start]  [icon + type label]  [one-line summary]  [duration]  [chevron]`. Expanding a row shows the payload in plain words, not raw JSON (raw JSON behind a "raw" toggle for the jury).

| event type | one-line summary shown | expanded detail |
|---|---|---|
| `run.start` | the question | config digest |
| `route` | `-> GRAPH + RETRIEVAL (rules): relational question` | reason, confidence |
| `retrieve.vector` | `7 chunks: 3 lexical, 5 semantic, fused top 5` | ranked list: story, chunk id, score; click opens the chunk in the quote panel |
| `retrieve.graph` | `12 nodes, 14 edges from seed "James McCarthy"` | node list; `truncated` shown as "+N not shown" |
| `tool.call` | `MCP timeline-alibi.check_alibi(person, window)` | full arguments, timeout |
| `tool.result` | `contradicted, 2 anchors` or `error: timeout` | result summary, anchors |
| `enrich` | `prompt ~410 tokens, 5 evidence blocks` | evidence list; shown with the text "corpus text = data" label (AC-16) |
| `llm.call` | `model qwen3:8b, attempt 1` and the **waiting counter** (below) | temperature, num_ctx |
| `llm.result` | `62 tokens` | finish reason |
| `selfcheck` | `quotes verified 3/3` or `1 quote dropped` | per-quote verbatim flag, unsupported claims, action |
| `answer` / `refusal` | `answered` / `refused: out_of_scope` | citations / what was searched |
| `error` | `tool timeout, continuing without it` | code, retriable |

Waiting counter (the key anti-freeze element): while an `llm.call` has no first token, its row shows `waiting for first token  12 s`, ticking each second, plus `prefill estimate ~N s` computed as `prompt_tokens_est / measured prefill tok/s` (13.8 tok/s measured for qwen3:8b in the spike; the live number comes from config, not hard-coded). Once tokens flow, the row shows `writing  4.6 tok/s`. The estimate is labelled "estimate".

Each row has a status glyph that is not colour-only: running (spinner or three dots), ok (check), warn (triangle), error (cross), skipped (dash). Rows carrying text from the corpus show a small "data" tag (the text came from the corpus, it is never an instruction).

### 1.3 Board / graph canvas (centre, AC-11)
- Starts empty (see states). Grows as `retrieve.graph`, `tool.result` and `enrich` events arrive: nodes and edges that are in the evidence set appear; nothing is drawn that has no source anchor.
- Entity types: Person, Place, Item, Event, Claim (data-schema 3.1). The Chunk node is not drawn; it is the "source" shown in the quote panel.
- Layout: force-directed, fixed random seed and fixed iteration budget so the same evidence gives the same picture (needed for AC-19, demo determinism). Seed nodes start at the centre. Hard cap 25 visible nodes; beyond that a "+N more" chip on the seed (expand on click). Nodes never move after they are placed unless the user drags (pinned), to avoid a restless screen on a projector.
- Contradiction pairs are laid out as a facing pair (left/right) with the conflict edge between them, so the eye gets the story without reading.
- Zoom/pan with mouse and keyboard (`+`, `-`, arrows when canvas focused); "fit" button; node labels are always visible at zoom >= 70 percent, otherwise on hover/focus.
- Legend (collapsible, open by default in demo mode): five node shapes + three edge styles.
- "List view" toggle swaps the canvas for an accessible table (nodes, then edges) with the same selection behaviour (section 6).

### 1.4 Answer panel (right top)
Top to bottom:
1. **Status line**: one of `Investigating...`, `Answer`, `Partial answer: part unknown`, `Refusal: not in the corpus`, `Error`. Icon + word; never colour only.
2. **Confidence** (only for findings: contradiction/alibi and for answers the self-check scored; plain lookups show "N of N quotes verified" instead of a number, since PRD defines confidence for findings): a labelled bar `Confidence 0.72  medium` plus the one-line reason. Bands: high >= 0.75, medium 0.40-0.74, low < 0.40 are **provisional** (TBD, to be set from the eval calibration; the confidence formula is owned by agent-engineer). The number is always printed; the bar and band word repeat it.
3. **Answer text** in 20-28 px (`--db-text-lg`..`--db-text-xl`), with numbered citation markers `[1]`, `[2]`. While the model streams, the text is shown with a muted "draft, not yet verified" label and tokens append live. When `selfcheck` arrives: ok -> label becomes "verified" and text switches to full contrast; quotes failing the check are struck out and removed from the text with a note ("1 quote dropped: not found verbatim"); `action=retry` shows "re-checking, attempt 2".
4. **Evidence list**: one card per citation: story title, chunk id, the verbatim quote in serif (`--db-font-quote`), a verified tick (after self-check). For contradictions the two quotes sit side by side, labelled A and B, with the second highlighted with the conflict colour and a "conflicts with A" label.
5. For refusals: the banner `Not in the corpus`, then "Searched: ..." (the `missing[]` and queries from the `refusal` event), and the list of the nearest chunks that were rejected as unrelated (so the audience sees the search happened).

Evidence cards appear **before** the model text: retrieved quotes are placed on the panel as soon as `retrieve.*` finishes, marked "candidate evidence (not yet used in the answer)". This is what the audience reads during the 15-30 s wait.

### 1.5 Quote panel (right bottom)
- Shows the source passage for the current selection: header `Story title - chunk id - characters start-end`, the chunk text (up to ~1,100 characters) with the cited span highlighted (`--db-quote-bg`). Text is in serif, 18 px minimum on the projector.
- The highlighted span is computed from the anchor (`char_start/char_end`, with `rel_*` fallback if the contiguity check failed, data-schema 1 and 3.3). If the anchor is `ambiguous`, an "ambiguous match: first occurrence shown" note appears.
- Two-quote mode (contradiction): two stacked passages, A and B, each with its own highlight; A uses `--db-quote-bg`, B uses `--db-quote-bg-conflict`. The shape cue is a left border: solid for A, double for B.
- Shared selection: selecting a trace row, graph node/edge, citation marker or evidence card selects the same underlying object everywhere (outline ring on the node `--db-selected-ring`, row highlighted, card highlighted, passage shown). Selecting never starts a run.

## 2. Visual language: nodes and edges

Colour is a second channel; **shape and an icon letter carry entity type** so the board survives colour-blindness, a washed-out projector and greyscale print.

| Entity | Shape | Icon glyph (in node, 14 px) | Light stroke/label | Light fill | Dark stroke/label | Dark fill |
|---|---|---|---|---|---|---|
| Person | circle | silhouette | `#1f5fa8` | `#d6e5f8` | `#7db2f0` | `#1f3552` |
| Place | rounded rectangle | pin | `#2a6f48` | `#d3ecdc` | `#6cc28e` | `#1d4130` |
| Item | diamond | key/tag | `#8a5a00` | `#f6e3b8` | `#e0b15a` | `#4a3812` |
| Event | hexagon | clock | `#7a3e9d` | `#e8d8f3` | `#c79be6` | `#3d2650` |
| Claim | speech-bubble (rectangle with tail) | quote mark | `#a03a6b` | `#f7d9e6` | `#ee92bb` | `#51243a` |

Node anatomy: 2 px stroke in the entity colour, fill in the tinted colour, label in `--db-text-on-fill` (18 px on projector, 14 px minimum), at most two lines then ellipsis, full name on hover/focus. Size is constant (no size-by-degree) except the seed node, which gets a second outer ring. Selected node: extra 3 px outer ring in `--db-selected-ring`. Keyboard focus: 3 px ring in `--db-focus` offset 2 px.

Claim nodes show the speaker's name as a small prefix line ("McCarthy:") because the claim is evidence of what was asserted, not of what happened (mcp-contracts 3.2).

Edges (2 px; arrowhead = direction; label on hover/focus, always on for conflict edges):

| Meaning | Edge types (data-schema 3.2) | Style | Colour token |
|---|---|---|---|
| Relation / participation | `RELATION`, `PARTICIPATED_IN`, `OCCURRED_AT`, `ABOUT`, `ASSERTS` | solid | `--db-edge` |
| Supports (claim supported, alibi `supported`) | derived from tool result | solid with a check mark at the midpoint | `--db-edge-support` |
| Conflicts (contradiction, alibi `contradicted`) | derived from tool/agent result | solid 3 px with a "!" badge at the midpoint, label "conflicts" | `--db-edge-conflict` |
| Unknown / insufficient evidence | `unknown`, `insufficient_evidence` | dotted, "?" badge | `--db-edge-unknown` |

Each edge has an anchor; clicking it opens the quote that justifies it. An edge without an anchor is a bug and is not drawn.

States of a node: `new` (animated in, section 5), `active` (in the current evidence set, full opacity), `context` (from an earlier question on the board, 55 percent opacity and a dashed stroke; contrast of context nodes is intentionally lower and they are decorative, never the only carrier of information), `dimmed` (not related to the current selection, 40 percent opacity, only while a selection exists).

The board is cleared on each new question by default (clean story for the audience); "keep previous" is a toggle (off by default).

## 3. Contrast: computed values

All pairs are computed, not estimated, by `docs/design/contrast_check.py` (Python stdlib only; parses `tokens.css`; WCAG 2.x relative-luminance formula; thresholds 4.5:1 text, 3:1 non-text per WCAG 1.4.3 and 1.4.11). Run: `python3 docs/design/contrast_check.py`. Last run 2026-10-22: 0 failures out of 57 pairs per theme. Full table is the script output; key ratios:

| Pair | Light | Dark |
|---|---|---|
| body text on board / on surface | 14.44 / 16.56 | 14.67 / 13.13 |
| muted text on surface / on board (worst case: on surface-2) | 8.14 / 7.10 (6.53) | 8.23 / 9.19 (7.16) |
| person label on board / text on its fill | 5.62 / 12.95 | 8.27 / 10.91 |
| place label on board / text on its fill | 5.28 / 13.25 | 8.49 / 9.96 |
| item label on board / text on its fill | 5.17 / 13.09 | 9.24 / 9.88 |
| event label on board / text on its fill | 6.10 / 12.26 | 8.07 / 11.58 |
| claim label on board / text on its fill | 5.53 / 12.64 | 8.25 / 11.08 |
| entity stroke vs its own fill (non-text, need 3:1; lowest = item 4.68 light, place 5.26 dark) | 4.68 to 5.18 | 5.26 to 5.82 |
| edge neutral / support / conflict / unknown on board | 5.49 / 5.28 / 5.70 / 4.39 | 7.66 / 8.49 / 8.01 / 6.95 |
| confidence text high / mid / low on surface | 6.52 / 5.93 / 6.54 | 7.60 / 8.27 / 7.17 |
| refusal accent text on surface | 8.75 | 7.86 |
| confidence bar vs track (need 3:1) | 4.35 / 3.96 / 4.37 | 5.16 / 5.62 / 4.87 |
| quote text on highlight A / B | 13.78 / 11.77 | 7.25 / 9.92 |
| UI border vs surface / vs board (need 3:1) | 4.41 / 3.85 | 5.15 / 5.76 |
| focus ring vs surface / board | 6.39 / 5.57 | 7.77 / 8.68 |
| link on surface | 7.54 | 7.77 |

What the script does **not** prove: (a) that the five hues are mutually distinguishable for every colour-vision type; that is why shape + glyph carry the type; (b) legibility on a specific projector (washed-out, low-contrast beamer); mitigation: the lowest computed text ratio is 5.17 (light) / 7.16 (dark), the lowest non-text ratio is 3.85 (light, UI border on board) / 4.87 (dark), and a pre-show check on the actual projector is on the demo checklist; (c) the quote-highlight background against the surface (1.20 light, 1.90 dark) is deliberately not a pass/fail pair: the highlight is identified by the text on it (13.78 and 7.25) and by the left border, not by its own edge contrast.

## 4. Typography and sizing (projector rule)

- UI font `--db-font-ui`; quotes in `--db-font-quote` serif so that "this is the book's text" is visible at a glance; trace payloads in `--db-font-mono`.
- Minimum sizes at 1920x1080: trace rows 16 px, node labels 18 px, answer 24 px, quotes 18 px, confidence number 28 px. Below 1280 px width: 14 px minimum and the three columns collapse to tabs (Trace / Board / Answer); the demo never uses this layout.
- Line length in answer and quote panels <= 70 characters; line-height 1.45.

## 5. Animation spec (all cuttable)

Backlog T-33 puts UI animations first in the cut order, so the board must be complete and legible with every animation removed. Switch: `<html data-motion="off">` or OS `prefers-reduced-motion` sets all `--db-dur-*` tokens to 0 ms; every animation below is purely a CSS/JS transition on a state that already exists. Priority P1 = keep if only one survives, P3 = cut first.

| ID | Name | Trigger | What | Duration / easing | Priority | Without it |
|---|---|---|---|---|---|---|
| A1 | Trace row slide-in | event arrives | row fades in and moves 8 px up | `--db-dur-fast` 120 ms | P1 | row appears instantly |
| A2 | Node appear | node enters evidence set | scale 0.85 -> 1 and opacity 0 -> 1, stroke flashes to the selected ring once | `--db-dur-node` 350 ms, `--db-ease`; nodes of one event staggered by 80 ms, max 6 staggered | P1 | nodes appear instantly (the live-growth message survives because they still appear event by event) |
| A3 | Edge draw | edge enters evidence set | line draws from source to target (stroke-dashoffset) | 350 ms, after its two nodes | P3 | edge appears instantly |
| A4 | Waiting pulse | `llm.call` without first token | three dots in the trace row pulse; counter text ticks every second | `--db-dur-pulse` 900 ms loop | P1 (the counter is not an animation and is never cut) | static "waiting" text with the ticking counter |
| A5 | Conflict emphasis | contradiction/alibi result | conflict edge pulses twice, both nodes get the selected ring | 2 x 450 ms | P2 | edge is already drawn thicker with "!" badge |
| A6 | Quote highlight sweep | passage shown | highlight background wipes left to right over the span | 300 ms | P3 | span highlighted instantly |
| A7 | Verified stamp | `selfcheck ok` | check mark scales in next to each verified quote; draft label changes to "verified" | 120 ms | P2 | label changes, no motion |
| A8 | Linked-selection glow | selection changes | the same object outlines in row, node, card | 120 ms | P2 | outline appears instantly |

Rules: no animation loops after the run ends; nothing blinks faster than 3 Hz; nothing moves nodes that are already placed (no continuous physics jitter; the layout simulation is run to rest off-screen, then new nodes are animated into the computed positions); animations are never required to understand state.

## 6. Accessibility

- Contrast: section 3; re-run the script on every token change (candidate CI check for frontend-engineer, see backlog request).
- Not colour-only: node type = shape + glyph + legend; edge meaning = style + badge + label; status = icon + word; confidence = number + band word + bar; REPLAY/LIVE = text.
- Keyboard: full operation without a mouse. Tab order: question input, Ask/Stop, theme and motion toggles, trace panel (list, rows are focusable, Enter expands), canvas (one tab stop; arrow keys move between nodes in discovery order, Enter selects, `Esc` clears selection), list-view toggle, answer panel (citation markers focusable), quote panel. Shortcuts: `/` focuses the question box, `g` toggles graph/list view, `t` jumps to latest trace row. Focus ring 3 px `--db-focus` everywhere, never removed.
- Screen readers: trace panel `role="log"` with `aria-live="polite"` and `aria-relevant="additions"`, rows throttled to at most one announcement per second; answer text is **not** a live region while streaming (token-by-token announcements are unusable); instead one polite announcement on commit ("Answer ready, 3 quotes verified, confidence 0.72") and one for a refusal. Graph canvas has an accessible name and a "list view" alternative: a table of nodes (type, name, source) and edges (from, relation, to, source) with the same selection and quote panel. Node `aria-label` = "Person: James McCarthy. Selected for quote".
- Motion: section 5; respects `prefers-reduced-motion`.
- Zoom/size: layout reflows at 200 percent browser zoom (columns become tabs); text resizable.
- Theme: dark by OS preference, manual override; both themes verified by the same script. The demo uses light on a projector unless the room is dark (decide at the pre-show check).
- Language: UI strings English. Corpus is English. Russian questions have a weak retrieval smoke result (spike: ru hit@5 0.20, n=5, vs en 1.00, n=15), so the product and demo are English-only; this is a stated limitation, not a design choice to hide.
- Corpus text is data: every block of corpus text carries a visible "corpus text" tag (trace `enrich` row, quote panel header) and is rendered as plain text (no HTML, no links, no markdown), so an injected instruction (AC-16) cannot do anything and is visibly not an instruction.

## 7. Empty, loading and error states

| State | Trigger | What the user sees |
|---|---|---|
| Empty board (first load) | no run yet | Canvas shows a faint pinboard grid, the legend, and the line "Ask a question. Nodes appear as the agent finds evidence." Trace: "No steps yet". Answer panel: "Answers appear here with quotes and a confidence value." Demo mode adds the scripted-question chips. |
| Warming up | API up, model not loaded (cold load measured 15.4 s for qwen3:8b) | Status strip: "Loading model... 8 s". Ask is enabled; first run shows the `llm.call` waiting counter as usual. Operator pre-warms before the show (checklist item). |
| Running, before any event | submit | within 300 ms (client-side, no server needed): `run.start` row with the question and the ticking clock (TBD: measured against the real API, AC-12 target TBD). |
| Running, retrieving | `route` .. `retrieve.*` | route chips, trace rows, candidate-evidence cards, nodes appearing. Target: first non-trivial event (route) within 2-3 s; if no event after 3 s the trace shows "still working: waiting for retrieval" so the screen is never silent. |
| Waiting for first token | `llm.call` sent | waiting counter and prefill estimate (1.2). Evidence already visible. |
| Streaming | tokens | draft text appended, muted, "draft, not yet verified"; tok/s in the status strip. |
| Verified answer | `selfcheck ok` + `answer` | full-contrast text, ticks on quotes, confidence. |
| Partial | answer with unsupported parts | status "Partial answer: part unknown"; unsupported parts listed under "Not supported by the corpus" in the muted style with the dashed unknown-edge icon (AC-04). |
| Refusal | `refusal` | status "Refusal: not in the corpus", reason code in plain words, "Searched: ..." list, nearest rejected chunks collapsed. Refusal uses `--db-refusal` (indigo), deliberately not the error red: a refusal is a correct result, not a failure. |
| Self-check retry | `selfcheck action=retry` | trace row "quote not verbatim, retrying (1 of 1)"; answer panel keeps showing the old draft greyed with a strike-through; if the retry fails the refusal state appears with code `selfcheck_failed`. |
| No contradiction found | AC-06 | status "No contradiction found", the claims that were compared (with quotes) and confidence; never an empty panel. |
| Tool error | `tool.result ok=false` | warn row in trace with code and "continuing without this evidence"; if the answer depended on it: refusal `tool_error`. Never silently dropped. |
| Model stall | no token for > 60 s (threshold TBD from latency measurements) | trace row "model not responding"; Stop button emphasised; demo mode shows operator hint "press `c` to serve the cached answer" (shown only to the presenter's screen if a second screen exists; otherwise press and the REPLAY badge appears). |
| Stream disconnect | SSE/WS closed unexpectedly | banner "Connection to the agent lost. Retrying (n/3)"; last state kept; after 3 failures an error state with "Run again". |
| Error | `error` / `run.end status=error` | error icon, code, plain message, `retriable` decides whether "Run again" is shown. No stack traces, no file paths. |
| Graph too large | `truncated` | "+N more" chip on the seed node; list view has everything. |
| No graph data for this question | retrieval-only route | canvas shows the retrieved chunks as source cards with the message "This question was answered from text search only; no graph nodes were used". The board is never blank without an explanation. |

## 8. Requests to other zones (also in `docs/backlog.md`)

1. backend/agent: the refusal path should not need an LLM call (templated message from the `refusal` event) so that the refusal returns within seconds; the UI renders `missing[]` and the rejected nearest chunks.
2. backend: a `candidate_evidence` flag on the `retrieve.vector` event payload (or the UI reuses `fused`) so quotes can be shown before the LLM answer; and a `cached: true` field on `run.start` so the UI can show the REPLAY badge.
3. frontend: add `python3 docs/design/contrast_check.py` to `just lint` or CI so token edits cannot regress contrast.
4. agent-engineer: confidence band thresholds (high/medium/low) from eval calibration, currently provisional in 1.4.
