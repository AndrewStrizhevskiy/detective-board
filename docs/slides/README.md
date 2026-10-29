# Slides: Detective Board (6:30 talk)

> The talk is given from the RUSSIAN deck, `deck.ru.md` (dark theme, `README.ru.md`, `deck.ru.pdf`). This English `deck.md` is the archive and the source of the numbers.

Files
- `deck.md`: Marp-compatible Markdown. 10 main slides (6:30 in total, timing and speaker notes in the HTML comment at the top of each slide) plus backup slides B1-B6 that are not part of the 6:30.
- `numbers.md`: every number on a slide, its source file and n; the open `TBD` markers.
- The demo steps behind slides 4-6 are in `docs/design/demo-script.md` (section 2a).

## Render to PDF (offline)

Marp CLI (needs Node; install once with network, then it works offline):

```bash
npx @marp-team/marp-cli docs/slides/deck.md --pdf --allow-local-files -o docs/slides/deck.pdf
npx @marp-team/marp-cli docs/slides/deck.md --pdf-notes --pdf --allow-local-files -o docs/slides/deck-with-notes.pdf   # notes as PDF annotations
```

Or the VS Code Marp extension (Export Slide Deck). Any other tool works too: the file is plain Markdown with `---` between slides, so `pandoc -t beamer docs/slides/deck.md -o deck.pdf` gives a plain version (HTML comments are dropped; the `style` header is ignored). The diagram on slide 3 is a text block, so no plugin is needed.

The exported PDF is not committed yet: render it after the numbers are final (issue #12 asks for the PDF with the final deck on Thu 29 Oct). Check that no `TBD` is left on a slide, or that it is read aloud as "not yet measured".

## Where each number comes from

| Slide | Numbers | File |
|---|---|---|
| 1 | bare-model transcript | `docs/spike/results/answers-20261023-v3-BARE-qwen3_4b-instruct.jsonl` |
| 4, 6, 7 | 12-question real-API run, extractive | `docs/spike/results/api12-20261027-extractive.md` |
| 6 | gate 0.17 / 0.25 | `docs/spike/results/answers-20261023-v3-qwen3_4b-instruct.jsonl` |
| 7 | 5 of 10, 8 of 12, 1 of 3 vs 2 of 3 | `docs/spike/results/answers-20261023-v3.md` |
| 7, B3 | 70 of 86 | `docs/spike/results/evidence-20261023-093201.md` |
| 8, B4 | 21 tokens/s, 42.7 s vs 52.7 s | `docs/perf/ttft-levers-2026-10-26.md` |
| 8 | 3195 MiB | `docs/spike/results/llm-20261022-171202.md` |
| B1 | first real extraction run | `docs/STATUS.md` |
| B2 | strict F1 v2.1 vs v2.2 | `docs/spike/results/prompt-v2-2-20261026.md` |
| B3 | hit@5 0.97 | `docs/spike/results/arms-20261023-080849.md` |

The full list with n and caveats is `numbers.md`. Nothing on a slide is rounded up; a rate is never shown without its n.

## Before the talk

1. `rg` each number of `numbers.md` against its file (pre-show check from demo-script section 5).
2. Replace every `TBD` once issue #16 / #6 deliver; update `numbers.md` in the same commit.
3. Do not edit the disclosure slide (9) without comparing it with `docs/DISCLOSURE.md`.
