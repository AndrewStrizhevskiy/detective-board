import test from "node:test";
import assert from "node:assert/strict";
import { initialState, reduce, mergeGraph, emptyGraph, citedGraphIds, answerText, waitingStage, progressSteps } from "../../web/js/state.js";

const run = (events, now = 1000) => {
  let s = reduce(initialState(), { type: "run_start", question: "q", now });
  events.forEach((e, i) => { s = reduce(s, { type: "event", event: { seq: i, ...e }, now: now + i }); });
  return s;
};
const tok = (text, attempt = 1) => ({ type: "answer_token", text, attempt });

test("tokens accumulate within an attempt", () => {
  const s = run([tok("The "), tok("band "), tok("is")]);
  assert.equal(s.answer.text, "The band is");
  assert.equal(s.answer.tokens, 3);
  assert.equal(s.answer.discardedAttempts, 0);
});

test("a new attempt drops the tokens of the failed one", () => {
  const s = run([tok("bad "), tok("draft"), tok("good ", 2), tok("one", 2)]);
  assert.equal(s.answer.text, "good one");
  assert.equal(s.answer.attempt, 2);
  assert.equal(s.answer.discardedTokens, 2);
  assert.equal(s.answer.discardedAttempts, 1);
});

test("straggler tokens of an older attempt are ignored", () => {
  const s = run([tok("a", 1), tok("b", 2), tok("late", 1)]);
  assert.equal(s.answer.text, "b");
});

test("three attempts: only the last survives, counts add up", () => {
  const s = run([tok("1"), tok("1"), tok("2", 2), tok("3", 3), tok("3", 3)]);
  assert.equal(s.answer.text, "33");
  assert.equal(s.answer.discardedTokens, 3);
  assert.equal(s.answer.discardedAttempts, 2);
});

test("final replaces the draft and ends the run; later events are ignored", () => {
  const s = run([tok("draft"), { type: "final", status: "answered", verified: true, answer: "FINAL", citations: [], provenance: [] }, tok("late")]);
  assert.equal(s.phase, "done");
  assert.equal(answerText(s), "FINAL");
  assert.equal(s.answer.text, "draft");
});

test("duplicate seq is ignored", () => {
  let s = reduce(initialState(), { type: "run_start", question: "q", now: 0 });
  const ev = { type: "answer_token", text: "x", attempt: 1, seq: 0 };
  s = reduce(s, { type: "event", event: ev, now: 1 });
  s = reduce(s, { type: "event", event: ev, now: 2 });
  assert.equal(s.answer.text, "x");
});

test("run_error is terminal and keeps earlier trace events", () => {
  const s = run([{ type: "route_decided", routes: ["vector"], method: "rules", reason: "r" }, { type: "run_error", code: "timeout", message: "slow" }]);
  assert.equal(s.phase, "error");
  assert.equal(s.error.code, "timeout");
  assert.equal(s.events.length, 2);
  assert.equal(s.route.routes[0], "vector");
});

test("stream ending without final or run_error is a lost connection", () => {
  const s = reduce(run([tok("x")]), { type: "stream_end", now: 5 });
  assert.equal(s.phase, "error");
  assert.equal(s.error.code, "connection_lost");
  assert.equal(reduce(run([{ type: "final", status: "refused", verified: true, answer: "", citations: [], provenance: [] }]), { type: "stream_end" }).phase, "done");
});

test("cancel only applies to a running run", () => {
  assert.equal(reduce(run([tok("x")]), { type: "cancel" }).phase, "cancelled");
  assert.equal(reduce(initialState(), { type: "cancel" }).phase, "idle");
});

test("graph events add nodes and edges incrementally and merge duplicates", () => {
  const s = run([
    { type: "graph_results", nodes: [{ id: "a", kind: "person", name: "A" }], edges: [] },
    { type: "graph_results", nodes: [{ id: "a", kind: "person", name: "A", confidence: "high" }, { id: "b", kind: "place", name: "B" }], edges: [{ id: 1, rel: "R", src: "a", dst: "b" }] },
  ]);
  assert.deepEqual(s.graph.nodeOrder, ["a", "b"]);
  assert.equal(s.graph.nodes.a.confidence, "high");
  assert.equal(s.graph.edges["1"].dst, "b");
  assert.deepEqual(s.graph.edgeOrder, ["1"]);
});

test("run_start clears the graph unless keepGraph", () => {
  const s = run([{ type: "graph_results", nodes: [{ id: "a", kind: "person", name: "A" }], edges: [] }]);
  assert.equal(reduce(s, { type: "run_start", question: "q2" }).graph.nodeOrder.length, 0);
  assert.equal(reduce(s, { type: "run_start", question: "q2", keepGraph: true }).graph.nodeOrder.length, 1);
});

test("graph_merge works outside a run and keeps richer anchors", () => {
  const g1 = mergeGraph(emptyGraph(), [{ id: "a", kind: "person", name: "A", anchors: [1, 2] }]);
  const g2 = mergeGraph(g1, [{ id: "a", kind: "person", name: "A", anchors: [1] }]);
  assert.equal(g2.nodes.a.anchors.length, 2);
});

test("cited graph elements are found by anchor overlap", () => {
  const anchor = { chunk_id: "c1", char_start: 10, char_end: 30 };
  const g = mergeGraph(emptyGraph(), [{ id: "a", kind: "person", name: "A" }, { id: "b", kind: "person", name: "B" }, { id: "c", kind: "person", name: "C", anchors: [{ chunk_id: "c2", char_start: 0, char_end: 5 }] }],
    [{ id: 1, rel: "R", src: "a", dst: "b", anchor: { chunk_id: "c1", char_start: 20, char_end: 40 } }, { id: 2, rel: "R", src: "b", dst: "c", anchor: { chunk_id: "c1", char_start: 30, char_end: 40 } }]);
  const c = citedGraphIds(g, [{ n: 1, anchor }]);
  assert.deepEqual([...c.edges], ["1"]);
  assert.deepEqual([...c.nodes].sort(), ["a", "b"]);
  assert.equal(citedGraphIds(g, []).nodes.size, 0);
});

test("tool_result keeps provenance and an explanation when the event has one", () => {
  const s = run([{ type: "tool_result", tool: "check_alibi", ok: true, summary: "s", provenance: "conditional", explanation: { rule_id: "R1" } }]);
  assert.equal(s.findings[0].explanation.rule_id, "R1");
});

test("waiting stage: working, first token, writing", () => {
  let s = reduce(initialState(), { type: "run_start", question: "q", now: 0 });
  assert.equal(waitingStage(s, 4000).kind, "working");
  s = reduce(s, { type: "event", event: { seq: 0, type: "enriched_query", sources: [] }, now: 1000 });
  assert.deepEqual(waitingStage(s, 13000), { kind: "first_token", seconds: 12 });
  s = reduce(s, { type: "event", event: { seq: 1, type: "answer_token", text: "x" }, now: 14000 });
  assert.equal(waitingStage(s, 16000).kind, "writing");
  assert.equal(waitingStage(initialState(), 0), null);
});

test("rule-first run (no model call): tokens stream from the template and every step ends done", () => {
  const s = run([
    { type: "route_decided", routes: ["mcp", "graph", "vector"], tools: ["find_contradictions"], method: "rules", reason: "r" },
    { type: "retrieval_results", hits: [], gate: { passed: true }, chunk_ids: [] },
    { type: "graph_results", nodes: [], edges: [] },
    { type: "tool_result", tool: "find_contradictions", ok: true, summary: "status=ok items=0" },
    { type: "enriched_query", sources: [], prompt_chars: 0, prompt_tokens_estimate: 0, strategy: "rule-first (empty): no model call" },
    tok("The rule engine found no violation "), tok("among the facts."),
    { type: "citation_check", ok: true, citations: [], action: "accept" },
    { type: "final", status: "answered", verified: true, answer: "The rule engine found no violation among the facts.", citations: [], provenance: [] },
  ]);
  assert.equal(s.phase, "done");
  assert.equal(answerText(s), "The rule engine found no violation among the facts.");
  const steps = progressSteps(s, 5000);
  assert.ok(steps.every((x) => x.status === "done" || x.status === "skipped"));
});
