// Pure helpers for the investigation board (no DOM): which picture a card gets, how a thread
// sags between two pins, and which way shadows fall from the desk lamp. Everything here is
// deterministic, so the same evidence always gives the same board.

// Stable 32-bit FNV-1a hash of a string.
export function hashStr(s) {
  let h = 0x811c9dc5;
  for (const ch of String(s)) {
    h ^= ch.codePointAt(0);
    h = Math.imul(h, 0x01000193) >>> 0;
  }
  return h >>> 0;
}

const has = (text, words) => words.some((w) => new RegExp(`\\b${w}`, "i").test(text));

// A period cabinet portrait. The corpus says nothing about looks, so the variant only comes from
// the id: it gives the board variety without pretending to know the person.
export function personArt(node) {
  const h = hashStr(node.id);
  return { hat: ["none", "bowler", "cap", "top", "none"][h % 5], beard: (h >> 3) % 3 === 0 };
}

// A landscape print chosen from words in the place name.
export function placeArt(node) {
  const t = `${node.name || ""} ${node.label || ""}`;
  if (has(t, ["pool", "lake", "river", "pond", "mere", "sea", "water", "brook", "reach"])) return "water";
  if (has(t, ["street", "road", "lane", "square", "station", "london", "city", "bridge", "inn"])) return "street";
  if (has(t, ["room", "study", "chamber", "bedroom", "office", "hall ", "parlour", "library", "cellar"])) return "room";
  if (has(t, ["farm", "house", "lodge", "manor", "cottage", "grange", "hall", "court", "villa", "place"])) return "house";
  return ["country", "house", "street"][hashStr(node.id) % 3];
}

// An exhibit sketch chosen from words in the item name.
export function itemArt(node) {
  const t = `${node.name || ""} ${node.label || ""}`;
  if (has(t, ["gun", "revolver", "pistol", "rifle", "shotgun"])) return "gun";
  if (has(t, ["letter", "note", "paper", "telegram", "document", "message", "card"])) return "letter";
  if (has(t, ["snake", "adder", "band", "serpent"])) return "snake";
  if (has(t, ["key", "lock"])) return "key";
  if (has(t, ["coat", "cloak", "plaid", "cloth", "hat", "boot", "shoe", "glove"])) return "cloth";
  return "tag";
}

// Exhibit letters in arrival order: A, B, ... Z, AA, AB ...
export function exhibitLetter(i) {
  let s = "";
  let n = i;
  do { s = String.fromCharCode(65 + (n % 26)) + s; n = Math.floor(n / 26) - 1; } while (n >= 0);
  return s;
}

// A thread between two pins: a quadratic curve that sags with its horizontal span (a taut thread
// hangs less when it runs steeply). offset shifts the whole curve down, for the second line of a
// rule-derived double string. Returns the path, its midpoint and the tangent angle there.
export function stringGeom(a, b, offset = 0) {
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  const len = Math.hypot(dx, dy) || 1;
  const sag = 0.06 * Math.abs(dx) + 6;
  // a steep thread bows sideways a little instead of straight down
  const side = Math.abs(dx) < 60 ? 14 : 0;
  const c = { x: (a.x + b.x) / 2 + side, y: (a.y + b.y) / 2 + sag };
  const o = offset;
  const mid = { x: (a.x + 2 * c.x + b.x) / 4, y: (a.y + 2 * c.y + b.y) / 4 + o };
  const tx = b.x - a.x; // tangent of a quadratic at t = 0.5 is parallel to b - a
  const ty = b.y - a.y;
  const r = (n) => Math.round(n * 10) / 10;
  return {
    d: `M${r(a.x)} ${r(a.y + o)} Q${r(c.x)} ${r(c.y + o)} ${r(b.x)} ${r(b.y + o)}`,
    mid: { x: r(mid.x), y: r(mid.y) },
    angle: r((Math.atan2(ty, tx) * 180) / Math.PI),
    len: r(len),
  };
}

// Shadow vector for an object at pt under a lamp at lamp (both in board units): it points away
// from the lamp and grows with the distance, with a constant downward part (the lamp is above).
export function shadowVector(pt, lamp, depth = 1) {
  const dx = pt.x - lamp.x;
  const dy = pt.y - lamp.y;
  const d = Math.hypot(dx, dy) || 1;
  const m = Math.max(1.5, Math.min(5.5, d / 90));
  const r = (n) => Math.round(n * 10) / 10;
  return { x: r((dx / d) * m * depth), y: r(((dy / d) * m + 1.5) * depth) };
}

// Short readable speaker name: "James McCarthy" -> "J. McCarthy".
export function initialName(name) {
  const p = String(name || "").trim().split(/\s+/).filter(Boolean);
  return p.length > 1 ? `${p[0][0]}. ${p[p.length - 1]}` : p[0] || "";
}

// Story slug to a title-cased name: "scandal-in-bohemia" -> "Scandal in Bohemia". No article is
// added: the slug does not say whether the real title starts with "The" or "A".
const SMALL = new Set(["a", "an", "and", "in", "of", "the", "with", "at", "on"]);
export function storyTitle(slug) {
  const words = String(slug || "").split("-").filter(Boolean);
  return words.map((w, i) => (i > 0 && SMALL.has(w) ? w : w[0].toUpperCase() + w.slice(1))).join(" ");
}
