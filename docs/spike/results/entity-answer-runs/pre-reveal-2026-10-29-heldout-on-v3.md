# Pre-reveal test, 2026-10-29

The cases are generated automatically: the reveal passages were located by reading the text, the cut placed before them and checked by scripts/eval/validate_pre_reveal.py. Every outcome is lexical (names or keywords in the answer and its cited quotes), not a human reading.

- run at commit `4150c4f`, generator `qwen3:4b-instruct`, seed 42, temperature 0.0, machine mendax-ThinkPad-X1-Carbon-7th / x86_64 / Linux 7.0.0-42-generic
- cases: eval/pre_reveal/cases.jsonl (sha256 e1ee1364ac22 at run time), 8 questions in 4 stories; AgentConfig = the app defaults (full dict in the JSON)
- graph present: True, sentence index: True, rule tools: timeline-alibi

## Metrics

**Primary: culprit named.** An accepted name or alias of the culprit or cause (case field `culprit_names`, e.g. Turner / Black Jack, the horse, snake / adder, Cairns, suicide / killed herself) occurs in the answer text or its cited quotes, case-insensitive, at a word start. It is primary because the question asks WHO or WHAT, and a correct answer can use any wording. Its weakness: several aliases also occur long before the cut (Turner, the horse, Joseph and Harrison, Oldacre, Cunningham are characters from the start), so in condition B a 'named' can be a mere mention; the exposure table below counts the pre-cut chunks that hold an alias, and every B 'named' is read by hand in the notes.

**Secondary: keyword metric.** Reveal-text keyword sets (`truth_keywords`, `truth_keywords_alt`, e.g. 'lessen his guilt', 'her own life', 'murdering their coachman'); the validator guarantees that no sentence and no chunk before the cut holds a set, so it is leak-free in B, but it is wording-bound: the full-corpus control fails it when the agent quotes a different correct sentence. That is why it is not the primary metric.

**Innocent accused.** Answered, a cleared person's name (`cleared_names`: James McCarthy, Fitzroy Simpson, McFarlane, Neligan, Grace Dunbar; 5 of 8 stories) in the answer or its quotes, and no culprit alias. A lexical proxy: a mention is not an accusation, read the rows.

**Bare model (C).** Names in the questions were not masked (story titles, victims), and the 4B model may know the stories by heart; C measures memory and guessing, not reasoning. Its refusals are detected with the phrase list of eval/run_answer_check.py.

## Result (n = questions; Wilson 95 % interval)

| condition | n scored | **culprit named** (primary) | refused | answered, culprit not named | innocent accused | keyword metric (secondary) | median latency |
|---|---|---|---|---|---|---|---|
| A. full corpus (control) | 8/8 | 3/8 = 38 % [14, 69] | 4/8 = 50 % [22, 78] | 1/8 = 12 % [2, 47] | 0/8 = 0 % [0, 32] | 3/8 = 38 % [14, 69] | 14.1 s |
| B. corpus cut before the reveal | 8/8 | 0/8 = 0 % [0, 32] | 5/8 = 62 % [31, 86] | 3/8 = 38 % [14, 69] | 2/8 = 25 % [7, 59] | 0/8 = 0 % [0, 32] | 13.0 s |

Paired, culprit named, full vs cut: only full 3, only cut 0, exact McNemar p 0.25 (n 8).

Per story, culprit named (questions named / asked):

| story | A. full corpus (control) | B. corpus cut before the reveal |
|---|---|---|
| black-peter | 2/2 | 0/2 |
| naval-treaty | 1/2 | 0/2 |
| reigate-squires | 0/2 | 0/2 |
| thor-bridge | 0/2 | 0/2 |

Leak exposure of the primary metric: chunks that end before the cut and hold a culprit alias (a 'named' in condition B can be a mere mention of the name):

| story | alias set: pre-cut chunks |
|---|---|
| naval-treaty | Joseph: 8, Joseph Harrison: 3, Harrison: 11 |
| black-peter | Cairns: 0, Patrick Cairns: 0 |
| thor-bridge | suicide: 0, killed herself: 0, her own hand: 1, Maria Gibson herself: 0 |
| reigate-squires | Cunningham: 9, Alec Cunningham: 3, the Cunninghams: 0 |

## Per question

| id | cond | culprit named | keywords | innocent | matched | answer (clipped) |
|---|---|---|---|---|---|---|
| pr-naval-1 | full | refused | refused |  |  | In these materials there is nothing about this. |
| pr-naval-1 | cut | refused | refused |  |  | In these materials there is nothing about this. |
| pr-naval-2 | full | named | named |  | Joseph | From the sources: [4: "Joseph a villain and a thief!”"] The text names Joseph Harrison here. |
| pr-naval-2 | cut | refused | refused |  |  | In these materials there is nothing about this. |
| pr-black-1 | full | named | named |  | Cairns (cleared: Neligan) | From the sources: [3: "You were so absorbed in young Neligan that you could not spare a thought to Patrick Cairns, the true murderer of Peter Carey.”"] The text names John Hopley Neligan here. |
| pr-black-1 | cut | wrong | wrong | yes |  (cleared: Neligan) | From the sources: [7: "Neligan was my father.”"] [7: "At last we were getting something positive, and yet it seemed a long gap between an absconding banker and Captain Peter Carey pinned against the wall with one of his own harpo… |
| pr-black-2 | full | named | named |  | Cairns (cleared: Neligan) | From the sources: [2: "You were so absorbed in young Neligan that you could not spare a thought to Patrick Cairns, the true murderer of Peter Carey.”"] The text names John Hopley Neligan here. |
| pr-black-2 | cut | wrong | wrong | yes |  (cleared: Neligan) | From the sources: [8: "Neligan was my father.”"] [8: "At last we were getting something positive, and yet it seemed a long gap between an absconding banker and Captain Peter Carey pinned against the wall with one of his own harpo… |
| pr-thor-1 | full | refused | refused |  |  | In these materials there is nothing about this. |
| pr-thor-1 | cut | refused | refused |  |  | In these materials there is nothing about this. |
| pr-thor-2 | full | refused | refused |  |  | In these materials there is nothing about this. |
| pr-thor-2 | cut | refused | refused |  |  | In these materials there is nothing about this. |
| pr-reigate-1 | full | wrong | wrong |  |  | From the sources: [7: "“Neither, sir. It was William the coachman."] The text names William the coachman here. |
| pr-reigate-1 | cut | wrong | wrong |  |  | From the sources: [4: "“Neither, sir. It was William the coachman."] The text names William the coachman here. |
| pr-reigate-2 | full | refused | refused |  |  | In these materials there is nothing about this. |
| pr-reigate-2 | cut | refused | refused |  |  | In these materials there is nothing about this. |

## Cases

- **naval-treaty** (cut at 57675): Cut before the breakfast at which the treaty reappears on Phelps's plate and Holmes tells how he caught Joseph Harrison; the scene before it (Holmes's failed day, the table laid) names no one. Truth: Joseph Harrison, the brother of Phelps's fiancee, stole the treaty and hid it under the bedroom floor.
- **black-peter** (cut at 29725): Cut before Holmes's telegrams to the shipping agent and to Hopkins and the breakfast scene where he demolishes the case against Neligan and the harpooner is arrested. Truth: Patrick Cairns, a harpooner of the Sea Unicorn, killed Peter Carey; young Neligan is innocent.
- **thor-bridge** (cut at 43341): Cut before Holmes leaves the cell at Winchester with the solution; the chip in the stonework is already known, its explanation, the revolver test and the review of the plot are after the cut. Truth: Maria Gibson killed herself and arranged the scene to frame Grace Dunbar, who is innocent.
- **reigate-squires** (cut at 22620): Cut before the house search in which Holmes upsets the carafe and is attacked; the accusation, the paper in the dressing-gown and the full explanation follow. Truth: Alec Cunningham and his father murdered their coachman William Kirwan.

## Limits

- n = 16 questions in 8 stories; the two questions of a story are not independent, so the intervals are optimistic. Cases and aliases are generated automatically, not reviewed by a human.
- The cut is placed by reading; the validator checks verbatim quotes, the cut before every quote and keyword leaks, but cannot check paraphrased hints or a culprit named by a description.
- CutRetriever re-fuses the arms over the kept hits; BM25 scores still use the statistics of the full index (ranks hardly change). The chunk that straddles the cut is dropped, so up to one chunk of legitimate pre-cut text is lost per story.
- The graph and the rule tools are not cut; no question here routed to them (no graph_query or tool_call event), otherwise the row would be 'unscored'.
- One run, temperature 0, seed 42; the laptop CPU was shared with other jobs (serialised by flock), so latencies are indicative.
