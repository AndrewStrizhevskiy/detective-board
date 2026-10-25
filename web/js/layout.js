// Deterministic incremental board layout: nodes that are already placed never move.
// positions: {id: {x, y}}; newIds: ids to place, in arrival order; edges: [{src, dst, rel}];
// kinds: {id: kind}. Returns {id: {x, y}} for the newly placed ids only.
//
// Each batch runs a small force simulation (repulsion, spring along edges, weak gravity) where
// only the new nodes move, then a rectangle-collision pass so cards never overlap. No random
// numbers: the same evidence always gives the same picture (a demo needs that).

// Card sizes in board px (width, height). graph.js sizes the cards from the same table.
export const BOX = {
  person: [136, 228], // cabinet portrait
  place: [180, 198],  // landscape print
  item: [156, 152],   // exhibit tag
  event: [196, 172],  // newspaper clipping
  claim: [214, 150],  // index card
  source: [176, 124], // torn book page
};
const GAP = 16; // free space kept between two cards
const SCALE = 1.8; // forces and start radii were tuned for cards this much smaller
const dims = (kinds, id) => BOX[kinds[id]] || BOX.person;

function neighboursOf(id, edges) {
  const out = [];
  for (const e of edges) {
    if (e.src === id) out.push(e.dst);
    else if (e.dst === id) out.push(e.src);
  }
  return out;
}

// Ideal spring length between two cards: claims sit close to their speaker like a note on a card.
function idealLength(a, b, e, kinds) {
  const [wa, ha] = dims(kinds, a);
  const [wb, hb] = dims(kinds, b);
  const base = Math.hypot((wa + wb) / 2, (ha + hb) / 2) * 0.62;
  // (tuned so ~12 cards fit a 1100 px board at about 0.75 zoom)
  if (e.rel === "ASSERTS") return base * 0.9;
  if (/CONTRADICT|CONFLICT/.test(e.rel)) return base * 1.9; // room for the DERIVED stamp on the string
  if (e.rel === "ABOUT") return base * 1.7;
  return base * 1.35;
}

function overlapAmount(pa, ba, pb, bb) {
  const dx = pb.x - pa.x;
  const dy = pb.y - pa.y;
  const ox = (ba[0] + bb[0]) / 2 + GAP - Math.abs(dx);
  const oy = (ba[1] + bb[1]) / 2 + GAP - Math.abs(dy);
  return { dx, dy, ox, oy, hit: ox > 0 && oy > 0 };
}

export function placeNew(positions, newIds, edges, kinds = {}) {
  const pos = {};
  for (const id in positions) pos[id] = { ...positions[id] };
  const free = newIds.filter((id) => !pos[id]);
  if (!free.length) return {};
  const freeSet = new Set(free);
  const fixedCount = Object.keys(pos).length;

  // initial positions: next to an already placed neighbour, else on a golden-angle spiral
  free.forEach((id, i) => {
    const nb = neighboursOf(id, edges).find((o) => pos[o] && !freeSet.has(o));
    const a = (i + 1) * 2.399963;
    if (nb) {
      const r = (150 + 18 * (i % 3)) * SCALE;
      pos[id] = { x: pos[nb].x + r * Math.cos(a), y: pos[nb].y + r * Math.sin(a) };
    } else {
      const r = fixedCount === 0 && i === 0 ? 0 : (120 + 62 * Math.sqrt(i)) * SCALE;
      pos[id] = { x: r * Math.cos(a) * 1.25, y: r * Math.sin(a) };
    }
  });

  const live = edges.filter((e) => pos[e.src] && pos[e.dst] && (freeSet.has(e.src) || freeSet.has(e.dst)));
  const ids = Object.keys(pos);
  const ITER = 260;
  for (let it = 0; it < ITER; it++) {
    const cool = 1 - it / ITER;
    const force = {};
    for (const id of free) force[id] = { x: 0, y: 0 };
    // repulsion between every pair where at least one side is free
    for (let i = 0; i < ids.length; i++) {
      for (let j = i + 1; j < ids.length; j++) {
        const a = ids[i], b = ids[j];
        if (!freeSet.has(a) && !freeSet.has(b)) continue;
        let dx = pos[a].x - pos[b].x;
        let dy = pos[a].y - pos[b].y;
        let d = Math.hypot(dx, dy);
        if (d < 1) { dx = ((i * 7 + j) % 5) - 2 || 1; dy = ((i + j * 3) % 5) - 2; d = Math.hypot(dx, dy); }
        const f = (26000 * SCALE * SCALE) / (d * d);
        const fx = (dx / d) * f, fy = (dy / d) * f;
        if (freeSet.has(a)) { force[a].x += fx; force[a].y += fy; }
        if (freeSet.has(b)) { force[b].x -= fx; force[b].y -= fy; }
      }
    }
    // springs along edges
    for (const e of live) {
      const dx = pos[e.dst].x - pos[e.src].x;
      const dy = pos[e.dst].y - pos[e.src].y;
      const d = Math.max(1, Math.hypot(dx, dy));
      const f = 0.09 * (d - idealLength(e.src, e.dst, e, kinds));
      const fx = (dx / d) * f, fy = (dy / d) * f;
      if (freeSet.has(e.src)) { force[e.src].x += fx; force[e.src].y += fy; }
      if (freeSet.has(e.dst)) { force[e.dst].x -= fx; force[e.dst].y -= fy; }
    }
    // weak gravity keeps disconnected pieces in the picture (only for the first batch: a later
    // batch is anchored by its placed neighbours)
    for (const id of free) {
      const g = fixedCount === 0 ? 0.03 : 0.004;
      force[id].x -= pos[id].x * g;
      force[id].y -= pos[id].y * g;
    }
    for (const id of free) {
      const m = Math.hypot(force[id].x, force[id].y);
      const cap = (28 * cool + 1.5) * SCALE;
      const s = m > cap ? cap / m : 1;
      pos[id].x += force[id].x * s;
      pos[id].y += force[id].y * s;
    }
  }

  // no overlaps: push apart along the axis of least penetration; fixed cards never move
  for (let pass = 0; pass < 200; pass++) {
    let moved = false;
    for (let i = 0; i < ids.length; i++) {
      for (let j = i + 1; j < ids.length; j++) {
        const a = ids[i], b = ids[j];
        const fa = freeSet.has(a), fb = freeSet.has(b);
        if (!fa && !fb) continue;
        const o = overlapAmount(pos[a], dims(kinds, a), pos[b], dims(kinds, b));
        if (!o.hit) continue;
        moved = true;
        const alongX = o.ox < o.oy;
        const sign = (alongX ? o.dx : o.dy) >= 0 ? 1 : -1;
        const amount = (alongX ? o.ox : o.oy) + 0.5;
        const share = fa && fb ? 0.5 : 1;
        if (fa) { if (alongX) pos[a].x -= sign * amount * share; else pos[a].y -= sign * amount * share; }
        if (fb) { if (alongX) pos[b].x += sign * amount * share; else pos[b].y += sign * amount * share; }
      }
    }
    if (!moved) break;
  }

  // pockets between placed cards can trap a node; move any that still overlap to the nearest free spot
  const clash = (id, p) => ids.some((o) => o !== id && overlapAmount(p, dims(kinds, id), pos[o], dims(kinds, o)).hit);
  for (const id of free) {
    if (!clash(id, pos[id])) continue;
    const home = { ...pos[id] };
    let found = null;
    for (let r = 20; r < 1400 && !found; r += 20) {
      for (let k = 0; k < 24 && !found; k++) {
        const a = (k / 24) * Math.PI * 2;
        const p = { x: home.x + r * Math.cos(a), y: home.y + r * Math.sin(a) };
        if (!clash(id, p)) found = p;
      }
    }
    if (found) pos[id] = found;
  }

  // first batch: the first card is the origin (the view is fitted to the bounding box anyway)
  if (fixedCount === 0) {
    const ox = pos[free[0]].x, oy = pos[free[0]].y;
    for (const id of free) { pos[id].x -= ox; pos[id].y -= oy; }
  }

  const added = {};
  for (const id of free) added[id] = { x: Math.round(pos[id].x), y: Math.round(pos[id].y) };
  return added;
}

// Bounding box of cards (graph units) for fitting the view before every node is on screen.
export function boundsOf(positions, kinds = {}) {
  let x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity;
  for (const id in positions) {
    const [w, h] = dims(kinds, id);
    x0 = Math.min(x0, positions[id].x - w / 2); x1 = Math.max(x1, positions[id].x + w / 2);
    y0 = Math.min(y0, positions[id].y - h / 2); y1 = Math.max(y1, positions[id].y + h / 2);
  }
  return Number.isFinite(x0) ? { x0, x1, y0, y1, w: x1 - x0, h: y1 - y0 } : null;
}
