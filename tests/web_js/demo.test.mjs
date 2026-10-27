import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { normQuestion, editDistance, findRecording, recordingLabel, stalled, recoveryActions, STALL_MS, STORED_RUN_CAP_MS } from "../../web/js/demo.js";
import { askStream } from "../../web/js/api.js";
import { normaliseRecording } from "../../web/js/replay.js";
import { initialState, reduce } from "../../web/js/state.js";

const REPLAY = new URL("../../web/replay/", import.meta.url);
const index = JSON.parse(readFileSync(new URL("index.json", REPLAY), "utf8"));
const recs = index.recordings;

test("questions are compared without case, quotes or punctuation", () => {
  assert.equal(normQuestion("  Are there contradictions in James McCarthy’s account?? "), "are there contradictions in james mccarthys account");
  assert.equal(normQuestion("What is a swamp-adder?"), "what is a swamp adder");
  assert.equal(normQuestion(null), "");
});

test("the stored run of a question: exact, near-exact, never a different question", () => {
  assert.equal(findRecording(recs, "What kind of snake killed Dr. Grimesby Roylott?").file, "real-g001-agent.json");
  assert.equal(findRecording(recs, "what kind of snake killed dr grimesby roylott").file, "real-g001-agent.json");
  assert.equal(findRecording(recs, "Are there contradictions in James McCarthy’s account?").file, "fake-mccarthy.json");
  assert.equal(findRecording(recs, "What kind of snake killed Grimesby Roylott?").file, "real-g001-agent.json", "one word missing still matches");
  assert.equal(findRecording(recs, "What kind of dog killed Sir Charles?"), null);
  assert.equal(findRecording(recs, "What kind of snake killed Dr. Grimesby Roylott's sister?"), null, "one added word is another question");
  assert.equal(findRecording(recs, "What kind of snake killed Dr. Grimesby Roylot?").file, "real-g001-agent.json", "a typo still matches");
  assert.equal(findRecording(recs, ""), null);
  assert.equal(findRecording(null, "x"), null);
});

test("a real run wins over a fake one for the same question", () => {
  const list = [{ file: "fake-a.json", question: "Q one?", kind: "fake" }, { file: "real-a.json", question: "q ONE", kind: "real" }];
  assert.equal(findRecording(list, "q one").file, "real-a.json");
});

test("every recording is labelled as one, synthetic ones say so", () => {
  const real = recordingLabel({ kind: "real", recorded_at: "2026-10-27T11:50:40+0200", seconds: 39.1, step: "demo step 0" });
  assert.equal(real.badge, "RECORDING");
  assert.match(real.line, /real run on the target laptop · 2026-10-27 09:50 UTC · 39.1 s · demo step 0/);
  assert.equal(recordingLabel({ kind: "fake" }).badge, "RECORDING");
  assert.equal(recordingLabel({ kind: "synthetic" }).badge, "SYNTHETIC RECORDING");
  for (const r of recs) assert.match(recordingLabel(r).badge, /RECORDING/);
});

test("a live run is stalled after STALL_MS of silence, not before", () => {
  assert.equal(STALL_MS, 90000);
  assert.equal(stalled(0, STALL_MS - 1), false);
  assert.equal(stalled(0, STALL_MS), true);
  assert.equal(stalled(1000, 3500, 2000), true);
  assert.equal(stalled(NaN, 1e12), false);
  assert.ok(STORED_RUN_CAP_MS <= 2000, "stored runs cap gaps at 2 s (R-02)");
});

test("recovery offers the stored run of the same question, else the picker, and a live retry", () => {
  const withRec = recoveryActions("What kind of snake killed Dr. Grimesby Roylott?", recs);
  assert.deepEqual(withRec.map((a) => a.kind), ["replay", "retry"]);
  assert.equal(withRec[0].file, "real-g001-agent.json");
  assert.deepEqual(recoveryActions("Who stole the Blue Carbuncle?", recs).map((a) => a.kind), ["pick", "retry"]);
});

test("index.json lists every recording in web/replay once, with its own question", () => {
  const files = readdirSync(REPLAY).filter((f) => f.endsWith(".json") && f !== "index.json").sort();
  assert.deepEqual(recs.map((r) => r.file).sort(), files, "run scripts/replay_index.py after adding a recording");
  for (const r of recs) {
    const meta = JSON.parse(readFileSync(new URL(r.file, REPLAY), "utf8")).meta || {};
    assert.equal(r.question, meta.question, r.file);
    assert.ok(["real", "fake", "synthetic"].includes(r.kind), r.file);
  }
  // the stored runs the demo script relies on (docs/design/demo-script.md, pre-show checklist)
  for (const f of ["real-g001-agent.json", "real-wisteria-r1-curated.json", "real-refusal-baskerville.json", "real-boscombe-control.json", "real-refusal-fee.json"]) {
    const r = recs.find((x) => x.file === f);
    assert.ok(r && r.kind === "real", f);
    assert.equal(findRecording(recs, r.question).file, f);
  }
});

test("askStream reports activity for keepalive-only chunks too (R-03 watchdog)", async () => {
  const enc = new TextEncoder();
  const body = new ReadableStream({ start(c) { c.enqueue(enc.encode(": keepalive\n\n")); c.enqueue(enc.encode(": keepalive\n\n")); c.enqueue(enc.encode('event: final\ndata: {"type":"final","status":"answered"}\n\n')); c.close(); } });
  let ticks = 0;
  const got = [];
  for await (const e of askStream("q", [], { fetchImpl: async () => new Response(body, { status: 200 }), onActivity: () => ticks++ })) got.push(e.type);
  assert.deepEqual(got, ["final"]);
  assert.ok(ticks >= 4, `headers + 3 chunks, got ${ticks}`);
});

test("edit distance", () => {
  assert.equal(editDistance("kitten", "sitting"), 3);
  assert.equal(editDistance("", "abc"), 3);
  assert.equal(editDistance("same", "same"), 0);
});

test("every recording plays through the reducer to its final event", () => {
  for (const r of recs) {
    const rec = normaliseRecording(JSON.parse(readFileSync(new URL(r.file, REPLAY), "utf8")));
    let s = reduce(initialState(), { type: "run_start", question: rec.meta.question, mode: "replay", now: 0 });
    rec.events.forEach((ev, i) => { s = reduce(s, { type: "event", event: ev, now: i + 1 }); });
    assert.equal(s.phase, "done", r.file);
    assert.equal(s.mode, "replay", r.file);
    assert.ok(s.final && ["answered", "refused", "partial"].includes(s.final.status), `${r.file}: ${s.final && s.final.status}`);
  }
});
