# Pre-reveal test, 2026-10-28

The cases are generated automatically: the reveal passages were located by reading the text, the cut placed before them and checked by scripts/eval/validate_pre_reveal.py. Every outcome is lexical (names or keywords in the answer and its cited quotes), not a human reading.

- run at commit `0e00f58` (dirty tree), generator `qwen3:4b-instruct`, seed 42, temperature 0.0, machine mendax-ThinkPad-X1-Carbon-7th / x86_64 / Linux 7.0.0-38-generic
- cases: eval/pre_reveal/cases.jsonl (sha256 8807021cb107 at run time), 16 questions in 8 stories; AgentConfig = the app defaults (full dict in the JSON)
- graph present: True, sentence index: True, rule tools: timeline-alibi
- RESCORED 2026-10-28T19:48:49+00:00 from `pre-reveal-2026-10-28.json` (the saved answers, no model rerun) at commit `9593abd`, cases sha256 e1ee1364ac22; supersedes the scoring of the first report

## Metrics

**Primary: culprit named.** An accepted name or alias of the culprit or cause (case field `culprit_names`, e.g. Turner / Black Jack, the horse, snake / adder, Cairns, suicide / killed herself) occurs in the answer text or its cited quotes, case-insensitive, at a word start. It is primary because the question asks WHO or WHAT, and a correct answer can use any wording. Its weakness: several aliases also occur long before the cut (Turner, the horse, Joseph and Harrison, Oldacre, Cunningham are characters from the start), so in condition B a 'named' can be a mere mention; the exposure table below counts the pre-cut chunks that hold an alias, and every B 'named' is read by hand in the notes.

**Secondary: keyword metric.** Reveal-text keyword sets (`truth_keywords`, `truth_keywords_alt`, e.g. 'lessen his guilt', 'her own life', 'murdering their coachman'); the validator guarantees that no sentence and no chunk before the cut holds a set, so it is leak-free in B, but it is wording-bound: the full-corpus control fails it when the agent quotes a different correct sentence. That is why it is not the primary metric.

**Innocent accused.** Answered, a cleared person's name (`cleared_names`: James McCarthy, Fitzroy Simpson, McFarlane, Neligan, Grace Dunbar; 5 of 8 stories) in the answer or its quotes, and no culprit alias. A lexical proxy: a mention is not an accusation, read the rows.

**Bare model (C).** Names in the questions were not masked (story titles, victims), and the 4B model may know the stories by heart; C measures memory and guessing, not reasoning. Its refusals are detected with the phrase list of eval/run_answer_check.py.

## Result (n = questions; Wilson 95 % interval)

| condition | n scored | **culprit named** (primary) | refused | answered, culprit not named | innocent accused | keyword metric (secondary) | median latency |
|---|---|---|---|---|---|---|---|
| A. full corpus (control) | 16/16 | 2/16 = 12 % [4, 36] | 5/16 = 31 % [14, 56] | 9/16 = 56 % [33, 77] | 1/16 = 6 % [1, 28] | 1/16 = 6 % [1, 28] | 40.4 s |
| B. corpus cut before the reveal | 16/16 | 0/16 = 0 % [0, 19] | 5/16 = 31 % [14, 56] | 11/16 = 69 % [44, 86] | 1/16 = 6 % [1, 28] | 0/16 = 0 % [0, 19] | 31.8 s |
| C. bare model, no retrieval | 16/16 | 1/16 = 6 % [1, 28] | 13/16 = 81 % [57, 93] | 2/16 = 12 % [4, 36] | 0/16 = 0 % [0, 19] | 1/16 = 6 % [1, 28] | 30.4 s |

Paired, culprit named, full vs cut: only full 2, only cut 0, exact McNemar p 0.5 (n 16).

Paired, culprit named, full vs bare: only full 2, only bare 1, exact McNemar p 1 (n 16).

Paired, culprit named, cut vs bare: only cut 0, only bare 1, exact McNemar p 1 (n 16).

Per story, culprit named (questions named / asked):

| story | A. full corpus (control) | B. corpus cut before the reveal | C. bare model, no retrieval |
|---|---|---|---|
| black-peter | 0/2 | 0/2 | 0/2 |
| boscombe-valley-mystery | 0/2 | 0/2 | 0/2 |
| naval-treaty | 1/2 | 0/2 | 0/2 |
| norwood-builder | 0/2 | 0/2 | 0/2 |
| reigate-squires | 1/2 | 0/2 | 0/2 |
| silver-blaze | 0/2 | 0/2 | 0/2 |
| speckled-band | 0/2 | 0/2 | 1/2 |
| thor-bridge | 0/2 | 0/2 | 0/2 |

Leak exposure of the primary metric: chunks that end before the cut and hold a culprit alias (a 'named' in condition B can be a mere mention of the name):

| story | alias set: pre-cut chunks |
|---|---|
| boscombe-valley-mystery | Turner: 11, John Turner: 1, Black Jack: 0 |
| silver-blaze | the horse: 11, Silver Blaze kicked: 0, Straker himself: 0 |
| speckled-band | snake: 0, swamp adder: 0, adder: 0 |
| norwood-builder | Oldacre+alive: 1, Oldacre+hiding: 0 |
| naval-treaty | Joseph: 8, Joseph Harrison: 3, Harrison: 11 |
| black-peter | Cairns: 0, Patrick Cairns: 0 |
| thor-bridge | suicide: 0, killed herself: 0, her own hand: 1, Maria Gibson herself: 0 |
| reigate-squires | Cunningham: 9, Alec Cunningham: 3, the Cunninghams: 0 |

## Per question

| id | cond | culprit named | keywords | innocent | matched | answer (clipped) |
|---|---|---|---|---|---|---|
| pr-boscombe-1 | full | refused | refused |  |  | In these materials there is nothing about this. |
| pr-boscombe-1 | cut | refused | refused |  |  | In these materials there is nothing about this. |
| pr-boscombe-1 | bare | refused | refused |  |  | Charles McCarthy was not killed at Boscombe Pool. In fact, there is no historical or factual record of a person named Charles McCarthy being killed at Boscombe Pool. Boscombe Pool is a well-known location in the UK, specifically … |
| pr-boscombe-2 | full | wrong | wrong |  |  | From the sources: [3: "Is he the man who hobnobbed in rum and water with Black Peter in the dead of the night?"] [5: "Was not that person the actual criminal?"] |
| pr-boscombe-2 | cut | wrong | wrong |  |  | From the sources: [3: "Is he the man who hobnobbed in rum and water with Black Peter in the dead of the night?"] [6: "Was not that person the actual criminal?"] |
| pr-boscombe-2 | bare | wrong | wrong |  |  | In *The Boscombe Valley Mystery*, a famous detective story by Sir Arthur Conan Doyle, the guilty man is **Dr. Grimesby Roylott**. However, it's important to clarify: *The Boscombe Valley Mystery* is actually a **short story** by … |
| pr-silver-1 | full | wrong | wrong |  |  | From the sources: [1: "“And of course this is all quite a minor point compared to the question of who killed John Straker.”"] [3: "You would do me a greater still if you could lay your hands on the murderer of John Straker.”"] |
| pr-silver-1 | cut | wrong | wrong |  |  | From the sources: [1: "“And of course this is all quite a minor point compared to the question of who killed John Straker.”"] [4: "“Who killed Colonel James Barclay, then?”"] |
| pr-silver-1 | bare | refused | refused |  |  | John Straker is a character from the British television series *Agatha Christie's Poirot*. In the episode titled "The Murder of John Straker," which is part of the *Poirot* series, John Straker is indeed a character, and he is mu… |
| pr-silver-2 | full | wrong | wrong |  |  | From the sources: [4: "Silas Brown, the trainer, is known to have had large bets upon the event, and he was no friend to poor Straker."] [10: "It was clear, however, that Straker had defended himself vigorously against his assail… |
| pr-silver-2 | cut | wrong | wrong |  |  | From the sources: [5: "Silas Brown, the trainer, is known to have had large bets upon the event, and he was no friend to poor Straker."] [8: "“John Clay, the murderer, thief, smasher, and forger."] |
| pr-silver-2 | bare | refused | refused |  |  | There is no known public figure or widely recognized case involving a person named John Straker who was a trainer and murdered. As of now, there is no credible evidence or record in official databases, news reports, or historical… |
| pr-speckled-1 | full | refused | refused |  |  | In these materials there is nothing about this. |
| pr-speckled-1 | cut | refused | refused |  |  | In these materials there is nothing about this. |
| pr-speckled-1 | bare | refused | refused |  |  | Julia Stoner did not die in a real-world, documented event. Julia Stoner is a fictional character from the novel *The Girl with the Dragon Tattoo* by Stieg Larsson. In the story, Julia Stoner is a character who is portrayed as a … |
| pr-speckled-2 | full | wrong | wrong |  |  | From the sources: [2: "Round his brow he had a peculiar yellow band, with brownish speckles, which seemed to be bound tightly round his head."] [4: "It was very long, though—almost as long, Watson, as when you and I waited in tha… |
| pr-speckled-2 | cut | wrong | wrong |  |  | From the sources: [4: "A double band of white shells were strung round the centre of it."] |
| pr-speckled-2 | bare | named | named |  | snake | The **Speckled Band** is a famous fictional story by **Sir Arthur Conan Doyle**, one of the most renowned authors in the world of detective fiction. It is a short story that was first published in 1892 as part of a collection tit… |
| pr-norwood-1 | full | wrong | wrong |  |  | From the sources: [12: "Was not that person the actual criminal?"] [13: "You can hardly find a flaw in the case which can now be presented against him, and all further investigation has served to strengthen it."] |
| pr-norwood-1 | cut | wrong | wrong |  |  | From the sources: [10: "“Do you think that this man Horner is innocent?”"] [12: "Was not that person the actual criminal?"] |
| pr-norwood-1 | bare | refused | refused |  |  | There is no widely known or officially documented case called the "Norwood Builder case" in historical or legal records. It's possible that you may be referring to a fictional scenario, a misremembered name, or a case that is not… |
| pr-norwood-2 | full | wrong | wrong | yes |  (cleared: McFarlane) | From the sources: [4: "It is known that Mr. Jonas Oldacre had received a late visitor in his bedroom upon that night, and the stick found has been identified as the property of this person, who is a young London solicitor named J… |
| pr-norwood-2 | cut | wrong | wrong | yes |  (cleared: McFarlane) | From the sources: [3: "Mr. Jonas Oldacre is a well-known resident of that suburb, where he has carried on his business as a builder for many years."] [3: "It is known that Mr. Jonas Oldacre had received a late visitor in his bedr… |
| pr-norwood-2 | bare | refused | refused |  |  | As of now, there is no publicly known figure named Jonas Oldacre in reliable historical, biographical, or governmental records. The name does not appear in any verified databases, news sources, or official records related to publ… |
| pr-naval-1 | full | refused | refused |  |  | In these materials there is nothing about this. |
| pr-naval-1 | cut | wrong | wrong |  |  | From the sources: [3: "Presuming that your theory is correct, if he can lay his hands upon the man who threatened you last night he will have gone a long way towards finding who took the naval treaty."] [3: "Phelps was still weak… |
| pr-naval-1 | bare | refused | refused |  |  | There is no historical or credible record of a "naval treaty" being stolen from Percy Phelps, and no known figure named Percy Phelps is associated with such an event in historical or diplomatic records. Percy Phelps was a real pe… |
| pr-naval-2 | full | named | named |  | Joseph | From the sources: [4: "Joseph a villain and a thief!”"] [5: "“‘Stolen!’ he cried. “‘Yes, thief!’"] |
| pr-naval-2 | cut | wrong | wrong |  |  | From the sources: [2: "Why should a thief try to break in at a bedroom window, where there could be no hope of any plunder, and why should he come with a long knife in his hand?”"] [8: "‘A document of immense value has been stole… |
| pr-naval-2 | bare | refused | refused |  |  | There is no known case called the "Naval Treaty case" involving a thief, and no widely recognized historical or legal case by that name exists in international law, maritime history, or criminal justice records. It's possible tha… |
| pr-black-1 | full | wrong | wrong |  |  | From the sources: [2: "That very night he went down to Woodman’s Lee, saw Peter Carey at the hut, quarrelled with him, and killed him with the harpoon."] [3: "You say I murdered Peter Carey, I say I _killed_ Peter Carey, and ther… |
| pr-black-1 | cut | wrong | wrong |  |  | From the sources: [8: "Did his companions follow him and kill him?"] [10: "The fact that the crime was committed at two in the morning, and yet Peter Carey was fully dressed, suggested that he had an appointment with the murderer… |
| pr-black-1 | bare | wrong | wrong |  |  | Peter Carey did not die. Peter Carey is a living Australian author, known for his novels such as *True History of the Kelly Gang*, *Oscar and Lucinda*, and *The Water Diviner*. As of now, he is alive and active in the literary wo… |
| pr-black-2 | full | wrong | wrong |  |  | From the sources: [2: "I knew Black Peter, and when he pulled out his knife I whipped a harpoon through him sharp, for I knew that it was him or me."] [5: "That very night he went down to Woodman’s Lee, saw Peter Carey at the hut… |
| pr-black-2 | cut | refused | refused |  |  | In these materials there is nothing about this. |
| pr-black-2 | bare | refused | refused |  |  | There is no known figure named Peter Carey who is the victim of a murder, and no widely recognized case or public record identifies a "true murderer" of someone named Peter Carey. Peter Carey is, in fact, a well-known Australian … |
| pr-thor-1 | full | refused | refused |  |  | In these materials there is nothing about this. |
| pr-thor-1 | cut | refused | refused |  |  | In these materials there is nothing about this. |
| pr-thor-1 | bare | refused | refused |  |  | Maria Gibson was not a real person, and there is no verified historical or public record of someone by that name being killed. It's possible there is a mix-up with the name or a confusion with another individual. If you meant a d… |
| pr-thor-2 | full | refused | refused |  |  | In these materials there is nothing about this. |
| pr-thor-2 | cut | refused | refused |  |  | In these materials there is nothing about this. |
| pr-thor-2 | bare | refused | refused |  |  | Maria Gibson is not a widely recognized public figure, and there is no credible or verified information indicating that someone named Maria Gibson died under specific circumstances that are publicly documented or widely reported.… |
| pr-reigate-1 | full | named | wrong |  | Cunningham | From the sources: [3: "Whoever wrote that note was the man who brought William Kirwan out of his bed at that hour."] [4: "“Before going into this, I would draw your attention to the fact that, if Alec Cunningham’s narrative was c… |
| pr-reigate-1 | cut | wrong | wrong |  |  | From the sources: [2: "Whoever wrote that note was the man who brought William Kirwan out of his bed at that hour."] [10: "“Who shot him, then?”"] |
| pr-reigate-1 | bare | refused | refused |  |  | William Kirwan was not murdered. William Kirwan was a prominent American academic and administrator, best known for serving as the president of the University of Maryland, College Park, from 1970 to 1980. There is no credible evi… |
| pr-reigate-2 | full | wrong | wrong |  |  | From the sources: [5: "McFarlane’s guilt definitely established."] [9: "He made a complete voluntary confession."] |
| pr-reigate-2 | cut | wrong | wrong |  |  | From the sources: [5: "McFarlane’s guilt definitely established."] [9: "He made a complete voluntary confession."] |
| pr-reigate-2 | bare | refused | refused |  |  | The Reigate Squires case is a real historical event, but it is important to clarify that there is no widely known or officially documented case involving "Reigate Squires" that has a definitive "guilty man" identified in a crimin… |

## Cases

- **boscombe-valley-mystery** (cut at 36458): Cut before Holmes shows Lestrade the stone ('The murder was done with it') and describes the murderer (tall, left-handed, lame, grey cloak); everything before is the inquest narrative, the Turner family introduction and the site visit. The Cooee/Ballarat deduction, the confession and the name follow. Truth: John Turner of the Hall (once 'Black Jack of Ballarat') killed Charles McCarthy; James McCarthy is innocent.
- **silver-blaze** (cut at 40470): Cut before the Wessex Cup scene in which Holmes says the real murderer is the horse; Holmes's earlier hints (the dog in the night-time, the lame sheep) are clues, not statements of the solution. Truth: The horse Silver Blaze killed John Straker, in self-defence, when Straker tried to nick its tendon; Fitzroy Simpson is not the culprit.
- **speckled-band** (cut at 39716): Cut before Holmes's night-time explanation at the inn (the ventilator, the bell-rope, the clamped bed); the snake is first named at the dénouement, after the cut. Truth: A swamp adder, a snake trained by Dr. Grimesby Roylott and sent through the ventilator, killed Julia Stoner; the 'speckled band' is the snake.
- **norwood-builder** (cut at 37573): Cut before Holmes says the thumb-mark was not there the day before; the hidden room, Oldacre's appearance and the explanation of the plot follow. Truth: Jonas Oldacre is alive and was hiding in a concealed room of his own house; he framed John Hector McFarlane.
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

## Reading of the answers (hand-written; `--rescore` regenerates the sections above, not this one)

The run header says "dirty tree": the scoring code was edited on disk after the run process had
loaded it; the code that ran is `0e00f58`, and the scoring that differs is what this rescore replaces.

**Headline.** B (cut before the reveal) names the culprit in 0 of 16 questions [0, 19], on both the
primary and the keyword metric. No B row is a 'named', so there is no mention-leak to discount,
although Turner, the horse, Joseph/Harrison and Cunningham sit in 9-11 pre-cut chunks each. In the
real run no B question retrieved or cited a chunk past the cut (checked on the saved rows). BUT the
control is weak: A (full corpus) names the culprit in only 2 of 16 [4, 36]; A vs B 2 vs 0, exact
McNemar p 0.5. The test therefore does not show that the reveal is what the agent needs; it shows that
the extractive agent mostly fails these "who did it" questions even when the reveal is in the index.
B near zero is the expected floor, and A is barely above it. At n = 16 the conditions are not
separable.

**The two A hits, read by hand.** naval-2: "Joseph a villain and a thief!" from the reveal chunk,
a genuine answer. reigate-1: a sentence of Holmes's explanation that names Alec Cunningham as the
one who must have torn the paper from the dead man's hand. That points at the culprit but does not
say he shot Kirwan, so it is a partial hit counted as 'named'.

**Near misses in A.** In 10 of 16 A rows the top-6 chunks held at least one chunk from past the cut,
yet the selection rarely took the naming sentence:
- black-peter 1/2 quote the harpooner's confession ("You say I murdered Peter Carey, I say I
  _killed_ Peter Carey"; "I whipped a harpoon through him") without the speaker's name, next to
  Hopkins's wrong Neligan theory.
- speckled-2 quotes "Round his brow he had a peculiar yellow band, with brownish speckles", one
  sentence before the serpent.
- silver-blaze 1/2 had the reveal chunks but chose sentences that echo the question ("the question
  of who killed John Straker", "the murderer of John Straker"), or the Silas Brown suspicion.
- naval-1 refused although the reveal chunks 0037/0038 were retrieved.

**Per story.**
- boscombe-valley-mystery: A = B. Q1 is refused; Q2 quotes off-story sentences from Black Peter
  and Thor Bridge. Bare Q1 says no such killing exists; bare Q2 names Dr. Grimesby Roylott (the
  Speckled Band villain).
- silver-blaze: in A the reveal chunks were retrieved and not chosen. In B the answer is the same
  echo plus a Crooked Man question sentence or the Silas Brown sentence. Bare places John Straker
  in a Poirot episode and refuses.
- speckled-band: Q1 is refused in A and B. On Q2, A has the near miss above, and B quotes a Wisteria
  Lodge "double band of white shells". Bare Q2 gives the only bare hit ("a speckled snake"), wrapped
  in confabulation (Roylott as a "stepson", a hidden room, a captive girl): memory of the famous
  twist, not of the story.
- norwood-builder: Q1 in A and B quotes generic lines ("Was not that person the actual
  criminal?", from Thor Bridge). On Q2 both conditions quote the newspaper report of McFarlane's
  arrest for the murder, which the innocent-accused metric flags: the agent repeats the accusation
  the text makes before the reveal. The hiding-place chunk 0027 was retrieved in A but not chosen.
- naval-treaty: A Q2 is genuinely right and A Q1 is refused. B answers with pre-cut suspicion
  sentences and no name.
- black-peter: A has the near misses above. B Q1 quotes the pre-cut "appointment with the
  murderer" reasoning plus a Wisteria line, and B Q2 is refused. Bare: "Peter Carey is a living
  Australian author".
- thor-bridge: all four agent rows are refused; the solution ("end her own life") never reached
  an answer. Bare refuses.
- reigate-squires: A Q1 is the partial hit. B Q1 quotes the pre-cut "Whoever wrote that note was
  the man who brought William Kirwan out of his bed": right reasoning, no name. Q2 in A and B
  retrieved no Reigate chunk and quotes "McFarlane's guilt definitely established." from Norwood,
  calling an innocent man of ANOTHER story guilty (not counted: `cleared_names` is per story).
  Bare: "William Kirwan was a prominent American academic".

**Bare model.** 13 of 16 refused. Without context the 4B model mostly takes the names for real
people (the novelist Peter Carey, the academic William Kirwan) or mixes up stories. Only the
Speckled Band twist came back from memory. The names in the questions were not masked, so a larger
model could answer from memory. For this model, memorisation does not explain the agent's numbers.

**What this means.** The before-the-reveal number (0/16) is honest, but the interpretation is
limited by the control: the extractive selection, not the cut, is the bottleneck on "who did it"
questions. That is consistent with the STATUS note that the agent picks the answer sentence worse
than vector-only. To make the test discriminating, the control has to pass first; that work belongs
to the selection step, not to this test.
