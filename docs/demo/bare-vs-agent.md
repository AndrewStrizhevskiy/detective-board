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

## Split view on the board (key `b`, issue #13)

Press `b` on the board: the left column (where the trace was) shows the bare model's recorded answer to the question in the box,
labelled **NO SOURCES** and **RECORDING**, with model, date, eval run and times; the board and the answer panel on the right are
the agent ("Detective Board, with sources"). The text arrives at the recorded pace (first token, total time; the run keeps no
per-token times, so the pace in between is even); **Show all** or Motion off shows it at once. With the split open, Enter asks the
agent live while the bare answer plays next to it; `c` plays the agent's stored run instead. `b` again closes it.

| File | Question | Bare model (from the run) | True answer, quote verbatim in `data/clean/` (`grep -F`, 2026-10-29) |
|---|---|---|---|
| `web/replay/bare/g001.json` | g001 | denies the snake, names a cobra, places Roylott in *The Hound of the Baskervilles*; 300-token cap reached | a swamp adder: “It is a swamp adder!” cried Holmes; “the deadliest snake in India. (`speckled-band.txt`) |
| `web/replay/bare/g003.json` | g003 | says no reward is recorded, calls the jewel "fictional or misattributed" | £1000: the reward offered of £ 1000 is certainly not within a twentieth part of the market price (`blue-carbuncle.txt`) |
| `web/replay/bare/g062.json` | g062 (Russian) | invents an author ("рассказу Айрона С. Холмса") and a story («Приключения змеи») | as g001 |

- Source of every file: `docs/spike/results/eval-2026-10-28-dev-ab945e8-78b3bbb3f2a6-145202-rescored.json` (commit `ab945e8`,
  qwen3:4b-instruct, temperature 0, seed 42, question only, 300-token cap, ThinkPad X1 Carbon 7th gen). The answers are byte for
  byte those of the run (the rescoring changed no answer; `tests/test_bare_recording.py` and `tests/web_js/bare.test.mjs` check
  it). Made with `python3 scripts/bare_recording.py --eval <that file> --ids g001 g003 g062`, then `scripts/replay_index.py`.
- The quotes are the gold quotes of `eval/golden/questions.jsonl` and were found verbatim with `grep -F`: a mechanical check.
  **Human check of the three bare errors against the story text: pending** (issue #13 asks for it; reviewer and date go here).
- A bare recording holds text only, no trace events: it is not a stored run and is not in the Recordings picker.
- **Not the same run as step 0 of the demo script.** Step 0 and the slides use the 2026-10-23 transcript
  (`answers-20261023-v3-BARE-qwen3_4b-instruct.jsonl`, first token 1.4 s, 48.7 s); key `b` shows the 2026-10-28 dev eval run (0.8 s,
  39 s). Same model and settings, slightly different text. Whoever shows `b` names the date on screen, not "the recording from
  step 0".
- Status: built after the feature freeze (2026-10-28); for after the show unless the tech lead decides otherwise (issue #13).
