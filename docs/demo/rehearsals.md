# Rehearsal log (fill it in during the three runs; times with a stopwatch)

Rules: full run with the timer, live parts live, recordings as recordings; one observer writes the interventions; the script is fixed after each run, not the code.

| # | Date, place | Total (min:s) | Step 0 first trace row (s) | Step 0 g001 total (s) | Step 2 (Garcia R1) ms | Step 3 refusal ms | Interventions (what, when, why) | Questions an observer would ask |
|---|---|---|---|---|---|---|---|---|
| 1 | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| 2 | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| 3 | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |

Failure drills (each once; write the time to recover): Ollama stopped; slow model (stop the model mid-answer with `ollama stop`); Wi-Fi on and off; resolution 1366x768; browser crash (reopen the page); API restarted (`kill` the API and `just run`); the key `c` pressed during a live run.
Target: three runs under 7:00; recovery from every drill within 20 s, using only the words in `docs/demo/STAGE_CHECKLIST.md`.

| Drill | How to cause it during a run | Expected recovery (row of STAGE_CHECKLIST) | Recovery time (s) | Date, who |
|---|---|---|---|---|
| Ollama stopped | `ollama stop qwen3:4b-instruct` before a live question (or stop the service) | "Ollama is not running" | TBD | TBD |
| Slow model | `ollama stop qwen3:4b-instruct` mid-answer, or ask with a cold model | "The model is slow": `c` | TBD | TBD |
| Wi-Fi on/off | toggle Wi-Fi during a live question | "Wi-Fi came on": nothing changes | TBD | TBD |
| 1366x768 | set the display (or the projector) to 1366x768 before the run | "The projector is 1366x768": `Ctrl+-` | TBD | TBD |
| Browser crash | close the browser window mid-step | "The browser crashed" | TBD | TBD |
| API restarted | `Ctrl+C` in the API terminal mid-answer | "The API stopped": `just run`, stored run | TBD | TBD |
| `c` during a live run | press `c` while the model streams | the stored run plays with RECORDING (write down whether the live run stopped) | TBD | TBD |
