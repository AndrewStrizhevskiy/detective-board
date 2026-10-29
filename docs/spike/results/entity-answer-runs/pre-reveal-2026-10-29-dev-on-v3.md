# Pre-reveal test, 2026-10-29

The cases are AI-written: the reveal passages were located by reading the text, the cut placed before them and checked by scripts/eval/validate_pre_reveal.py. Every outcome is lexical (names or keywords in the answer and its cited quotes), not a human reading.

- run at commit `98067d8` (dirty tree), generator `qwen3:4b-instruct`, seed 42, temperature 0.0, machine mendax-ThinkPad-X1-Carbon-7th / x86_64 / Linux 7.0.0-42-generic
- cases: eval/pre_reveal/cases.jsonl (sha256 e1ee1364ac22 at run time), 5 questions in 3 stories; AgentConfig = the app defaults (full dict in the JSON)
- graph present: True, sentence index: True, rule tools: timeline-alibi

## Metrics

**Primary: culprit named.** An accepted name or alias of the culprit or cause (case field `culprit_names`, e.g. Turner / Black Jack, the horse, snake / adder, Cairns, suicide / killed herself) occurs in the answer text or its cited quotes, case-insensitive, at a word start. It is primary because the question asks WHO or WHAT, and a correct answer can use any wording. Its weakness: several aliases also occur long before the cut (Turner, the horse, Joseph and Harrison, Oldacre, Cunningham are characters from the start), so in condition B a 'named' can be a mere mention; the exposure table below counts the pre-cut chunks that hold an alias, and every B 'named' is read by hand in the notes.

**Secondary: keyword metric.** Reveal-text keyword sets (`truth_keywords`, `truth_keywords_alt`, e.g. 'lessen his guilt', 'her own life', 'murdering their coachman'); the validator guarantees that no sentence and no chunk before the cut holds a set, so it is leak-free in B, but it is wording-bound: the full-corpus control fails it when the agent quotes a different correct sentence. That is why it is not the primary metric.

**Innocent accused.** Answered, a cleared person's name (`cleared_names`: James McCarthy, Fitzroy Simpson, McFarlane, Neligan, Grace Dunbar; 5 of 8 stories) in the answer or its quotes, and no culprit alias. A lexical proxy: a mention is not an accusation, read the rows.

**Bare model (C).** Names in the questions were not masked (story titles, victims), and the 4B model may know the stories by heart; C measures memory and guessing, not reasoning. Its refusals are detected with the phrase list of eval/run_answer_check.py.

## Result (n = questions; Wilson 95 % interval)

| condition | n scored | **culprit named** (primary) | refused | answered, culprit not named | innocent accused | keyword metric (secondary) | median latency |
|---|---|---|---|---|---|---|---|
| A. full corpus (control) | 5/5 | 0/5 = 0 % [0, 43] | 4/5 = 80 % [38, 96] | 1/5 = 20 % [4, 62] | 0/5 = 0 % [0, 43] | 0/5 = 0 % [0, 43] | 24.9 s |

Per story, culprit named (questions named / asked):

| story | A. full corpus (control) |
|---|---|
| boscombe-valley-mystery | 0/2 |
| norwood-builder | 0/1 |
| silver-blaze | 0/2 |

Leak exposure of the primary metric: chunks that end before the cut and hold a culprit alias (a 'named' in condition B can be a mere mention of the name):

| story | alias set: pre-cut chunks |
|---|---|
| boscombe-valley-mystery | Turner: 11, John Turner: 1, Black Jack: 0 |
| silver-blaze | the horse: 11, Silver Blaze kicked: 0, Straker himself: 0 |
| norwood-builder | Oldacre+alive: 1, Oldacre+hiding: 0 |

## Per question

| id | cond | culprit named | keywords | innocent | matched | answer (clipped) |
|---|---|---|---|---|---|---|
| pr-boscombe-1 | full | refused | refused |  |  | In these materials there is nothing about this. |
| pr-boscombe-2 | full | refused | refused |  |  | In these materials there is nothing about this. |
| pr-silver-1 | full | refused | refused |  |  | In these materials there is nothing about this. |
| pr-silver-2 | full | wrong | wrong |  |  | From the sources: [4: "Silas Brown, the trainer, is known to have had large bets upon the event, and he was no friend to poor Straker."] The text names Silas Brown here. |
| pr-norwood-1 | full | refused | refused |  |  | In these materials there is nothing about this. |

## Cases

- **boscombe-valley-mystery** (cut at 36458): Cut before Holmes shows Lestrade the stone ('The murder was done with it') and describes the murderer (tall, left-handed, lame, grey cloak); everything before is the inquest narrative, the Turner family introduction and the site visit. The Cooee/Ballarat deduction, the confession and the name follow. Truth: John Turner of the Hall (once 'Black Jack of Ballarat') killed Charles McCarthy; James McCarthy is innocent.
- **silver-blaze** (cut at 40470): Cut before the Wessex Cup scene in which Holmes says the real murderer is the horse; Holmes's earlier hints (the dog in the night-time, the lame sheep) are clues, not statements of the solution. Truth: The horse Silver Blaze killed John Straker, in self-defence, when Straker tried to nick its tendon; Fitzroy Simpson is not the culprit.
- **norwood-builder** (cut at 37573): Cut before Holmes says the thumb-mark was not there the day before; the hidden room, Oldacre's appearance and the explanation of the plot follow. Truth: Jonas Oldacre is alive and was hiding in a concealed room of his own house; he framed John Hector McFarlane.

## Limits

- n = 16 questions in 8 stories; the two questions of a story are not independent, so the intervals are optimistic. Cases and aliases are AI-written, not reviewed by a human.
- The cut is placed by reading; the validator checks verbatim quotes, the cut before every quote and keyword leaks, but cannot check paraphrased hints or a culprit named by a description.
- CutRetriever re-fuses the arms over the kept hits; BM25 scores still use the statistics of the full index (ranks hardly change). The chunk that straddles the cut is dropped, so up to one chunk of legitimate pre-cut text is lost per story.
- The graph and the rule tools are not cut; no question here routed to them (no graph_query or tool_call event), otherwise the row would be 'unscored'.
- One run, temperature 0, seed 42; the laptop CPU was shared with other jobs (serialised by flock), so latencies are indicative.
