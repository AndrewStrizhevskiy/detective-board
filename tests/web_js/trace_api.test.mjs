import test from "node:test";
import assert from "node:assert/strict";
import { traceRows, healthSummary } from "../../web/js/trace.js";
import { askStream, ApiError, friendlyError } from "../../web/js/api.js";
import { initialState, reduce } from "../../web/js/state.js";

test("traceRows folds tokens into one row per attempt and keeps order", () => {
  const rows = traceRows([
    { seq: 0, type: "route_decided", routes: ["graph", "vector"], method: "rules", reason: "why", matched: ["x"] },
    { seq: 1, type: "answer_token", attempt: 1, text: "a" }, { seq: 2, type: "answer_token", attempt: 1, text: "b" },
    { seq: 3, type: "answer_token", attempt: 2, text: "c" },
    { seq: 4, type: "refusal", code: "no_evidence", message: "m", missing: ["x"], searched: ["s"] },
  ]);
  assert.deepEqual(rows.map((r) => r.type), ["route_decided", "answer_token", "answer_token", "refusal"]);
  assert.equal(rows[1].count, 2);
  assert.match(rows[0].summary, /GRAPH \+ VECTOR \(rules\): why/);
  assert.equal(rows[3].status, "info");
});

test("retrieval row lists per-arm ranks and the gate", () => {
  const [r] = traceRows([{ seq: 0, type: "retrieval_results", hits: [{ chunk_id: "c1", story: "s", rank: 1, rrf: 0.03, ranks: { bm25: 2, vec: 1 }, scores: {} }], gate: { passed: false, best_score: 0.01, threshold: 0.018, support: 0, min_support: 0.25, reason: "weak" }, chunk_ids: ["c1"] }]);
  assert.match(r.list[0].text, /bm25 #2, vec #1/);
  assert.equal(r.status, "warn");
  assert.equal(r.list[0].chunk_id, "c1");
});

test("healthSummary: ok, degraded, down", () => {
  assert.equal(healthSummary({ status: "ok", fake: true, ollama: { reachable: null }, index: { present: true }, graph: { present: true } }).level, "ok");
  const d = healthSummary({ status: "degraded", ollama: { reachable: false, models: { llm: false, embedding: true } }, index: { present: false } });
  assert.equal(d.level, "degraded");
  assert.equal(d.problems.length, 3);
  assert.equal(healthSummary(null).level, "down");
});

const sseBody = (chunks) => new ReadableStream({ start(c) { const e = new TextEncoder(); for (const x of chunks) c.enqueue(e.encode(x)); c.close(); } });

test("askStream decodes a stream split mid-frame and mid-UTF8", async () => {
  const text = 'event: answer_token\nid: 0\ndata: {"type":"answer_token","text":"é","attempt":1,"seq":0}\n\n: keepalive\n\nevent: run_error\ndata: {"code":"timeout","message":"m"}\n\n';
  const bytes = new TextEncoder().encode(text);
  const cut = text.indexOf("é") + 1; // between the two bytes of "é" in byte terms
  const chunks = new ReadableStream({ start(c) { c.enqueue(bytes.slice(0, cut)); c.enqueue(bytes.slice(cut, cut + 7)); c.enqueue(bytes.slice(cut + 7)); c.close(); } });
  const fetchImpl = async () => new Response(chunks, { status: 200 });
  const got = [];
  for await (const e of askStream("q", [], { fetchImpl })) got.push(e);
  assert.equal(got[0].text, "é");
  assert.equal(got[1].type, "run_error");
});

test("askStream maps 429 busy to ApiError and a friendly message", async () => {
  const fetchImpl = async () => new Response(JSON.stringify({ error: { code: "busy", message: "run active" } }), { status: 429 });
  await assert.rejects(async () => { for await (const _ of askStream("q", [], { fetchImpl })); }, (e) => e instanceof ApiError && e.status === 429);
  assert.equal(friendlyError(new ApiError(429, "busy", "x")).kind, "busy");
  assert.equal(friendlyError(new TypeError("fetch failed")).kind, "error");
});

// Real server: DB_URL=http://127.0.0.1:8765 node --test tests/web_js
const URL_ = process.env.DB_URL;
test("live: real /api/ask stream reduces to a verified answer", { skip: !URL_ }, async () => {
  let s = reduce(initialState(), { type: "run_start", question: "q", now: 0 });
  let n = 0;
  for await (const ev of askStream("What was the speckled band?", [], { base: URL_ })) { s = reduce(s, { type: "event", event: ev, now: ++n }); }
  s = reduce(s, { type: "stream_end", now: n + 1 });
  assert.equal(s.phase, "done");
  assert.equal(s.final.status, "answered");
  assert.equal(s.final.citations[0].anchor.chunk_id, "speckled-band-0001");
  assert.equal(s.answer.text, s.final.answer);
  assert.ok(s.events.every((e) => e.type !== "parse_error"));
  assert.deepEqual(s.events.map((e) => e.seq), s.events.map((_, i) => i));
});

test("live: refusal stream and a second concurrent-safe sequence", { skip: !URL_ }, async () => {
  let s = reduce(initialState(), { type: "run_start", question: "q", now: 0 });
  for await (const ev of askStream("What is the weather in Paris today?", [], { base: URL_ })) s = reduce(s, { type: "event", event: ev, now: 1 });
  assert.equal(s.final.status, "refused");
  assert.equal(s.refusal.code, "no_evidence");
});
