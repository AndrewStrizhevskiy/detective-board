import test from "node:test";
import assert from "node:assert/strict";
import { SseParser, decodeMessage } from "../../web/js/sse.js";

const frame = (event, id, data) => `event: ${event}\nid: ${id}\ndata: ${data}\n\n`;

test("parses a complete frame", () => {
  const p = new SseParser();
  const out = p.push(frame("route_decided", 0, '{"a":1}'));
  assert.deepEqual(out, [{ event: "route_decided", data: '{"a":1}', id: "0" }]);
});

test("frame split at every byte position gives the same result", () => {
  const text = frame("a", 1, '{"x":"é"}') + ": keepalive\n\n" + frame("b", 2, '{"y":2}');
  const whole = new SseParser().push(text);
  assert.equal(whole.length, 2);
  for (let i = 1; i < text.length; i++) {
    const p = new SseParser();
    const got = [...p.push(text.slice(0, i)), ...p.push(text.slice(i))];
    assert.deepEqual(got, whole, `split at ${i}`);
  }
});

test("CRLF, bare CR, and CR+LF split across chunks", () => {
  const p = new SseParser();
  assert.equal(p.push("event: x\r\ndata: 1\r\n\r\n").length, 1);
  assert.equal(p.push("event: y\rdata: 2\r\r").length, 1);
  const q = new SseParser();
  assert.deepEqual([...q.push("data: 3\r"), ...q.push("\n\r"), ...q.push("\n")].map((m) => m.data), ["3"]);
});

test("comments and keepalives are ignored, multi-line data joined, BOM stripped", () => {
  const p = new SseParser();
  const out = p.push("﻿: keepalive\n\nevent: m\ndata: a\ndata: b\n\n");
  assert.deepEqual(out, [{ event: "m", data: "a\nb", id: "" }]);
});

test("blank data does not dispatch; default event name is message; id persists", () => {
  const p = new SseParser();
  assert.equal(p.push("event: x\n\n").length, 0);
  const a = p.push("id: 7\ndata: z\n\n");
  assert.equal(a[0].event, "message");
  assert.equal(a[0].id, "7");
  assert.equal(p.push("data: q\n\n")[0].id, "7");
});

test("incomplete tail is not emitted", () => {
  const p = new SseParser();
  assert.equal(p.push('event: a\ndata: {"x":').length, 0);
});

test("decodeMessage: JSON, type fallback, bad JSON", () => {
  assert.equal(decodeMessage({ event: "final", data: '{"type":"final","status":"answered"}' }).status, "answered");
  assert.equal(decodeMessage({ event: "run_error", data: '{"code":"timeout","message":"m"}' }).type, "run_error");
  const bad = decodeMessage({ event: "x", data: "{nope" });
  assert.equal(bad.type, "parse_error");
  assert.equal(decodeMessage({ event: "x", data: "[1]" }).type, "parse_error");
});
