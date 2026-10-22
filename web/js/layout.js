// Deterministic incremental placement: nodes that are already placed never move.
// positions: {id: {x, y}}; newIds: ids to place in order; edges: [{src, dst}].
const R = 150;
const MIN_DIST = 105;

function minDist(p, positions) {
  let d = Infinity;
  for (const id in positions) d = Math.min(d, Math.hypot(positions[id].x - p.x, positions[id].y - p.y));
  return d;
}

export function placeNew(positions, newIds, edges) {
  const pos = { ...positions };
  const added = {};
  for (const id of newIds) {
    if (pos[id]) continue;
    const nb = edges
      .map((e) => (e.src === id ? e.dst : e.dst === id ? e.src : null))
      .find((o) => o && pos[o]);
    let best = null;
    if (nb) {
      const c = pos[nb];
      let bestD = -1;
      for (let k = 0; k < 16; k++) {
        const a = (k / 16) * Math.PI * 2;
        const p = { x: c.x + R * Math.cos(a), y: c.y + R * Math.sin(a) };
        const d = minDist(p, pos);
        if (d > bestD + 1e-9) { bestD = d; best = p; }
      }
    } else if (Object.keys(pos).length === 0) {
      best = { x: 0, y: 0 };
    } else {
      for (let k = 1; k < 400 && !best; k++) { // spiral outwards from the centre
        const a = k * 2.399963, r = 70 * Math.sqrt(k);
        const p = { x: r * Math.cos(a), y: r * Math.sin(a) };
        if (minDist(p, pos) >= MIN_DIST) best = p;
      }
      best = best || { x: 0, y: 0 };
    }
    pos[id] = best;
    added[id] = best;
  }
  return added;
}
