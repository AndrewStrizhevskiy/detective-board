# Stage checklist (print it; tick in the order written)

Build for the show: the tag the team agreed on (`git describe --tags`; offline archive `detective-board-offline-<tag>.tar`, check its sha256 on the stick).

## The evening before (Thursday)
- [ ] Charger, adapter (HDMI/USB-C to the projector) and a spare cable in the bag; the projector resolution is probably 1366x768 or 1920x1080: open the UI at both once.
- [ ] The archive on the USB stick (formatted exFAT, not FAT32: the archive is over 4 GB) AND on the laptop; `sha256sum -c` passes on both.
- [ ] The backup screen recording (mp4, one clip per step and the full run) on the stick and on the laptop, played once.
- [ ] Printed or offline copies: this checklist, `docs/design/demo-script.md` section 2a (operator cards), `docs/demo/jury-faq.md`.
- [ ] A fresh `just run` from the archive on the laptop with the network OFF; the three scripted questions answer (g001, the Garcia R1, the refusal).
- [ ] Disclosure slide reads: precomputed on other hardware with the same models (allowed by the organizers), curated facts human-checked and labelled, gold sets AI-written (human review date or "not done"), test split run once.

## T-60 min on site
- [ ] Mains power, performance profile, battery saver off, notifications and updates off, screen lock off, display never sleeps, brightness full.
- [ ] Close everything except the browser and one terminal; no VPN client, no second VPN, no Docker containers (they take CPU and memory); Wi-Fi off (the show is offline).
- [ ] Cooling: laptop on a stand or hard flat surface, vents free; plan a 20 s pause between live questions (it reached 92 C after six questions in a row).
- [ ] Browser zoom so the board and the answer are readable from the back row; font size of the terminal 20 pt.

## T-10 min
- [ ] `just run`; open http://127.0.0.1:8000/ in full screen.
- [ ] Warm the model: one throw-away question that is not in the script (about 30-45 s; then `ollama ps` shows qwen3:4b-instruct loaded, `UNTIL` in the future; keep_alive is 30 min).
- [ ] Open the replay tabs in a second window: `?replay=replay/real-g001-agent.json&speed=4`, `real-wisteria-r1-curated.json`, `real-refusal-baskerville.json`, `real-abbey-grange-r1-curated.json`, `real-scene-board.json`, `real-garcia-timeline.json` (the badge must read RECORDING).
- [ ] The full backup video open and paused at 0:00 on the second window.
- [ ] Timer visible to the speaker; a glass of water.

## If something goes wrong (say these words, do not improvise)
| Symptom | Do | Say |
|---|---|---|
| Nothing on the screen / the page does not load | open the full backup video | "The live system is not responding; this is the recorded run of the same demo." |
| The model is slow (more than 45 s to the first token) | press `c` (stored run, badge RECORDING) | "The model on this CPU needs a moment; here is the stored run of this exact question, labelled." |
| The connection-lost banner appears | click "Play the stored run" | the same sentence |
| A wrong or odd answer | do not re-ask; narrate: show the quote and the trace; "this is exactly why every answer carries its quote" | "The check is that the quote is in the book; here it is." |
| Ollama is not running | in the terminal `ollama serve` (or the archive's Ollama), then warm up; meanwhile use the recordings | "Starting the local model; meanwhile the stored runs." |
| The API stopped or was restarted (page shows connection lost, `/api/health` does not answer) | in the API terminal `Ctrl+C`, then `just run` (about 5 s); click "Play the stored run" for the question that was running; reload the page when the terminal shows the URL | "The server restarted; the stored run of this question meanwhile, then we continue live." |
| The browser crashed or the tab closed | reopen the browser, `http://127.0.0.1:8000/` from history, full screen (`F11`); the replay tabs: reopen from the second window's history | "One moment, reopening the page." |
| The projector is 1366x768 and the board is cut | browser zoom `Ctrl+-` to 80 % (try it once in a rehearsal at 1366x768); the terminal font stays 20 pt | nothing; do it during the slide change |
| Wi-Fi came on, or the network changed | nothing is needed (the show is offline, no request leaves the laptop); switch Wi-Fi off again after the step | "The system runs offline; the network does not matter." |
| A jury question about numbers | open `docs/slides/numbers.md` backup slide | read the number AND its caveat |

## After the show
- [ ] Note the questions the jury asked and any answer that failed (for `docs/demo/rehearsals.md`).
- [ ] Do not delete the archive until the results are announced.
