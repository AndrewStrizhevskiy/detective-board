import test from "node:test";
import assert from "node:assert/strict";
import { hashStr, personArt, placeArt, itemArt, exhibitLetter, stringGeom, shadowVector, initialName, storyTitle } from "../../web/js/board-art.js";

test("hash and portrait variants are deterministic", () => {
  assert.equal(hashStr("p:x:james"), hashStr("p:x:james"));
  assert.notEqual(hashStr("p:x:james"), hashStr("p:x:charles"));
  assert.deepEqual(personArt({ id: "p:x:james" }), personArt({ id: "p:x:james" }));
  const hats = new Set(Array.from({ length: 40 }, (_, i) => personArt({ id: `p:${i}` }).hat));
  assert.ok(hats.size >= 3, "the board gets some variety");
});

test("place print follows the words in the name", () => {
  assert.equal(placeArt({ id: "a", name: "Boscombe Pool" }), "water");
  assert.equal(placeArt({ id: "b", name: "Hatherley Farm" }), "house");
  assert.equal(placeArt({ id: "c", name: "Baker Street" }), "street");
  assert.equal(placeArt({ id: "d", name: "the study" }), "room");
  assert.ok(["country", "house", "street"].includes(placeArt({ id: "e", name: "Leatherhead" })));
});

test("exhibit sketch follows the words in the name", () => {
  assert.equal(itemArt({ name: "a gun" }), "gun");
  assert.equal(itemArt({ name: "the speckled band" }), "snake");
  assert.equal(itemArt({ name: "a letter" }), "letter");
  assert.equal(itemArt({ name: "grey cloak" }), "cloth");
  assert.equal(itemArt({ name: "a lamp" }), "tag");
});

test("exhibit letters run A..Z then AA", () => {
  assert.deepEqual([0, 1, 25, 26, 27].map(exhibitLetter), ["A", "B", "Z", "AA", "AB"]);
});

test("a thread sags below the straight line and the offset copy runs parallel", () => {
  const a = { x: 0, y: 100 }, b = { x: 400, y: 100 };
  const g = stringGeom(a, b);
  assert.match(g.d, /^M0 100 Q200 \d+(\.\d)? 400 100$/);
  assert.ok(g.mid.y > 100, "midpoint hangs below the pins");
  assert.equal(g.mid.x, 200);
  assert.equal(g.angle, 0);
  const g2 = stringGeom(a, b, 5);
  assert.equal(g2.mid.y, g.mid.y + 5);
  const steep = stringGeom({ x: 0, y: 0 }, { x: 10, y: 300 });
  assert.ok(steep.mid.x > 5, "a steep thread bows sideways");
});

test("shadows fall away from the lamp and always a little down", () => {
  const lamp = { x: 0, y: 0 };
  const right = shadowVector({ x: 300, y: 0 }, lamp);
  assert.ok(right.x > 0 && right.y > 0);
  const left = shadowVector({ x: -300, y: 0 }, lamp);
  assert.ok(left.x < 0);
  const under = shadowVector({ x: 0, y: 0 }, lamp);
  assert.equal(under.x, 0);
  assert.ok(under.y > 0);
  assert.ok(shadowVector({ x: 3000, y: 0 }, lamp).x <= 5.5, "capped");
});

test("names and story titles", () => {
  assert.equal(initialName("James McCarthy"), "J. McCarthy");
  assert.equal(initialName("Holmes"), "Holmes");
  assert.equal(initialName(""), "");
  assert.equal(storyTitle("boscombe-valley-mystery"), "Boscombe Valley Mystery");
  assert.equal(storyTitle("scandal-in-bohemia"), "Scandal in Bohemia");
  assert.equal(storyTitle(""), "");
});
