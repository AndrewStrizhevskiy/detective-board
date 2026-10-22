import test from "node:test";
import assert from "node:assert/strict";
import { splitHighlights, parseAnswer } from "../../web/js/highlight.js";

const T = "Holmes said the speckled band was a swamp adder.";
const join = (segs) => segs.map((s) => s.text).join("");

test("single range splits into before/hit/after", () => {
  const segs = splitHighlights(T, [{ rel_start: 12, rel_end: 26, match: "exact" }]);
  assert.deepEqual(segs.map((s) => [s.text, s.hl]), [[T.slice(0, 12), false], [T.slice(12, 26), true], [T.slice(26), false]]);
  assert.equal(join(segs), T);
});

test("no highlights returns the whole text", () => {
  assert.deepEqual(splitHighlights(T, []), [{ text: T, hl: false }]);
  assert.deepEqual(splitHighlights(T, undefined), [{ text: T, hl: false }]);
});

test("overlapping and adjacent ranges merge; order does not matter", () => {
  const segs = splitHighlights("0123456789", [{ rel_start: 5, rel_end: 8 }, { rel_start: 2, rel_end: 6 }, { rel_start: 8, rel_end: 9 }]);
  assert.deepEqual(segs.map((s) => [s.text, s.hl]), [["01", false], ["2345678", true], ["9", false]]);
});

test("ranges are clamped; empty, inverted and non-numeric ranges are dropped", () => {
  const segs = splitHighlights("abcdef", [{ rel_start: -5, rel_end: 2 }, { rel_start: 4, rel_end: 99 }, { rel_start: 3, rel_end: 3 }, { rel_start: 5, rel_end: 1 }, { rel_start: "x", rel_end: 2 }]);
  assert.deepEqual(segs.map((s) => [s.text, s.hl]), [["ab", true], ["cd", false], ["ef", true]]);
  assert.equal(join(segs), "abcdef");
});

test("highlight at both ends and full-text range", () => {
  assert.deepEqual(splitHighlights("abc", [{ rel_start: 0, rel_end: 3 }]), [{ text: "abc", hl: true, match: undefined }]);
});

test("empty text with a range is safe", () => {
  assert.deepEqual(splitHighlights("", [{ rel_start: 0, rel_end: 4 }]), []);
});

test("parseAnswer: agent form [1: \"quote\"], plain [2], lists", () => {
  const segs = parseAnswer('The band was a snake. [1: "a deadly snake from India"] Also [2] and [1, 3].');
  assert.deepEqual(segs.map((s) => s.t), ["text", "cite", "text", "cite", "text", "cite", "text"]);
  assert.deepEqual(segs[1].ns, [1]);
  assert.equal(segs[1].quote, "a deadly snake from India");
  assert.deepEqual(segs[5].ns, [1, 3]);
  assert.equal(segs.map((s) => (s.t === "text" ? s.s : s.raw)).join(""), 'The band was a snake. [1: "a deadly snake from India"] Also [2] and [1, 3].');
});

test("parseAnswer: unfinished marker while streaming stays text; escaped quotes", () => {
  assert.deepEqual(parseAnswer('so [1: "a dead'), [{ t: "text", s: 'so [1: "a dead' }]);
  assert.deepEqual(parseAnswer("ends [1"), [{ t: "text", s: "ends [1" }]);
  assert.equal(parseAnswer('x [1: "say \\"hi\\""]')[1].quote, 'say "hi"');
  assert.deepEqual(parseAnswer("array[abc] [x]"), [{ t: "text", s: "array[abc] [x]" }]);
});
