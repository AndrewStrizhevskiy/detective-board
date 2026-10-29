# Pre-reveal test, 2026-10-29

The cases are AI-written: the reveal passages were located by reading the text, the cut placed before them and checked by scripts/eval/validate_pre_reveal.py. Every outcome is lexical (names or keywords in the answer and its cited quotes), not a human reading.

- run at commit `98067d8` (dirty tree), generator `qwen3:4b-instruct`, seed 42, temperature 0.0, machine mendax-ThinkPad-X1-Carbon-7th / x86_64 / Linux 7.0.0-42-generic
- cases: eval/pre_reveal/cases.jsonl (sha256 e1ee1364ac22 at run time), 3 questions in 2 stories; AgentConfig = the app defaults (full dict in the JSON)
- graph present: True, sentence index: True, rule tools: timeline-alibi

## Metrics

**Primary: culprit named.** An accepted name or alias of the culprit or cause (case field `culprit_names`, e.g. Turner / Black Jack, the horse, snake / adder, Cairns, suicide / killed herself) occurs in the answer text or its cited quotes, case-insensitive, at a word start. It is primary because the question asks WHO or WHAT, and a correct answer can use any wording. Its weakness: several aliases also occur long before the cut (Turner, the horse, Joseph and Harrison, Oldacre, Cunningham are characters from the start), so in condition B a 'named' can be a mere mention; the exposure table below counts the pre-cut chunks that hold an alias, and every B 'named' is read by hand in the notes.

**Secondary: keyword metric.** Reveal-text keyword sets (`truth_keywords`, `truth_keywords_alt`, e.g. 'lessen his guilt', 'her own life', 'murdering their coachman'); the validator guarantees that no sentence and no chunk before the cut holds a set, so it is leak-free in B, but it is wording-bound: the full-corpus control fails it when the agent quotes a different correct sentence. That is why it is not the primary metric.

**Innocent accused.** Answered, a cleared person's name (`cleared_names`: James McCarthy, Fitzroy Simpson, McFarlane, Neligan, Grace Dunbar; 5 of 8 stories) in the answer or its quotes, and no culprit alias. A lexical proxy: a mention is not an accusation, read the rows.

**Bare model (C).** Names in the questions were not masked (story titles, victims), and the 4B model may know the stories by heart; C measures memory and guessing, not reasoning. Its refusals are detected with the phrase list of eval/run_answer_check.py.

## Result (n = questions; Wilson 95 % interval)

| condition | n scored | **culprit named** (primary) | refused | answered, culprit not named | innocent accused | keyword metric (secondary) | median latency |
|---|---|---|---|---|---|---|---|
| A. full corpus (control) | 3/3 | 0/3 = 0 % [0, 56] | 1/3 = 33 % [6, 79] | 2/3 = 67 % [21, 94] | 1/3 = 33 % [6, 79] | 0/3 = 0 % [0, 56] | 3.1 s |

Per story, culprit named (questions named / asked):

| story | A. full corpus (control) |
|---|---|
| norwood-builder | 0/1 |
| speckled-band | 0/2 |

Leak exposure of the primary metric: chunks that end before the cut and hold a culprit alias (a 'named' in condition B can be a mere mention of the name):

| story | alias set: pre-cut chunks |
|---|---|
| speckled-band | snake: 0, swamp adder: 0, adder: 0 |
| norwood-builder | Oldacre+alive: 1, Oldacre+hiding: 0 |

## Per question

| id | cond | culprit named | keywords | innocent | matched | answer (clipped) |
|---|---|---|---|---|---|---|
| pr-speckled-1 | full | refused | refused |  |  | In these materials there is nothing about this. |
| pr-speckled-2 | full | wrong | wrong |  |  | From the sources: [2: "Round his brow he had a peculiar yellow band, with brownish speckles, which seemed to be bound tightly round his head."] [4: "It was very long, though—almost as long, Watson, as when you and I waited in tha… |
| pr-norwood-2 | full | wrong | wrong | yes |  (cleared: McFarlane) | From the sources: [4: "It is known that Mr. Jonas Oldacre had received a late visitor in his bedroom upon that night, and the stick found has been identified as the property of this person, who is a young London solicitor named J… |

## Cases

- **speckled-band** (cut at 39716): Cut before Holmes's night-time explanation at the inn (the ventilator, the bell-rope, the clamped bed); the snake is first named at the dénouement, after the cut. Truth: A swamp adder, a snake trained by Dr. Grimesby Roylott and sent through the ventilator, killed Julia Stoner; the 'speckled band' is the snake.
- **norwood-builder** (cut at 37573): Cut before Holmes says the thumb-mark was not there the day before; the hidden room, Oldacre's appearance and the explanation of the plot follow. Truth: Jonas Oldacre is alive and was hiding in a concealed room of his own house; he framed John Hector McFarlane.

## Limits

- n = 16 questions in 8 stories; the two questions of a story are not independent, so the intervals are optimistic. Cases and aliases are AI-written, not reviewed by a human.
- The cut is placed by reading; the validator checks verbatim quotes, the cut before every quote and keyword leaks, but cannot check paraphrased hints or a culprit named by a description.
- CutRetriever re-fuses the arms over the kept hits; BM25 scores still use the statistics of the full index (ranks hardly change). The chunk that straddles the cut is dropped, so up to one chunk of legitimate pre-cut text is lost per story.
- The graph and the rule tools are not cut; no question here routed to them (no graph_query or tool_call event), otherwise the row would be 'unscored'.
- One run, temperature 0, seed 42; the laptop CPU was shared with other jobs (serialised by flock), so latencies are indicative.
