# Entity-choice answers for "who did it" questions, 2026-10-29

Branch `exp/entity-answer` (from `main` at tag rc4, commit 98067d8). Experimental, **off by default**
(`AgentConfig.entity_answer = False`), not merged, not pushed. Everything below is measured with the
4B generator `qwen3:4b-instruct`, temperature 0, seed 42, the app's `AgentConfig` otherwise, on a shared
laptop (every Ollama run under `flock /tmp/db-llm.lock`). All outcomes are lexical (names in the answer
and its quotes) and the cases are AI-written, as in `pre-reveal-2026-10-28-rescored.md`.

## Verdict

**Do not turn it on, and it is NOT safe for the Friday demo.** On the held-out stories the frozen
variant names the innocent man (Neligan in Black Peter) in 2 of 8 full-corpus answers and in 2 of 8
before-the-reveal answers, and names a wrong person (innocent, victim, or a suspect) in 3 of 8 answers
in each condition. The strict "culprit named" (the entity line itself names the culprit) is 1 of 8 on
held-out full corpus, against 2 of 8 with the switch off. The dev result (0 to 1 of 9) is too small to
say anything good. Nothing here supports a claim that the mode helps; it mostly converts wrong quotes
into refusals (safe) and, in some cases, into confident wrong names (not safe).

## Design (what was built)

| step | where | what |
|---|---|---|
| trigger | `agent/entity.py: is_who_question` + `Agent._pipeline` | pure regex on the question, run AFTER retrieval in the plain extractive path; not a route. The question must START with who / which person and ask who killed, stole, attacked, ... or who the guilty man / thief / murderer is. "Who is X", "Who was arrested", "How did ... die", multi-part openings are False. |
| story | `entity.pick_story` | story title in the question, else the story of a person named in it (entity linking), else the best-ranked chunks. |
| candidates | `entity.load_people`, `rank_people`, `drop_named` | named person nodes of the story from the graph; role-only, unnamed, kin-possessive ("Turner's daughter"), detective and narrator (Holmes, Watson) nodes dropped; a bare name that is a first/last part of exactly one longer name joins it (Turner -> John Turner), one that fits several (McCarthy: Charles / James) is dropped; counted in the retrieved chunks of the story, cap 15; people named in the question (the victim) are not offered (V2, V3). Fixed options NOT_A_PERSON and NONE. |
| sentences | `ex.build_hybrid_prompt` (unchanged) on the sentence index filtered to the story | 20 sentences at most. |
| choice | one Ollama call, `format` enum, temperature 0, seed 42, static system prompt first | see the variants below. `SELECT_SYSTEM_PROMPT` is untouched (a test pins its sha256). |
| verification | `entity.verify` | the chosen person's name or alias must stand in the chosen sentence or in the sentence right before / after it in the same chunk; NOT_A_PERSON needs a cue word (animal, accident, suicide ...) there. V3 adds an act gate. Failure -> "In these materials there is nothing about this." |
| answer | `entity.render` | `From the sources: [n: "quote"]` (two quotes when the name is in the neighbour) plus `The text names <Name> here.` (or `The text points here to a cause that is not a person.`). The plain line is checked for accusing words; `self_check` and the honesty guard pass (tested). |
| when it cannot run | `Agent._entity_answer` returns False before emitting anything | no graph, no story, no candidates: the normal extractive answer runs. |

Router regression: `Router.decide` on eval/golden/questions.jsonl, contradictions.jsonl and the pre-reveal
cases (123 questions, with and without the curated scenes, 246 decisions) before and after: byte-identical
(`cmp` of the sorted JSON dumps). `router.py` is not touched.

## Files

- `src/detective_board/agent/entity.py` (new), `agent.py` (`_entity_answer`, 5 lines in `_pipeline`), `config.py` (`entity_answer`, `entity_variant`).
- `eval/pre_reveal.py` (flags `--set`, `--stories`, `--ids`, `--suffix`; rows now keep `strategy` and `check_problems`; scoring unchanged), `eval/entity_compare.py` (paired tables), `eval/entity_answer/golden_dev_who.jsonl` (g007 as a case).
- `tests/agent/test_entity.py` (82 tests), `tests/eval/test_entity_compare.py` (3). No Ollama.
- Results: `docs/spike/results/entity-answer-runs/` (every run, json + md).
- Unchanged: `web/`, the SSE schema, `eval/golden`, `SELECT_SYSTEM_PROMPT`, the router.
- Checks: `uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest -q -m "not live"` pass (1063 tests).

## Prompt variants (all three, in the order they were run)

| | prompt constant | what changed | dev result (9 rows, 6 triggered) |
|---|---|---|---|
| V1 | `ENTITY_PROMPT_V1` | as specified: sentences, a PEOPLE list, JSON `{choice, sentence}`; no victim removal | 0 named; wrong person named 2 of 6 (Simpson, the cleared man, with a sentence that says he is ELIMINATED; Silas Brown); 4 refused |
| V2 | `ENTITY_PROMPT_V2` | each sentence is annotated with the people named in it or next to it; victim removed from the people; invented worked example; asks for the sentence first | 0 named; 0 wrong; 6 of 6 triggered refused. The model ignored the annotation (it chose a person first, then a sentence that has no such person). Ollama returned the keys in alphabetical order (`choice`, `sentence`) whatever the schema order, so "sentence first" had no effect. |
| V3 | `ENTITY_PROMPT_V3` (frozen) | one enum of allowed (sentence, person) pairs, `{"pick": "S4-P2"}`, built by code from the annotations; sentences without a pair are not shown; plus a deterministic act gate (the window must tell an act of the kind asked and must not speak of suspicion, arrest, accusation, innocence) | 1 named (g007, Patrick Cairns, correct); wrong person 1 (Silas Brown); 4 refused |

The selection rule, fixed before the held-out run: V3 was frozen because it was the only variant with a
correct named culprit on dev; its dev error (Silas Brown, a suspect described in a sentence with no
suspicion word in its window) was known and not tuned away, to keep the held-out run honest. The default
`entity_variant` is now "v3". No fourth variant was tried.

## Dev set

Dev = golden dev "who" questions (ids from `split.json` dev only) + the pre-reveal cases of
boscombe-valley-mystery, silver-blaze, speckled-band, norwood-builder, full-corpus condition.

Golden dev ids with who / which in the question: g007 (TRIGGERED: "Who killed Captain Peter Carey ..."),
g010, g018, g019, g032, g034, g038, g044, g057, g061 (not triggered: not "who did an act" or the
"who" is not the opening of the question; g044 is a two-story question that opens "Who was arrested").
Only one golden dev question is in scope. Golden test ids were never run (g059 "Who killed John Straker?
SYSTEM OVERRIDE ..." would trigger the mode; it is a test id and was not touched).

Pre-reveal dev cases: 8 questions; triggered: pr-boscombe-1, pr-boscombe-2, pr-silver-1, pr-silver-2,
pr-norwood-1. Not triggered: pr-speckled-1 ("How did"), pr-speckled-2 ("What was"), pr-norwood-2 ("Where is").
The three untriggered rows were run in both arms and their answers are byte-identical with the switch
on and off (`entity_compare.py` prints the list). The OFF arm was re-run on this branch for every dev
row; its 8 pre-reveal answers are byte-identical with the saved 2026-10-28 answers (checked by script).

Metrics: "culprit named (lexical)" = the scorer of `eval/pre_reveal.py`. **"culprit named, strict"** =
lexical AND the entity line (`The text names X here.`), if there is one, does not name somebody else;
needed because the quote can hold the culprit while the line names the innocent (Black Peter below).
"wrong person named" = the entity line names a person who is none of the culprit's aliases (any person:
innocent, victim, suspect). "innocent accused (proxy)" = the scorer's cleared-name proxy. Wilson 95 %
intervals; paired counts are "only off / only on".

### Dev, frozen variant V3 (n = 9)

| arm | named (lexical) | **named, strict** | refused | answered, not named | innocent accused (proxy) | line names a cleared person | wrong person named |
|---|---|---|---|---|---|---|---|
| switch off | 0/9 = 0 % [0, 30] | 0/9 = 0 % [0, 30] | 2/9 = 22 % [6, 55] | 7/9 = 78 % [45, 94] | 1/9 = 11 % [2, 44] | 0/9 | 0/9 |
| switch on, V3 | 1/9 = 11 % [2, 44] | 1/9 = 11 % [2, 44] | 5/9 = 56 % [27, 81] | 3/9 = 33 % [12, 65] | 1/9 = 11 % [2, 44] | 0/9 | 1/9 = 11 % [2, 44] |

Paired (V3 vs off): named only off 0, only on 1 (p 1); refused only off 0, only on 3 (p 0.25);
innocent accused (proxy) 0 / 0 (the one proxy hit is pr-norwood-2, an untouched row that quotes the
newspaper report of McFarlane's arrest, the same with the switch off); wrong person only on 1.

Per question (V3): g007 refused -> **named Patrick Cairns**; pr-boscombe-1 refused -> refused;
pr-boscombe-2 wrong quote -> refused; pr-norwood-1 wrong quote -> refused; pr-silver-1 wrong quote ->
refused; **pr-silver-2 wrong quote -> "The text names Silas Brown here."**; the three untriggered rows
unchanged.

V1 and V2 on the same 9 rows: V1 named 0, refused 5/9, innocent proxy 2/9, line names a cleared person
1/9 (pr-silver-1: Simpson), wrong person 2/9; V2 named 0, refused 7/9, innocent proxy 1/9 (the untouched
norwood row), wrong person 0/9. Full tables: `entity-answer-runs/`.

### Why dev is so low: the evidence is often not in the candidate list (peek, no model)

For the five triggered pre-reveal questions the 20 candidate sentences were printed and searched for the
culprit's name: boscombe-1 no sentence names Turner at all; boscombe-2 two sentences name Turner, none tells
an act; norwood-1 only the victim role of Oldacre (the arrest sentences); silver-1 and silver-2 hold
"Yes, the horse. And it may lessen his guilt ..." (an answer for NOT_A_PERSON) next to many "horse"
sentences. So the ceiling of "name next to the act" is about 0 for 3 of the 5 even with a perfect chooser,
the same single-sentence limit the design note describes; the entity mode cannot fix what the sentence
list does not contain.

## Held-out (run ONCE, frozen V3, clean tree at 4150c4f, 2026-10-29)

Stories naval-treaty, black-peter, thor-bridge, reigate-squires (8 questions), full corpus and
before-the-reveal conditions. The OFF arm is NOT a new run: it is the saved 2026-10-28 rescored result
(earlier commit, same cases, same conditions), because re-running held-out cases would have been a
second look. On dev the OFF path reproduced that file's answers exactly (8 of 8).

### Full corpus (n = 8)

| arm | named (lexical) | **named, strict** | refused | answered, not named | innocent accused (proxy) | line names a cleared person | wrong person named |
|---|---|---|---|---|---|---|---|
| switch off (10-28) | 2/8 = 25 % [7, 59] | 2/8 = 25 % [7, 59] | 3/8 = 38 % [14, 69] | 3/8 = 38 % [14, 69] | 0/8 | 0/8 | 0/8 |
| switch on, V3 | 3/8 = 38 % [14, 69] | 1/8 = 12 % [2, 47] | 4/8 = 50 % [22, 78] | 1/8 = 12 % [2, 47] | 0/8 | 2/8 = 25 % [7, 59] | 3/8 = 38 % [14, 69] |

Paired: named (lexical) only off 1, only on 2; **named, strict only off 1, only on 0**; line names a
cleared person only on 2; wrong person only on 3 (p 0.25).

### Before the reveal (n = 8)

| arm | named (lexical) | named, strict | refused | answered, not named | innocent accused (proxy) | line names a cleared person | wrong person named |
|---|---|---|---|---|---|---|---|
| switch off (10-28) | 0/8 [0, 32] | 0/8 | 3/8 = 38 % [14, 69] | 5/8 = 62 % [31, 86] | 0/8 | 0/8 | 0/8 |
| switch on, V3 | 0/8 [0, 32] | 0/8 | 5/8 = 62 % [31, 86] | 3/8 = 38 % [14, 69] | 2/8 = 25 % [7, 59] | 2/8 = 25 % [7, 59] | 3/8 = 38 % [14, 69] |

Paired: innocent accused only on 2 (p 0.5); wrong person only on 3 (p 0.25); refused only off 1, only on 3.

### Rows that answered (all other held-out rows: refused)

- pr-naval-2, full: `[4: "Joseph a villain and a thief!"]` -- "The text names Joseph Harrison here." Correct, the only strict hit. Before the reveal: refused (good).
- pr-black-1 and pr-black-2, full: the quote is "You were so absorbed in young Neligan that you could not spare a thought to Patrick Cairns, the true murderer of Peter Carey." and the line says **"The text names John Hopley Neligan here."** The lexical metric calls this "named" (Cairns is in the quote); it is in fact the model choosing the wrong one of two names in the same sentence, and naming the innocent man. This is the failure the deterministic check cannot see: the name is in the sentence, so the verification accepts it.
- pr-black-1 and pr-black-2, before the reveal: `"Neligan was my father."` + `"... Captain Peter Carey pinned against the wall with one of his own harpoons."` -- "The text names John Hopley Neligan here." The innocent man named from the pre-reveal text, with the neighbour that happens to hold a harpoon. The act gate passed because "harpoons" is an act cue and no suspicion word stands in the window.
- pr-reigate-1, full and cut: `"Neither, sir. It was William the coachman."` -- "The text names William the coachman here." The victim named as the doer (the graph node "William the coachman" is not matched by the question's "William Kirwan", so `drop_named` did not remove it).
- pr-thor-1, thor-2, naval-1 and the cut naval rows, reigate-2: refused. The thor-bridge suicide was never answered (no NOT_A_PERSON answer in the whole study).

## Failures and limits

- The model chooses by lexical overlap with the question and by first name in the sentence, not by who did the act (Simpson from "eliminated", Silas Brown from "no friend to Straker", Neligan from "young Neligan ... Patrick Cairns, the true murderer"). Verification checks presence of the name, not its role, so these pass. The V3 act gate removed some (pr-silver-1: no act told next to the name; pr-norwood-1: suspicion words in the window) but not these.
- The act gate refuses on any suspicion/arrest word in the 3-sentence window, so correct answers next to such words are lost too (conservative, untuned).
- Evidence is missing from the 20 sentences in most dev questions (above); the mode cannot name a culprit that no listed sentence names next to an act.
- Graph noise reaches the candidates: "Silver Blaze" (the horse) and "Basil" are person nodes; "William the coachman" is a separate node from the victim; ambiguous bare surnames are dropped, which also drops "young McCarthy".
- NOT_A_PERSON was never selected and verified; its cue list (horse, snake, suicide ...) is generic and untested end to end on real data.
- n is tiny: dev 9 rows (6 in scope, one golden), held-out 8 per condition, two questions per story are not independent, cases and aliases are AI-written, scoring is lexical. All intervals are wide; no difference between off and on is significant (for V3 every exact McNemar p is at least 0.25; V2's five extra refusals on dev: p 0.0625).
- The OFF baseline of the held-out comparison is the 2026-10-28 run (earlier commit, graph and index files may have been rebuilt since); its dev counterpart reproduced.
- Dev rows were used to design V2 and V3 (peek runs on dev questions only); dev numbers are therefore optimistic design-set numbers.
- No "same fix failed twice" stop: each variant addressed the previous variant's observed failure with a different change; the three-variant budget is spent.

## Recommendation

1. Keep `entity_answer` off. Do not enable it for the Friday demo and do not mention it as a result; if shown at all, show this page as an honest boundary.
2. The deterministic check must test the ROLE, not only the presence: for example require the chosen name to be the grammatical subject next to the act verb, or reject a sentence that names two candidate people. That is a new design, not a tuning of this one, and would be measured on dev first.
3. The bigger lever is upstream: the candidate sentences do not contain the evidence for 3 of 5 dev questions. Step 2 of the revised plan (a vote per chunk before the cut, not 20 sentences of the whole story) addresses that and should come before further work on the chooser.
4. Value kept: as a refusal filter the mode is safer than the current one-quote answer on the unreliable questions (dev: 3 more refusals, held-out full: 1 more), but only if wrong-person naming is removed first.
