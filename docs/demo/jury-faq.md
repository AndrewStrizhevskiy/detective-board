# Jury FAQ (24 questions)

Status: DRAFT 1, 2026-10-22. Written from the repository as it is today. **Re-check every status tag at the freeze (2026-10-28).**

Tags: **[BUILT]** exists in the repo and was run/tested on 2026-10-22. **[DESIGNED]** only in docs (PRD, ADR, c4, data-schema, mcp-contracts); not implemented at the time of writing. **[TBD]** depends on a measurement that does not exist yet; the number is not stated here and must not be improvised on stage. If a [DESIGNED] item is still not built at the freeze, change the answer to "planned, not done".

What exists today (2026-10-22): corpus fetch/ingest scripts, 20 cleaned stories, 596 chunks, a chunk-level extraction schema (v1) with a grounding rule, a 12-chunk extraction gold set labelled by an agent (not a human, not reviewed), latency and embedding benchmarks, 20 spike questions, unit tests for ingest and extraction scoring, ADRs 0001-0003, and design documents. Not built yet: the symbolic layer (rules R1-R3, provenance labels), retrieval layer, graph layer, agent, MCP servers, UI, eval runner.

---

**1. What is it, in one sentence?**
A local, CPU-only investigator agent over 20 Sherlock Holmes stories that answers only with verbatim quotes, checks contradictions and alibis, shows its work on a live board, and refuses when the corpus does not support an answer. [DESIGNED; PRD section 5]

**2. Why not just ask ChatGPT or any big model?**
Because it answers from memory and cannot prove anything. Ours must attach a verbatim quote and chunk reference to each claim and drops claims it cannot verify. The demo shows this on one question and the eval will report it across a set (A/B lift: [TBD]). A big hosted model would probably also be more fluent; we do not claim to beat it on fluency, only on verifiability and offline operation.

**3. Why Sherlock Holmes?**
Public-domain text (all stories first published before 1931), rich in testimony, alibis and contradictions, and small enough to check by hand: 20 stories, about 183k words, 596 chunks. [BUILT; `data/LICENSES.md`, `docs/PRD.md`] Limit: other genres and languages are untested.

**4. What exactly runs, and where?**
Ollama on a laptop (i7-8665U, 4 cores, 15 GiB RAM, no GPU), models of at most 8B parameters, fully offline at run time. The corpus was downloaded once; after that no network is needed. [Hardware and models BUILT as benchmarks; whole product DESIGNED; offline one-command start AC-13 is [TBD] until tested.]

**5. How fast is it? The demo looks slow.**
Measured (spike, Ollama 0.35.0, temperature 0): generation 4.3 tok/s (qwen3:8b) to about 8.5 tok/s (4B models); time to first token about 15-30 s on a 300-word prompt, 1.5-4 s on a 52-token prompt. [BUILT: `docs/spike/results/llm-*.md`] That is why every step of the UI streams non-LLM progress (route, retrieval, tool calls, quotes) before the model speaks, and why the demo uses stored runs, labelled REPLAY. End-to-end latency of the finished system: [TBD].

**6. Which model do you use and why?**
Not decided. The spike compared gemma3:4b, phi4-mini, qwen3:4b, qwen3:4b-instruct, qwen2.5:7b and qwen3:8b on speed only; there is no ADR for model choice yet, and quality per role is not measured. [TBD]

**7. How do you stop it hallucinating?**
Three layers, none of them a promise: (1) the model is only given retrieved evidence blocks and must cite them by id; (2) a mechanical self-check requires every quote to be a verbatim substring of the cited chunk, otherwise the quote is dropped or the answer refused; (3) a refusal path when evidence is insufficient. [DESIGNED; AC-02, AC-03; c4 Flow B] Residual risk: a quote can be verbatim and still not support the claim; the LLM-judged support check is provisional. Measured citation validity: [TBD].

**8. What happens on a question the corpus cannot answer?**
It refuses, lists what it searched, and quotes only what the text does support. Demo example: the Reichenbach Falls question; the corpus mentions Moriarty exactly once (his death, in the Norwood Builder) and nothing about the falls (checked with `rg` on the cleaned texts). [Behaviour DESIGNED; corpus facts BUILT.] Refusal precision/recall: [TBD].

**9. What is GraphRAG doing here that plain retrieval cannot?**
Relational and multi-hop questions: who said what about whom, which claims conflict, who was at which place. Extraction produces persons, places, items, events and claims with a verbatim quote for each; the graph links them with source anchors. Whether this beats hybrid retrieval is exactly what the A/B eval measures; the result may be negative and will be reported either way. [DESIGNED; schema BUILT; lift [TBD]]

**10. How good is the extraction, honestly?**
Unknown. There is a schema with a grounding rule (a quote not found verbatim in the chunk is dropped) and a 12-chunk gold set, but the gold labels were written by an agent, were not reviewed by a human, and are not exhaustive; scoring code exists with unit tests. No extraction run with a model has produced reported numbers. [BUILT: schema, gold, scorer; quality [TBD]]

**11. How do you detect a contradiction? Is it reliable?**
By rules, not by asking the model: the model extracts claims and times into the graph, and deterministic rules (R1 one person in two places at once, R3 a witness claim against an established fact) find the conflict; the answer shows both quotes and the explanation. See questions 21-24. When claims are consistent it must report none found. [DESIGNED; AC-05, AC-06.] The demo case is James McCarthy vs the gamekeeper in The Boscombe Valley Mystery. Reliability (precision/recall on gold cases): [TBD], and the gold cases are few. The confidence is the system's own score, not a calibrated probability, unless calibration is measured. [TBD]

**12. What is MCP doing in this project? Is it just decoration?**
The alibi/timeline logic is deterministic interval reasoning (rules R1/R2 in a pure Python module that the MCP tool wraps, planned) over dated events with source anchors, which small models do badly, so it lives in a separate tool server (`timeline-alibi`: `check_alibi`, `find_overlaps`, `build_timeline`) that never calls an LLM and reads the index read-only. The agent calls it over MCP stdio and the call appears in the trace. A second, off-the-shelf server (filesystem) is planned with an allowlist. [DESIGNED; ADR-0003 and `docs/mcp-contracts.md`, SDK details unverified.] Works on the demo story only if time normalisation covers it: [TBD].

**13. How reliable is the alibi check?**
Limited by how well times are extracted. Temporal subtleties (ordering, durations) are priority P2 and may be cut (backlog T-14); vague times ("late in the evening") yield `unknown` or low confidence by design, and the tool returns `insufficient_evidence` rather than guessing. A statement by a character is evidence of what was said, not of what happened. [DESIGNED] Precision/recall: [TBD].

**14. Prompt injection: what if a story contains "ignore previous instructions"?**
Corpus text is data. It is placed only inside delimited evidence blocks, never in the system prompt; the UI tags it as corpus text and renders plain text; tool calls triggered only by corpus text are a failure. A test chunk with an injected instruction is planned (AC-16, T-20, T-26). [DESIGNED; test result [TBD].] No claim of immunity: small models can still be steered.

**15. Is the file tool safe? Can the model read my disk?**
Planned two-layer allowlist: the server is started with only the corpus directories, and our MCP client resolves paths (symlinks followed) and rejects anything outside, including `..`; write tools are not exposed to the model. [DESIGNED; AC-17; implementation and tests [TBD].]

**16. How will you measure quality? What are the numbers?**
Eval set = the 20 spike questions (15 English, 5 Russian) plus gold to be added, comparing baseline RAG, hybrid, GraphRAG and the full agent on citation validity, correctness, refusal precision/recall, contradiction/alibi quality, latency. Numbers: [TBD]. Targets in the PRD are TBD on purpose until the first eval. Failures are listed, not removed (AC-15). The set is small; a difference of one question is noise. A current smoke result: embedding retrieval (nomic-embed-text, 768-dim) put the expected story in the top 5 for 15/15 English questions and 1/5 Russian ones (n=5). [BUILT: `docs/spike/results/embed-*.md`]

**17. Why is the demo in English only?**
Because the corpus is English and the only Russian result so far is weak (hit@5 0.20, n=5, with the English embedder tested). Multilingual support is a non-goal for this version. [BUILT measurement; PRD non-goals]

**18. Is the demo real or staged?**
Some runs are stored real runs replayed because first-token latency is 15-30 s on long prompts; each is labelled REPLAY on screen, uses the original event order and recorded outputs, and the alibi and refusal steps are run live if they are fast enough in rehearsal. The comparison question uses a live bare-model run, with a recorded fallback. [DESIGNED; `docs/design/demo-script.md`] What happens in the final rehearsals: [TBD].

**19. What are the known limitations?**
CPU-only speed; only 20 stories; extraction quality unmeasured; entities are scoped per story (cross-story merge deferred); confidence is not calibrated; time reasoning is shallow; Russian unsupported; the self-check is mechanical first (a verbatim quote can still be misleading); storage and graph engine choices are Proposed in ADRs, not yet validated by measurement. [BUILT/DESIGNED facts from `docs/`]

**20. What would you do with another month?**
Human-labelled gold set for extraction and contradictions; calibrate confidence; test larger/multilingual embedders and a reranker; cross-story entity merge; stronger temporal reasoning; measure the same pipeline on a stronger local model if hardware allows. These are ideas, not commitments or results. [PLANNED, no measurements]

---

**21. What does "neuro-symbolic" mean here, concretely?**
Two parts with different guarantees. The LLM reads the text and extracts facts (persons, places, times, claims) with verbatim quotes: probabilistic, label `extracted`, with confidence. A small set of explicit rules then reasons over the graph: R1 one person cannot be in two places in overlapping intervals; R2 event order (before/after) is transitive and must have no cycle; R3 a witness claim incompatible with an established fact is a contradiction. Their output is deterministic, label `derived`, with an explanation listing the facts, edges and source quotes used. [DESIGNED; ADR-0004, `docs/symbolic-layer.md`; not built yet. Do not say "built" until T-36/T-37 are done.]

**22. If the model extracts a wrong fact, does the rule layer catch it?**
No. Extraction errors pass through the rules: a misread time yields a wrong but well-explained finding. We limit the damage three ways: every input in the explanation shows its quote so a human can check it; findings that rest on a low-confidence extracted fact are marked `conditional`; extraction quality is measured separately on a gold set that is small and agent-labelled today. We claim "follows from the stated facts", not "true in the story". [DESIGNED; PRD section 6; extraction quality [TBD]]

**23. What is actually proven, and how do you know the rules are right?**
Only that the rule conclusion follows from the facts given, by explicit code. The rules are a pure Python module tested on hand-built mini graphs with answers worked out by hand, including boundary cases (touching intervals, cycles, unknown times); the target is 100% green and identical results on repeated runs. The MCP alibi tool calls the same module, so there is one implementation. [DESIGNED; AC-23, AC-25; tests not written yet. Rules are correct relative to their written definition, not relative to every reading of a novel.]

**24. How do you measure the contradiction finder, and is it better than asking the model?**
It is measured separately from answer quality: precision and recall of rule-found contradictions on gold cases, including cases lost because extraction missed a fact (T-39). Whether it beats a model judging pairs directly is not measured; no number is stated here. Gold cases are few, so one case is noise. [TBD]
