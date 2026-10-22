import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { normaliseRecording, replayDelays, playReplay, safeReplayPath } from "../../web/js/replay.js";
import { placeNew } from "../../web/js/layout.js";

const ev = (type, ts) => ({ type, ts });

test("delays follow original timing, with speed and cap", () => {
  const evs = [ev("a", "2026-01-01T00:00:00.000Z"), ev("b", "2026-01-01T00:00:01.500Z"), ev("c", "2026-01-01T00:00:11.500Z")];
  assert.deepEqual(replayDelays(evs), [0, 1500, 10000]);
  assert.deepEqual(replayDelays(evs, { speed: 2 }), [0, 750, 5000]);
  assert.deepEqual(replayDelays(evs, { cap: 2000 }), [0, 1500, 2000]);
  assert.deepEqual(replayDelays([ev("a", "bad"), ev("b", "bad")]), [0, 0]);
});

test("playReplay yields events in order using the injected sleep", async () => {
  const slept = [];
  const evs = [ev("a", "2026-01-01T00:00:00.000Z"), ev("b", "2026-01-01T00:00:00.300Z")];
  const got = [];
  for await (const e of playReplay(evs, { sleep: async (ms) => slept.push(ms) })) got.push(e.type);
  assert.deepEqual(got, ["a", "b"]);
  assert.deepEqual(slept, [300]);
});

test("abort stops playback", async () => {
  const ctl = new AbortController();
  const evs = [ev("a", "2026-01-01T00:00:00.000Z"), ev("b", "2026-01-01T00:00:01.000Z"), ev("c", "2026-01-01T00:00:02.000Z")];
  const got = [];
  for await (const e of playReplay(evs, { signal: ctl.signal, sleep: async () => ctl.abort() })) got.push(e.type);
  assert.deepEqual(got, ["a"]);
});

test("normaliseRecording accepts both formats and rejects junk", () => {
  assert.equal(normaliseRecording([{ type: "x" }]).events.length, 1);
  assert.equal(normaliseRecording({ meta: { question: "q" }, events: [{ type: "x" }] }).meta.question, "q");
  assert.throws(() => normaliseRecording({ nope: 1 }));
  assert.throws(() => normaliseRecording([{ foo: 1 }]));
});

test("shipped replay files are valid recordings", () => {
  for (const f of ["fake-speckled-band.json", "synthetic-derived.json"]) {
    const r = normaliseRecording(JSON.parse(readFileSync(new URL(`../../web/replay/${f}`, import.meta.url))));
    assert.equal(r.events.at(-1).type, "final");
  }
});

test("safeReplayPath rejects traversal, schemes and absolute paths", () => {
  assert.equal(safeReplayPath("replay/run.json"), "replay/run.json");
  for (const bad of ["../x.json", "/etc/passwd", "http://evil/x.json", "a\\b", "", null, "a b.json"]) assert.equal(safeReplayPath(bad), null, String(bad));
});

test("layout is deterministic and never moves placed nodes", () => {
  const first = placeNew({}, ["a", "b"], [{ src: "a", dst: "b" }]);
  assert.deepEqual(first.a, { x: 0, y: 0 });
  assert.ok(Math.hypot(first.b.x, first.b.y) > 100);
  const again = placeNew({}, ["a", "b"], [{ src: "a", dst: "b" }]);
  assert.deepEqual(first, again);
  const more = placeNew(first, ["a", "c", "d"], [{ src: "a", dst: "c" }]);
  assert.equal(more.a, undefined);
  const all = { ...first, ...more };
  const pts = Object.values(all);
  for (let i = 0; i < pts.length; i++) for (let j = i + 1; j < pts.length; j++) assert.ok(Math.hypot(pts[i].x - pts[j].x, pts[i].y - pts[j].y) > 50);
});
