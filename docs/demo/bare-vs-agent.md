# Bare model against the agent: errors recorded in the evaluation run (2026-10-28)

Source: `docs/spike/results/eval-2026-10-28-dev-ab945e8-78b3bbb3f2a6-145202-rescored.json` (dev split, one run, generator qwen3:4b-instruct,
temperature 0; the bare model gets the question only, no sources). Nothing here was staged: these are the first answers the runner recorded.
The questions were not chosen after looking at the answers: they are the first questions of the dev split.

| Question | Bare model (no sources) | Agent |
|---|---|---|
| g001 `What kind of snake killed Dr. Grimesby Roylott?` | "Dr. Grimesby Roylott was not killed by a snake in the story of *The Hound of the Baskervilles* or any of Sir Arthur Conan Doyle's Sherlock Holmes stories." Then it contradicts itself ("a cobra", "Wait - correction") and stops mid-argument (39 s). Wrong: he is killed by a swamp adder in *The Speckled Band*. | `[6: "“It is a swamp adder!” cried Holmes; “the deadliest snake in India."]` (30 s) |
| g003 `What reward was offered for the return of the Countess of Morcar's blue carbuncle?` | "There is no historical record or credible source indicating that a reward was offered ... The 'Countess of Morcar' is not a historically documented figure": it treats a fictional jewel as a historical claim and denies the reward (32 s). Wrong: the text says 1000 pounds. | `[1: "... the reward offered of £ 1000 ..."] [5: "I have already offered a reward of £ 1000."]` |
| g062 (Russian) `Какая змея, по словам Холмса, убила доктора Ройлотта?` | Invents an author "Айрон С. Холмс" and a story "Приключения змеи", then repeats that the story "does not exist" in a loop (41 s). | the same swamp-adder sentence, question translated to English first (30 s) |

How to say it on stage (one sentence): "Without sources a four-billion-parameter model confidently denies a snake that is in the text; with sources it quotes the sentence."
Limits: three questions of one split, one run, one small model. A bigger model may do better; this says what THIS model does without the corpus.
Live version: ask the same question on the screen (the agent answer takes about 30 s); the bare answer is shown from this recorded run, labelled as a recording.
