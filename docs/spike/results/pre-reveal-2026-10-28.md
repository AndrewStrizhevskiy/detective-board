# Pre-reveal test, 2026-10-28

> SUPERSEDED for scoring by `pre-reveal-2026-10-28-rescored.md` (same answers, culprit-name metric primary). This file keeps the first scoring, whose only metric was the reveal-text keyword sets.

The cases are AI-written (reveal passages located by reading the text, keywords chosen so that no sentence and no chunk before the cut holds them together: scripts/eval/validate_pre_reveal.py). A 'named' needs the keywords in the answer text or its cited quotes, not a human reading.

- commit `0e00f58` (dirty tree), generator `qwen3:4b-instruct`, seed 42, temperature 0.0, machine mendax-ThinkPad-X1-Carbon-7th / x86_64 / Linux 7.0.0-38-generic
- cases: eval/pre_reveal/cases.jsonl (sha256 8807021cb107), 16 questions in 8 stories; AgentConfig = the app defaults (full dict in the JSON)
- graph present: True, sentence index: True, rule tools: timeline-alibi

## Result (n = questions; Wilson 95 % interval)

| condition | n scored | culprit named | refused | answered wrong | median latency |
|---|---|---|---|---|---|
| A. full corpus (control) | 16/16 | 1/16 = 6 % [1, 28] | 5/16 = 31 % [14, 56] | 10/16 = 62 % [39, 82] | 40.4 s |
| B. corpus cut before the reveal | 16/16 | 0/16 = 0 % [0, 19] | 5/16 = 31 % [14, 56] | 11/16 = 69 % [44, 86] | 31.8 s |
| C. bare model, no retrieval | 16/16 | 1/16 = 6 % [1, 28] | 13/16 = 81 % [57, 93] | 2/16 = 12 % [4, 36] | 30.4 s |

Bare model with the looser `free_keywords` (names and plain words): 1/16 = 6 % [1, 28].

## Per question

| id | cond | outcome | routes | answer (clipped) |
|---|---|---|---|---|
| pr-boscombe-1 | full | refused | vector | In these materials there is nothing about this. |
| pr-boscombe-1 | cut | refused | vector | In these materials there is nothing about this. |
| pr-boscombe-1 | bare | refused |  | Charles McCarthy was not killed at Boscombe Pool. In fact, there is no historical or factual record of a person named Charles McCarthy being killed at Boscombe Pool. Boscombe Pool is a well-known location in the UK, specifically … |
| pr-boscombe-2 | full | wrong | vector | From the sources: [3: "Is he the man who hobnobbed in rum and water with Black Peter in the dead of the night?"] [5: "Was not that person the actual criminal?"] |
| pr-boscombe-2 | cut | wrong | vector | From the sources: [3: "Is he the man who hobnobbed in rum and water with Black Peter in the dead of the night?"] [6: "Was not that person the actual criminal?"] |
| pr-boscombe-2 | bare | wrong |  | In *The Boscombe Valley Mystery*, a famous detective story by Sir Arthur Conan Doyle, the guilty man is **Dr. Grimesby Roylott**. However, it's important to clarify: *The Boscombe Valley Mystery* is actually a **short story** by … |
| pr-silver-1 | full | wrong | vector | From the sources: [1: "“And of course this is all quite a minor point compared to the question of who killed John Straker.”"] [3: "You would do me a greater still if you could lay your hands on the murderer of John Straker.”"] |
| pr-silver-1 | cut | wrong | vector | From the sources: [1: "“And of course this is all quite a minor point compared to the question of who killed John Straker.”"] [4: "“Who killed Colonel James Barclay, then?”"] |
| pr-silver-1 | bare | refused |  | John Straker is a character from the British television series *Agatha Christie's Poirot*. In the episode titled "The Murder of John Straker," which is part of the *Poirot* series, John Straker is indeed a character, and he is mu… |
| pr-silver-2 | full | wrong | vector | From the sources: [4: "Silas Brown, the trainer, is known to have had large bets upon the event, and he was no friend to poor Straker."] [10: "It was clear, however, that Straker had defended himself vigorously against his assail… |
| pr-silver-2 | cut | wrong | vector | From the sources: [5: "Silas Brown, the trainer, is known to have had large bets upon the event, and he was no friend to poor Straker."] [8: "“John Clay, the murderer, thief, smasher, and forger."] |
| pr-silver-2 | bare | refused |  | There is no known public figure or widely recognized case involving a person named John Straker who was a trainer and murdered. As of now, there is no credible evidence or record in official databases, news reports, or historical… |
| pr-speckled-1 | full | refused | vector | In these materials there is nothing about this. |
| pr-speckled-1 | cut | refused | vector | In these materials there is nothing about this. |
| pr-speckled-1 | bare | refused |  | Julia Stoner did not die in a real-world, documented event. Julia Stoner is a fictional character from the novel *The Girl with the Dragon Tattoo* by Stieg Larsson. In the story, Julia Stoner is a character who is portrayed as a … |
| pr-speckled-2 | full | wrong | vector | From the sources: [2: "Round his brow he had a peculiar yellow band, with brownish speckles, which seemed to be bound tightly round his head."] [4: "It was very long, though—almost as long, Watson, as when you and I waited in tha… |
| pr-speckled-2 | cut | wrong | vector | From the sources: [4: "A double band of white shells were strung round the centre of it."] |
| pr-speckled-2 | bare | named |  | The **Speckled Band** is a famous fictional story by **Sir Arthur Conan Doyle**, one of the most renowned authors in the world of detective fiction. It is a short story that was first published in 1892 as part of a collection tit… |
| pr-norwood-1 | full | wrong | vector | From the sources: [12: "Was not that person the actual criminal?"] [13: "You can hardly find a flaw in the case which can now be presented against him, and all further investigation has served to strengthen it."] |
| pr-norwood-1 | cut | wrong | vector | From the sources: [10: "“Do you think that this man Horner is innocent?”"] [12: "Was not that person the actual criminal?"] |
| pr-norwood-1 | bare | refused |  | There is no widely known or officially documented case called the "Norwood Builder case" in historical or legal records. It's possible that you may be referring to a fictional scenario, a misremembered name, or a case that is not… |
| pr-norwood-2 | full | wrong | vector | From the sources: [4: "It is known that Mr. Jonas Oldacre had received a late visitor in his bedroom upon that night, and the stick found has been identified as the property of this person, who is a young London solicitor named J… |
| pr-norwood-2 | cut | wrong | vector | From the sources: [3: "Mr. Jonas Oldacre is a well-known resident of that suburb, where he has carried on his business as a builder for many years."] [3: "It is known that Mr. Jonas Oldacre had received a late visitor in his bedr… |
| pr-norwood-2 | bare | refused |  | As of now, there is no publicly known figure named Jonas Oldacre in reliable historical, biographical, or governmental records. The name does not appear in any verified databases, news sources, or official records related to publ… |
| pr-naval-1 | full | refused | vector | In these materials there is nothing about this. |
| pr-naval-1 | cut | wrong | vector | From the sources: [3: "Presuming that your theory is correct, if he can lay his hands upon the man who threatened you last night he will have gone a long way towards finding who took the naval treaty."] [3: "Phelps was still weak… |
| pr-naval-1 | bare | refused |  | There is no historical or credible record of a "naval treaty" being stolen from Percy Phelps, and no known figure named Percy Phelps is associated with such an event in historical or diplomatic records. Percy Phelps was a real pe… |
| pr-naval-2 | full | named | vector | From the sources: [4: "Joseph a villain and a thief!”"] [5: "“‘Stolen!’ he cried. “‘Yes, thief!’"] |
| pr-naval-2 | cut | wrong | vector | From the sources: [2: "Why should a thief try to break in at a bedroom window, where there could be no hope of any plunder, and why should he come with a long knife in his hand?”"] [8: "‘A document of immense value has been stole… |
| pr-naval-2 | bare | refused |  | There is no known case called the "Naval Treaty case" involving a thief, and no widely recognized historical or legal case by that name exists in international law, maritime history, or criminal justice records. It's possible tha… |
| pr-black-1 | full | wrong | vector | From the sources: [2: "That very night he went down to Woodman’s Lee, saw Peter Carey at the hut, quarrelled with him, and killed him with the harpoon."] [3: "You say I murdered Peter Carey, I say I _killed_ Peter Carey, and ther… |
| pr-black-1 | cut | wrong | vector | From the sources: [8: "Did his companions follow him and kill him?"] [10: "The fact that the crime was committed at two in the morning, and yet Peter Carey was fully dressed, suggested that he had an appointment with the murderer… |
| pr-black-1 | bare | wrong |  | Peter Carey did not die. Peter Carey is a living Australian author, known for his novels such as *True History of the Kelly Gang*, *Oscar and Lucinda*, and *The Water Diviner*. As of now, he is alive and active in the literary wo… |
| pr-black-2 | full | wrong | vector | From the sources: [2: "I knew Black Peter, and when he pulled out his knife I whipped a harpoon through him sharp, for I knew that it was him or me."] [5: "That very night he went down to Woodman’s Lee, saw Peter Carey at the hut… |
| pr-black-2 | cut | refused | vector | In these materials there is nothing about this. |
| pr-black-2 | bare | refused |  | There is no known figure named Peter Carey who is the victim of a murder, and no widely recognized case or public record identifies a "true murderer" of someone named Peter Carey. Peter Carey is, in fact, a well-known Australian … |
| pr-thor-1 | full | refused | vector | In these materials there is nothing about this. |
| pr-thor-1 | cut | refused | vector | In these materials there is nothing about this. |
| pr-thor-1 | bare | refused |  | Maria Gibson was not a real person, and there is no verified historical or public record of someone by that name being killed. It's possible there is a mix-up with the name or a confusion with another individual. If you meant a d… |
| pr-thor-2 | full | refused | vector | In these materials there is nothing about this. |
| pr-thor-2 | cut | refused | vector | In these materials there is nothing about this. |
| pr-thor-2 | bare | refused |  | Maria Gibson is not a widely recognized public figure, and there is no credible or verified information indicating that someone named Maria Gibson died under specific circumstances that are publicly documented or widely reported.… |
| pr-reigate-1 | full | wrong | vector | From the sources: [3: "Whoever wrote that note was the man who brought William Kirwan out of his bed at that hour."] [4: "“Before going into this, I would draw your attention to the fact that, if Alec Cunningham’s narrative was c… |
| pr-reigate-1 | cut | wrong | vector | From the sources: [2: "Whoever wrote that note was the man who brought William Kirwan out of his bed at that hour."] [10: "“Who shot him, then?”"] |
| pr-reigate-1 | bare | refused |  | William Kirwan was not murdered. William Kirwan was a prominent American academic and administrator, best known for serving as the president of the University of Maryland, College Park, from 1970 to 1980. There is no credible evi… |
| pr-reigate-2 | full | wrong | vector | From the sources: [5: "McFarlane’s guilt definitely established."] [9: "He made a complete voluntary confession."] |
| pr-reigate-2 | cut | wrong | vector | From the sources: [5: "McFarlane’s guilt definitely established."] [9: "He made a complete voluntary confession."] |
| pr-reigate-2 | bare | refused |  | The Reigate Squires case is a real historical event, but it is important to clarify that there is no widely known or officially documented case involving "Reigate Squires" that has a definitive "guilty man" identified in a crimin… |

## Cases

- **boscombe-valley-mystery** (cut at 36458): Cut before Holmes shows Lestrade the stone ('The murder was done with it') and describes the murderer (tall, left-handed, lame, grey cloak); everything before is the inquest narrative, the Turner family introduction and the site visit. The Cooee/Ballarat deduction, the confession and the name follow. Truth: John Turner of the Hall (once 'Black Jack of Ballarat') killed Charles McCarthy; James McCarthy is innocent.
- **silver-blaze** (cut at 40470): Cut before the Wessex Cup scene in which Holmes says the real murderer is the horse; Holmes's earlier hints (the dog in the night-time, the lame sheep) are clues, not statements of the solution. Truth: The horse Silver Blaze killed John Straker, in self-defence, when Straker tried to nick its tendon; Fitzroy Simpson is not the culprit.
- **speckled-band** (cut at 39716): Cut before Holmes's night-time explanation at the inn (the ventilator, the bell-rope, the clamped bed); the snake is first named at the dénouement, after the cut. Truth: A swamp adder, a snake trained by Dr. Grimesby Roylott and sent through the ventilator, killed Julia Stoner; the 'speckled band' is the snake.
- **norwood-builder** (cut at 37573): Cut before Holmes says the thumb-mark was not there the day before; the hidden room, Oldacre's appearance and the explanation of the plot follow. Truth: Jonas Oldacre is alive and was hiding in a concealed room of his own house; he framed John Hector McFarlane.
- **naval-treaty** (cut at 57675): Cut before the breakfast at which the treaty reappears on Phelps's plate and Holmes tells how he caught Joseph Harrison; the scene before it (Holmes's failed day, the table laid) names no one. Truth: Joseph Harrison, the brother of Phelps's fiancee, stole the treaty and hid it under the bedroom floor.
- **black-peter** (cut at 29725): Cut before Holmes's telegrams to the shipping agent and to Hopkins and the breakfast scene where he demolishes the case against Neligan and the harpooner is arrested. Truth: Patrick Cairns, a harpooner of the Sea Unicorn, killed Peter Carey; young Neligan is innocent.
- **thor-bridge** (cut at 43341): Cut before Holmes leaves the cell at Winchester with the solution; the chip in the stonework is already known, its explanation, the revolver test and the review of the plot are after the cut. Truth: Maria Gibson killed herself and arranged the scene to frame Grace Dunbar, who is innocent.
- **reigate-squires** (cut at 22620): Cut before the house search in which Holmes upsets the carafe and is attacked; the accusation, the paper in the dressing-gown and the full explanation follow. Truth: Alec Cunningham and his father murdered their coachman William Kirwan.
