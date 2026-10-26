# Jury FAQ (31 questions)

Status: DRAFT 2, 2026-10-26. Written from the repository and the files named in each answer. **Re-check every tag at the freeze (2026-10-28 12:00).**

Tags answer one question: does the thing exist AND was it verified end to end on the real data and the real stack?
- **[BUILT]** yes: it exists and was run end to end, and the file with the result is named.
- **[DESIGNED]** it is designed, or the code exists and is unit-tested on fake or hand-built data, but it has not been verified end to end on the real graph or the real stack. "Pilot" marks a number measured on a small, partly AI-built set.
- **[TBD]** depends on a measurement that does not exist yet; no number is given and none may be improvised on stage.

State on 2026-10-25/26 (ROADMAP, HANDOFF): all modules exist and are tested on fake and hand-built data (474 Python tests, 50 UI logic tests, CI green). Real runs so far: embeddings and the hybrid index over the 596 chunks; the spike benchmarks; a 12-question answer check of the real agent on the retrieval-only path (graph and MCP off); extraction on the 12 gold chunks and about 30 pipeline chunks. **Not existing yet: the real extracted graph (`graph.sqlite` over the 20 stories) and the real stdio MCP server over it (backlog R-19).** Nothing has run end to end on a real extracted graph. If this is still true at the freeze, every answer that depends on it stays [DESIGNED].

---

**1. What is it, in one sentence?**
A local, CPU-only investigator agent over 20 Sherlock Holmes stories: a small model reads, deterministic rules derive checkable findings, and every answer carries verbatim quotes or is refused. [Text-retrieval path BUILT on a 12-question check; rules, graph and MCP path DESIGNED; `docs/PRD.md`, `docs/HANDOFF.md`]

**2. Why not just ask ChatGPT or any big model?**
A big hosted model is more fluent and we do not claim to beat it on fluency. Ours must attach a verbatim quote to each claim, drops claims it cannot verify, and runs offline. Pilot evidence on one run: asked "What kind of snake killed Dr. Grimesby Roylott?", the bare qwen3:4b-instruct answers that Roylott "was not killed by a snake" and places him in the wrong book; the agent answers "a swamp adder" with the quote "It is a swamp adder!" (`answers-20261023-v3-BARE-qwen3_4b-instruct.jsonl`, `answers-20261023-v3-qwen3_4b-instruct.jsonl`, g001). That is one question; across the three out-of-corpus and adversarial questions the bare model behaved as required on 1 of 3 and the agent on 2 of 3 (`answers-20261023-v3.md`). We do not claim a general rate. [BUILT as a pilot; a full A/B lift is TBD because `eval/run_eval.py` does not exist]

**3. Why Sherlock Holmes?**
Public-domain text, rich in testimony, alibis and contradictions, and small enough to check by hand: 20 stories, about 183k words, 596 chunks. Limit: other genres and languages are untested. [BUILT; `data/LICENSES.md`, `docs/PRD.md`]

**4. What exactly runs, and where?**
Ollama on a laptop (i7-8665U, 4 cores, 15 GiB RAM, no GPU), models of at most 8B parameters, fully offline at run time. Two things were computed elsewhere or are to be: the embeddings index (22 minutes on the laptop, once) and the extracted graph (24-30 h of CPU, on stronger hardware, see question 25). [Offline answering path BUILT in `--fake` mode and on the 12-question check; whole product on the real graph DESIGNED; one-command offline start (AC-13) TBD until tested on a clean machine]

**5. How fast is it? The demo looks slow.**
Measured end to end with the real agent and qwen3:4b-instruct: **42.0 s to the first token and 59.5 s total per question on average, 6.0 tok/s, about 1110 prompt tokens** (12 questions, `answers-20261023-v3.md`). The earlier 15-30 s figure was only the benchmark on a 300-word prompt (`REPORT.md` section 3) and does not include routing and retrieval; do not quote it. That is why the UI shows route, retrieval and quotes while the model reads, and why some steps are labelled recordings. Prefill is the bottleneck (11-23 tokens/s), so the answer context is kept small. Refusals by the gate and rule findings take milliseconds to seconds because no model is called. [BUILT: measurement; finished-system latency on the real graph TBD, measured on Tuesday]

**6. Which model do you use and why?**
Decided: **qwen3:4b-instruct for answers**, **qwen3:4b (think off, constrained JSON) for extraction**, **bge-m3 for embeddings**. The numbers are pilot-level: answers rest on a 12-question check (behaviour correct 8/12 for the 4B-instruct, 6/12 gemma3:4b, 9/12 qwen3:8b; `answers-20261023-v3.md`), extraction on 12 labelled chunks (`REPORT.md` section 6), embeddings on 35 retrieval questions (bge-m3 hit@5 0.89 against 0.46-0.69 for the other four; only bge-m3 handled the 5 Russian questions). The decision rationale is in `REPORT.md` sections 8-9 and `docs/HANDOFF.md` section 3. [BUILT: the measurements and the choice; confidence medium-low]

**7. How do you stop it hallucinating?**
We do not claim to stop it. Three layers: (1) the model sees only retrieved evidence blocks and must cite them; (2) a mechanical self-check requires each quote to be a verbatim substring of the cited chunk and to lexically support its claim, otherwise the answer is retried, shortened to the supported part, or refused; (3) a relevance gate refuses before any model call when the retrieved text does not cover the question. In the 12-question check all five answered questions passed the self-check; two of them needed a second attempt because the first claim was not supported by its quote. Residual risk: a quote can be verbatim and lexically close and still not mean what the sentence says (question 14). [BUILT on the 12-question check (pilot); LLM-judged support check is provisional]

**8. What happens on a question the corpus cannot answer?**
Two paths. The gate refuses without any model call when the retrieved text covers too few of the question's terms: golden question g047 (the Baskerville creature) was refused in 0.01 s with "In these materials there is nothing about this." (`answers-20261023-v3-qwen3_4b-instruct.jsonl`). Otherwise the model may be called and decline: g056 (a fee not in the text) cost an LLM call of 47 s and then a refusal. The gate thresholds (min_score 0.018, min_support 0.25) are provisional (backlog R-13). 2 of 3 out-of-corpus and adversarial questions behaved as required (the false-premise question g057 was refused instead of corrected). [BUILT as a pilot (n=3); refusal precision/recall TBD]

**9. What is GraphRAG doing here that plain retrieval cannot?**
Relational and multi-hop questions: who said what about whom, which statements cannot both hold. The graph links persons, places, events and claims to verbatim quotes. Whether this beats hybrid retrieval is what the A/B eval should measure; the result may be negative and will be reported either way. In the 12-question check the graph was off, so that check is not a test of this layer. [DESIGNED; graph store and rules unit-tested on hand-built data; no real graph yet; lift TBD]

**10. How good is the extraction, honestly?**
Weak on claims and relations. On 12 hand-labelled chunks, qwen3:4b scores strict F1 0.55 on entities, 0.31 on claims, 0.18 on relations; the lenient overlap scorer gives 0.51 / 0.48 / 0.45 (`REPORT.md` section 6). 6.6% of its quotes are not verbatim (quote accuracy 0.934; 7-21% across the six models) and are dropped or re-anchored before entering the graph. The gold labels were written by an AI, are not human-reviewed and not exhaustive, so precision is understated and the 12-chunk differences are noise. Prompt v2.1 was 25% faster than v2.0 (`ab-prompt-v2_1.md`); its quality on the gold chunks is not yet scored. [BUILT: pilot measurement; quality of the full-corpus extraction TBD]

**11. How do you detect a contradiction? Is it reliable?**
By rules, not by asking the model: the model extracts claims and times, and deterministic rules find the conflict (R1 one person, two places, overlapping times; R3 a witness claim against an established fact). The demo case is Wisteria Lodge: Scott Eccles says Garcia spoke to him in the bedroom "nearly one o'clock"; the police say Garcia lay dead on Oxshott Common "since one o'clock" (gold c001). The rule returns `violated`, marked conditional, because "nearly one" and "since one" both normalise to 01:00 and the story day had to be fixed by hand (`docs/symbolic-layer.md` section 11.1). That is a regression test on the real quotes. Reliability on the real extracted graph is TBD, and the gold cases are few (question 28). The confidence is the system's own score, not a calibrated probability. [DESIGNED; unit-tested; not run on a real extracted graph]

**12. What is MCP doing in this project? Is it just decoration?**
The alibi and overlap logic is deterministic interval reasoning in one Python module (rules R1-R3), exposed as the `timeline-alibi` MCP server (`check_alibi`, `find_overlaps`, `build_timeline`), which never calls an LLM and reads facts read-only. A stdio integration test exists and passes. Today the server serves one story from a facts JSON, and the agent otherwise runs the same functions in-process; the real stdio server over the real graph (R-19) does not exist yet, so we cannot say the demo's MCP call is "over the real graph" until it does. A second, off-the-shelf server (filesystem) was dropped from scope. [Server and client BUILT and tested over stdio on a fixture; over the real graph DESIGNED; ADR-0003, `docs/mcp-contracts.md`]

**13. How reliable is the alibi check?**
Limited by how well times are extracted and normalised. Vague times ("late in the evening") give `unknown` or low confidence by design and the tool returns `insufficient_evidence` rather than guessing. A statement by a character is evidence of what was said, not of what happened. Normalisation of clock times, day parts and "since/nearly" cues exists (`extract/normalise.py`) and is tested on real passages, not on the whole corpus. [DESIGNED; precision/recall TBD]

**14. Prompt injection: what if a story contains "ignore previous instructions"?**
Corpus text is data: it goes only into delimited evidence blocks, never into the system prompt, and the UI renders it as plain text. Extraction-time injection is an open item in `docs/security.md`. No claim of immunity: small models can still be steered. [DESIGNED; the injected-chunk test result TBD]

**15. Is the file tool safe? Can the model read my disk?**
The off-the-shelf filesystem server was cut from scope (ROADMAP cut order); the only tool server is our own `timeline-alibi`, which reads the facts store read-only and exposes no write or file-reading tool. [BUILT as a design decision; the claim "no file access" is verified by the tool list in `docs/mcp-contracts.md`, not by a penetration test]

**16. How will you measure quality? What are the numbers?**
What exists: the 12-question answer check (behaviour correct 8/12, answered and verified 5 of 10 answerable, gold chunk cited 5/10, gold span cited 4/10; first token 42.0 s), the retrieval pilot (hybrid RRF k=30, bge-m3: hit@5 0.97 on 35 questions, tuned on the same questions so optimistic; the gold chunk is in the top 4 for 70 of 86 answerable questions = 81%), and the extraction pilot (question 10). What does not exist: the four-configuration A/B runner (`eval/run_eval.py`), contradiction precision/recall on the real graph. Failures are listed, not removed. A difference of one question is noise. [BUILT: pilot numbers in `answers-20261023-v3.md`, `arms-20261023-080849.md`, `evidence-20261023-093201.md`; full eval TBD]

**17. Why is the demo in English only?**
The corpus is English and Russian is optional. With bge-m3 Russian retrieval works (hit@5 1.00 on 5 questions, `REPORT.md` section 4), but the Russian answer question g062 is refused by the relevance gate before the model, because the lexical support check fails across languages. [BUILT measurement; Russian answers unsupported]

**18. Is the demo real or staged?**
Every step says which. The graph and the model answers are real; parts are recordings, labelled `RECORDING` on screen and in speech: the bare-model transcript (a real run from 2026-10-23, kept verbatim), and any stored run. Live: the g001 agent question, the rule finding and the MCP call (if the real stdio server over the real graph exists on the day; otherwise the single-story server, said on stage), the gate refusal, and the `rg` quote checks. No error of the bare model is staged. [DESIGNED; `docs/design/demo-script.md`; final rehearsal results TBD]

**19. What are the known limitations?**
CPU-only speed (about 42 s to the first token); 20 stories; extraction is weak on claims and relations (question 10); gold sets are AI-written; only 4 genuine R1 cases (question 28); entities are scoped per story; confidence is not calibrated; time reasoning is shallow; Russian answers unsupported; the self-check is mechanical (question 14); the gate thresholds are provisional; the real graph and real MCP integration came late. [BUILT/DESIGNED facts from `docs/`]

**20. What would you do with another month?**
A human-labelled gold set for extraction and contradictions; calibrate confidence; the A/B runner and a reranker; cross-story entity merge; better temporal reasoning; the same pipeline on a stronger local model. Ideas, not results. [no measurements]

---

**21. What does "neuro-symbolic" mean here, concretely?**
Two parts with different guarantees. The model reads text and extracts persons, places, times and claims with verbatim quotes: probabilistic, label `extracted`, with confidence. Explicit rules then reason over those facts: R1 one person cannot be in two places in overlapping intervals; R2 event order is transitive and acyclic; R3 a witness claim incompatible with an established fact. Output is deterministic, label `derived` (or `conditional`), with an explanation listing the facts and quotes used. [Rules and explanations BUILT as code with 70 deterministic tests on hand-built and real-quote cases; on a real extracted graph DESIGNED; ADR-0004, `docs/symbolic-layer.md`]

**22. If the model extracts a wrong fact, does the rule layer catch it?**
No. Extraction errors propagate: a misread time or a mis-attributed claim yields a wrong but well-explained finding. With claims at strict F1 0.31 (question 10), this is the main risk, and R1 and R3 consume exactly those claims. Three limits on the damage: every input in the explanation shows its quote, so a human can check it; a finding resting on a low-confidence input is marked `conditional` (as the Wisteria case is); the rules are tested separately from extraction. We claim "follows from the stated facts", not "true in the story". [DESIGNED; propagation rate on the real graph TBD]

**23. What is actually proven, and how do you know the rules are right?**
Only that the conclusion follows from the facts given, by explicit code. The rules are a pure Python module tested on hand-built graphs with hand-worked answers, including boundary cases (touching intervals, cycles, unknown times), plus regression tests on real quotes. The MCP tool wraps the same module. Rules are correct relative to their written definition, not to every reading of a novel. [BUILT: tests pass; correctness against real extracted data TBD]

**24. How do you measure the contradiction finder, and is it better than asking the model?**
Separately from answer quality: precision and recall on the gold contradictions (`eval/golden/contradictions.jsonl`, 43 cases including consistent controls), and the false-positive rate on controls. Not measured yet on the real graph; whether it beats a model judging pairs directly is not measured, and no number is stated. [TBD]

---

**25. What does "verified" mean? Is a verified answer true?**
No. "Verified" means two mechanical things: every quote is a verbatim substring of the chunk it cites, and the claim is lexically supported by the quote (shared content words). It does not mean the claim is true, that the quote is the best evidence, or that the model understood it. Example from the check: g028 passed the self-check on its second attempt, after the first claim was rejected as "not supported by its quote". Also, a character's statement is evidence of what was said, not of what happened. [BUILT; limits stated in `answers-20261023-v3.md` caveats]

**26. Why were only 5 of 10 answerable questions answered and verified?**
From the per-question table (`answers-20261023-v3-qwen3_4b-instruct.jsonl`): g001, g028, g019, g022, g038 answered and verified. Of the other five: g007 (the model declined although the gold chunk was retrieved), g032 (the gold chunk was not retrieved, model declined), g016 (partial: one claim uncited, one not supported by its quote), g057 (false premise: model declined instead of correcting it), g062 (Russian, refused by the gate). So the misses are mostly retrieval (the gold chunk is in the top 4 for 81% of answerable questions, but the evidence needed is inside the prompt for only 66-69%, `evidence-20261023-093201.md`) and a cautious 4B model. n=12, one run, temperature 0: one question is 8 points. Strictness is a feature (refuse rather than invent) but it costs coverage: mean coverage on answerable questions is 0.33 (crude proxy). [BUILT: pilot]

**27. The gold sets were written by an AI. Why trust the numbers?**
Partly we do not. The golden questions, the contradiction cases and the extraction labels were written by a Claude agent and were not reviewed by a human (`eval/golden/README.md`); a human spot-check of 10 questions and 4 extraction chunks is on the list. Consequences: precision numbers are underestimates (gold is not exhaustive), recall is more trustworthy, and some labels are debatable (c042 is flagged low-confidence; g027 and c042 disagree). The retrieval parameters were tuned on the same questions they are scored on, so 0.97 is optimistic. Every number in this project is therefore a pilot number. [BUILT: caveats stated in every metric file; human review TBD]

**28. Only 4 genuine R1 cases? Is that a demonstration or a result?**
A demonstration. The corpus has only 4 genuine R1 (person in two places) and 3 R2 (order cycle) cases, and R3 dominates (`docs/HANDOFF.md` section 5). The demo shows one of the four, with the case chosen because the text itself calls the conflict "perfectly impossible"; no recall or precision for R1 can be claimed from four cases, and we do not. [BUILT: counts; precision/recall TBD]

**29. Why is McCarthy vs Crowder not flagged as a contradiction?**
Because it is not a conflict of observed facts (gold c042, a consistent control). Both agree James went the same way with a gun a few minutes after his father; they differ on whether he was deliberately following, which the gamekeeper gives as "his belief" and James denies as intent. Intent is not a checkable proposition, so rule R3 correctly returns no violation (regression test on the real quotes, `docs/symbolic-layer.md` section 11.1). Honest caveat: c042 is itself low-confidence, and the golden question g027 treats the same pair as a conflict between accounts; whether an inference against a denial counts as a contradiction is a labelling decision for a human. The rules were not run on the real extracted graph for this case. [DESIGNED]

**30. Why a 4B model? Is that not too small?**
Two reasons: the hardware limit and the measurements. The laptop has no GPU and 15 GiB RAM; the PRD sets a limit of 8B. qwen3:4b-instruct against qwen3:8b on the same 12 questions: behaviour correct 8/12 against 9/12, answered and verified 5/10 against 5/10, first token 42.0 s against 101.1 s, resident memory about 3.2 GiB against 6.0 GiB, and sustained 7-8B load throttled the CPU to 96 C (`REPORT.md` sections 2-3, 9). The 8B is at most one question better, which is noise at n=12, and 2.4 times slower. It is too small to reason well: that is why reasoning is left to rules and the model only reads, extracts and phrases; and its weakness shows in claims (F1 0.31) and cautious refusals (question 26). A stronger model would likely help and is not measured. [BUILT: measurements, pilot]

**31. Where was the extraction done? Did you cheat the CPU limit?**
Answering runs on the laptop. Extracting 596 chunks takes about 179.7 s per chunk with qwen3:4b, projected at 29.7 h (`REPORT.md` section 7; 24-30 h in `docs/HANDOFF.md`), which does not fit before the show, so the extraction is precomputed on stronger machines with the same model tag, prompt, temperature 0 and seed 42, and the resulting cache and graph are copied to the laptop. We say this on stage. The same inputs give the same cache entries (determinism is checked by `merge_extract_cache.py verify` on the partial cache); the laptop does not run extraction during the talk. Whether the competition allows precomputing on other hardware was asked of the organizers (ROADMAP); the answer will be written here. [DESIGNED/in progress: at the time of writing the graph has not been built; answer from organizers TBD]
