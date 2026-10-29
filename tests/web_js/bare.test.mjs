import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { normaliseBare, bareLabel, revealedChars, recordedSeconds } from "../../web/js/bare.js";
import { findRecording } from "../../web/js/demo.js";

const ROOT = new URL("../../", import.meta.url);
const BARE = new URL("web/replay/bare/", ROOT);
const index = JSON.parse(readFileSync(new URL("web/replay/index.json", ROOT), "utf8"));
const files = readdirSync(BARE).filter((f) => f.endsWith(".json")).sort();
const load = (f) => JSON.parse(readFileSync(new URL(f, BARE), "utf8"));

test("every bare recording is labelled, has text, and is the eval run's answer byte for byte", () => {
  assert.ok(files.length >= 2, "at least two recorded bare-model errors (issue #13)");
  for (const f of files) {
    const { meta, answer } = normaliseBare(load(f));
    assert.equal(meta.label, "RECORDING", f);
    assert.equal(meta.kind, "bare model, no sources", f);
    const run = JSON.parse(readFileSync(new URL(meta.source, ROOT), "utf8"));
    const rows = run.rows.filter((r) => r.config === "bare" && r.id === meta.qid);
    assert.equal(rows.length, 1, `${f}: one bare row for ${meta.qid} in ${meta.source}`);
    assert.equal(answer, rows[0].answer, `${f}: not the recorded answer`);
    assert.equal(meta.seconds, rows[0].total_s, f);
    assert.equal(meta.ttft_s, rows[0].ttft_s, f);
    assert.equal(meta.git_sha, run.meta.git_sha.slice(0, 7), f);
    assert.equal(meta.model, run.meta.generator, f);
  }
});

test("index.json lists every bare recording once, apart from the stored runs", () => {
  assert.deepEqual(index.bare.map((r) => r.file).sort(), files.map((f) => `bare/${f}`), "run scripts/replay_index.py");
  for (const r of index.bare) assert.equal(r.question, load(r.file.slice(5)).meta.question, `${r.file}: index.json is stale`);
  assert.ok(index.recordings.every((r) => !r.file.startsWith("bare/")), "bare answers are not stored runs (no events to play)");
});

test("the bare recording of a question: same matching as stored runs, never another question", () => {
  assert.equal(findRecording(index.bare, "What kind of snake killed Dr. Grimesby Roylott?").file, "bare/g001.json");
  assert.equal(findRecording(index.bare, "what kind of snake killed dr grimesby roylott").file, "bare/g001.json");
  assert.equal(findRecording(index.bare, "What kind of snake killed Dr. Grimesby Roylott's sister?"), null);
  assert.equal(findRecording(index.bare, "Какая змея, по словам Холмса, убила доктора Ройлотта?").file, "bare/g062.json");
});

test("the left column always says NO SOURCES and RECORDING, with model, date, run and times", () => {
  const l = bareLabel({ model: "qwen3:4b-instruct", recorded_on: "2026-10-28", git_sha: "ab945e8", split: "dev", ttft_s: 0.826, seconds: 38.965, call: "question only" });
  assert.deepEqual(l.badges, ["NO SOURCES", "RECORDING"]);
  assert.equal(l.line, "qwen3:4b-instruct · 2026-10-28 · eval run ab945e8, dev split · first token 0.8 s, 39 s in all");
  assert.equal(l.call, "question only");
  assert.deepEqual(bareLabel({}).badges, ["NO SOURCES", "RECORDING"]);
  const html = readFileSync(new URL("web/index.html", ROOT), "utf8");
  const panel = html.slice(html.indexOf('id="panel-bare"'), html.indexOf("</section>", html.indexOf('id="panel-bare"')));
  assert.match(panel, /NO SOURCES/);
  assert.match(panel, /RECORDING/);
});

test("the text arrives at the recorded pace: nothing before the first token, all at the total", () => {
  const meta = { ttft_s: 1, seconds: 11 };
  const a = "x".repeat(100);
  assert.equal(revealedChars(a, meta, 0), 0);
  assert.equal(revealedChars(a, meta, 999), 0);
  assert.equal(revealedChars(a, meta, 1000), 1, "the first token shows something");
  assert.equal(revealedChars(a, meta, 6000), 50);
  assert.equal(revealedChars(a, meta, 11000), 100);
  assert.equal(revealedChars(a, meta, 99999), 100);
  assert.equal(revealedChars(a, meta, 3000, 2), 50, "speed 2 plays twice as fast");
  let prev = 0;
  for (let ms = 0; ms <= 12000; ms += 250) { const n = revealedChars(a, meta, ms); assert.ok(n >= prev); prev = n; }
  assert.equal(revealedChars(a, {}, 0), 100, "no times recorded: shown at once");
  assert.equal(recordedSeconds(meta, 5000), 5);
  assert.equal(recordedSeconds(meta, 50000), 11);
});

test("an unlabelled or empty bare recording is refused, not shown", () => {
  assert.throws(() => normaliseBare(null));
  assert.throws(() => normaliseBare([]));
  assert.throws(() => normaliseBare({ answer: "x" }), /no meta/);
  assert.throws(() => normaliseBare({ meta: { label: "LIVE" }, answer: "x" }), /RECORDING/);
  assert.throws(() => normaliseBare({ meta: { label: "RECORDING" }, answer: "  " }), /no answer/);
});
