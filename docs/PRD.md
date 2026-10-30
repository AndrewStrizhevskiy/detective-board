# PRD: Detective Board

Status: draft 2, 2026-10-23. Phase 0 spike done except the answer-model check (docs/spike/REPORT.md). Numeric targets are filled in only where a spike measurement justifies them (latency); all others stay TBD until the first eval run.

## 0. Positioning
Detective Board is a **neuro-symbolic system**. The LLM extracts knowledge from text (probabilistic, may err). The graph stores it with source quotes. Deterministic rules then draw inferences that can be verified: each inference comes with an explanation listing the facts and edges used and their source quotes. The model guesses; the rules prove, and say what they proved from. Design: `docs/adr/0004-symbolic-layer.md`, `docs/symbolic-layer.md` (planned, not built).

Provenance labels on every statement shown to the user: `extracted` (made by the model, probabilistic, with confidence) and `derived` (made by a rule, deterministic, with explanation). A `derived` statement that rests on a doubtful `extracted` fact is marked `conditional`.

## 1. Problem
Long-form fiction is hard to interrogate. A reader asking "who could not have been at the scene?" must re-read dozens of stories. Plain LLM chat invents facts and quotes. We need an agent that investigates a fixed corpus, shows its evidence, and says "not in the corpus" when it is not.

## 2. Users
- Competition jury: judges engineering quality, honesty of answers, measured quality, and fit to the brief (agent, RAG/GraphRAG, MCP).
- Demo audience (live, 7 minutes): must see in seconds what the agent does and why it can be trusted.
- Secondary: developers running the repo from a clean checkout.

## 3. Goals
1. Answer questions about ~20 Sherlock Holmes stories using only the corpus, every claim with a verbatim quote and story reference.
2. Find contradictions between claims and check alibis, each finding with its supporting quotes and an explanation. Findings come from deterministic rules (R1 one person cannot be in two places in overlapping intervals; R2 before/after order is transitive and has no cycle; R3 a witness claim incompatible with an established fact is a contradiction). Confidence is attached only to `extracted` facts; a `derived` finding is exact given its inputs and is marked `conditional` when an input is doubtful.
3. Refuse honestly when the corpus does not support an answer.
4. Show the investigation: live graph of persons, places, items, events, claims, plus a trace of every step and tool call.
5. Expose capabilities as MCP tools (own server(s) plus a standard third-party/filesystem-style tool where useful).
6. Measure quality: A/B eval of baseline RAG vs hybrid vs GraphRAG vs full agent, and, separately, contradiction detection by the rules (precision/recall on gold cases), not mixed into answer quality.
7. Rules are one module of pure Python; the MCP server `timeline-alibi` and the agent call the same code (single source of truth), and the rule tests are deterministic and green.

## 4. Non-goals
- Other corpora, user uploads, multi-user, auth, cloud or hosted models.
- Fine-tuning or training models.
- Chat of general knowledge about Holmes outside the corpus text.
- Mobile UI, i18n, persistence of sessions beyond the demo.
- Temporal-graph subtleties beyond what alibi checks need.
- A general reasoner or ontology: only the rules R1-R3 (plus any added later by ADR); no learned or LLM-judged inference in the symbolic layer.
- Correcting extraction errors: the rules do not repair the graph (see limitation in section 6).

## 5. Product description
- Corpus: 20 stories, 596 chunks, 183k words (see docs/spike/).
- Knowledge graph: nodes Person, Place, Item, Event, Claim; edges link to source chunk and quote span. Claims carry speaker, subject, time/place if stated.
- Investigator agent: router picks a path (plain retrieval, graph traversal, contradiction/alibi tools, refusal), then a self-check verifies that each quote exists in the retrieved text and supports the claim before the answer is shown.
- Retrieval: hybrid (lexical plus embeddings) with graph expansion.
- Answers: short text, inline quotes with story/chunk reference, confidence for findings. If evidence is insufficient: explicit refusal stating what was searched.
- Symbolic layer (planned): rules R1-R3 over the graph give `derived` findings; each carries an explanation object (rule id, facts and edges used, source quotes). Contradiction/alibi detection = the rules; the LLM only extracts and phrases. Output lists both quotes.
- UI (investigation board): question box, live graph that grows as the agent works, trace panel (steps, tool calls, retrieved chunks, timings), answer panel with quotes.
- MCP tools: corpus search, graph query, contradiction check, alibi check (the last two delegate to the rules module), plus a sandboxed file/tool server. Tool calls visible in trace.
- Corpus text is data, never instructions.

## 6. Constraints
- Hardware: laptop i7-8665U, 4 cores, 15 GiB RAM, CPU only.
- Models: Ollama, at most 8B parameters, fully offline at run time.
- Measured generation speed here: gemma3:4b, phi4-mini, qwen3:4b about 7-7.8 tok/s; qwen2.5:7b 4.9 tok/s; qwen3:8b 4.3 tok/s. Time to first token 15-30 s for a 300-word prompt. Consequence: few LLM calls per question, short prompts and outputs, stream progress to the UI, precompute graph extraction offline, cache demo questions.
- One-command run (via `just`), no network needed after setup.
- Show date 2026-10-30; talk 7 minutes; freeze 2026-10-28/29.
- Never cut: working demo, citations, honest refusals, quality measurements.
- **Limitation: extraction errors pass into the symbolic layer.** Rules are exact on the graph they get, not on the story. A wrongly extracted time, place or speaker yields a wrong but well-explained `derived` finding. Mitigations: explanations show the source quote of every input; findings built on low-confidence inputs are `conditional`; extraction quality is measured separately (gold set) and reported. We do not claim the output is true, only that it follows from the stated facts.

## 7. Success metrics (targets mostly TBD)
Only the latency target and the rule-determinism target are numeric. Everything else stays TBD on purpose: the spike measured speed and retrieval, not answer quality, and its gold sets were generated automatically and not reviewed by a human. The right column gives the spike evidence, not a target.

| Metric | Definition | Target | Spike evidence |
|---|---|---|---|
| Citation validity | share of answer quotes found verbatim in cited chunk | TBD | none yet; for extraction, 79-93 % of quotes were verbatim (REPORT section 6) |
| Answer correctness | on eval set (spike_questions plus gold), judged per rubric | TBD | answer-model check PENDING (REPORT section 9) |
| Refusal precision/recall | out-of-corpus refused; in-corpus not refused | TBD | none |
| Contradiction/alibi quality | precision/recall of rule-found contradictions vs gold cases, reported separately from answer quality | TBD | none; only 4 R1 and 3 R2 real cases exist |
| Rule determinism | rule unit tests (hand-built mini graphs, boundary cases) pass, identical result on repeated runs | 100% green | not a spike measurement |
| Explanation completeness | share of `derived` findings whose explanation lists every used fact with a verbatim source quote | TBD | none |
| Retrieval | chunk-level hit@5 of hybrid retrieval on the spike questions | TBD | 0.97 (n=35, parameters tuned on the same questions, so optimistic; vector-only 0.89) (`arms-20261023-080849.md`) |
| A/B lift | agent vs baseline RAG on same set | TBD | none |
| Latency, final answer | time from question to complete answer, 4B model, 150-token answer | provisional budget: at most 40 s | qwen3:4b: TTFT 17.2 s + 150 tokens / 7.07 tok/s = 38.4 s (`llm-20261022-171654.md`; the 150-token length is an assumption; an 8B model would take about 64 s) |
| Latency, first visible trace event | time to first visible trace event | TBD | not measured |
| Cold start | one command to usable UI | TBD | embedding index build is a one-off 22 min with bge-m3 (`embed-20261022-180354.md`: 0.46 chunks/s); graph extraction of 596 chunks is about 30 h with qwen3:4b, so both must ship precomputed |
| Demo reliability | rehearsal runs completed without intervention | TBD | none |

Targets are set after the first eval; results are reported as measured, including bad ones.
