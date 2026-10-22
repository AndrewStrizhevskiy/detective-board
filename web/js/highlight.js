// Pure helpers for quote highlighting and inline citation markers.

// Split `text` into segments using highlight ranges ({rel_start, rel_end, match}).
// Ranges are clamped to the text, sorted, overlaps merged, empty ranges dropped.
// Returns [{text, hl: boolean, match?: string}] whose texts concatenate to `text`.
export function splitHighlights(text, highlights) {
  const n = text.length;
  const ranges = [];
  for (const h of highlights || []) {
    let a = Number(h.rel_start);
    let b = Number(h.rel_end);
    if (!Number.isFinite(a) || !Number.isFinite(b)) continue;
    a = Math.max(0, Math.min(n, a));
    b = Math.max(0, Math.min(n, b));
    if (b > a) ranges.push({ a, b, match: h.match });
  }
  ranges.sort((x, y) => x.a - y.a || x.b - y.b);
  const merged = [];
  for (const r of ranges) {
    const last = merged[merged.length - 1];
    if (last && r.a <= last.b) last.b = Math.max(last.b, r.b);
    else merged.push({ ...r });
  }
  const out = [];
  let pos = 0;
  for (const r of merged) {
    if (r.a > pos) out.push({ text: text.slice(pos, r.a), hl: false });
    out.push({ text: text.slice(r.a, r.b), hl: true, match: r.match });
    pos = r.b;
  }
  if (pos < n) out.push({ text: text.slice(pos), hl: false });
  return out;
}

// Split answer text into plain text and citation markers.
// Handles "[1]", "[1, 2]" and the agent's "[1: \"quote\"]" form. An unfinished marker at the
// end of a streaming text stays plain text until it is closed.
const MARKER = /\[(\d+(?:\s*,\s*\d+)*)(?::\s*"((?:[^"\\]|\\.)*)")?\]/g;

export function parseAnswer(text) {
  const out = [];
  let pos = 0;
  MARKER.lastIndex = 0;
  let m;
  while ((m = MARKER.exec(text)) !== null) {
    if (m.index > pos) out.push({ t: "text", s: text.slice(pos, m.index) });
    out.push({
      t: "cite",
      ns: m[1].split(",").map((x) => Number(x.trim())),
      quote: m[2] === undefined ? null : m[2].replace(/\\(.)/g, "$1"),
      raw: m[0],
    });
    pos = m.index + m[0].length;
  }
  if (pos < text.length) out.push({ t: "text", s: text.slice(pos) });
  return out;
}
