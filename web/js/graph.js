// Cytoscape wrapper: the investigation board. Evidence cards pinned on a board, strings between
// them. Elements are revealed one by one in arrival order; placed cards never move (layout.js).
import cytoscape from "../vendor/cytoscape.esm.min.mjs";
import { placeNew, boundsOf, BOX } from "./layout.js";

// Shape carries the entity type together with the icon and the colour (never colour alone).
export const KIND_SHAPE = { person: "ellipse", place: "round-rectangle", item: "diamond", event: "hexagon", claim: "round-tag", source: "rectangle" };
export const KIND_GLYPH = { person: "P", place: "L", item: "I", event: "E", claim: "C", source: "S" };
export const KIND_WORD = { person: "Person", place: "Place", item: "Item", event: "Event", claim: "Claim", source: "Source text" };

const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
export const isDerived = (e) => e.provenance === "derived" || e.provenance === "conditional";

export function edgeSemantics(e) {
  const t = `${e.rel || ""} ${(e.props && (e.props.verdict || e.props.status)) || ""}`.toLowerCase();
  if (/contradict|conflict|violat/.test(t)) return "conflict";
  if (/support|consistent/.test(t)) return "support";
  if (/unknown|insufficient/.test(t)) return "unknown";
  return "relation";
}

export function ruleOf(e) {
  const x = e.explanation || (e.props && e.props.explanation);
  return (x && x.rule_id) || (e.props && e.props.rule) || "";
}

const REL_WORD = { PARTICIPATED_IN: "took part in", OCCURRED_AT: "happened at", ASSERTS: "says", ABOUT: "about", RELATION: "", CONTRADICTS: "contradicts" };
export function edgeLabel(e) {
  const sem = edgeSemantics(e);
  const word = e.props && e.props.predicate ? e.props.predicate : REL_WORD[e.rel] ?? String(e.rel || "").toLowerCase().replace(/_/g, " ");
  if (isDerived(e)) {
    const r = ruleOf(e);
    return `${e.provenance === "conditional" ? "=? CONDITIONAL" : "= DERIVED"}${r ? " " + r : ""}${sem === "conflict" ? " · CONFLICTS" : word ? " · " + word : ""}`;
  }
  return sem === "conflict" ? `! CONFLICTS${word ? " · " + word : ""}` : word;
}

const MAXCH = { person: 26, place: 30, item: 20, event: 70, claim: 54, source: 26 };
function clip(s, n) { s = String(s || ""); return s.length > n ? s.slice(0, n - 1).trimEnd() + "…" : s; }
const initial = (name) => { const p = String(name || "").trim().split(/\s+/); return p.length > 1 ? `${p[0][0]}. ${p[p.length - 1]}` : p[0] || ""; };

export function nodeLabel(n, graph) {
  let text = clip(n.name || n.label || n.id, MAXCH[n.kind] || 30);
  if (n.kind === "claim") {
    const eid = graph.edgeOrder.find((id) => graph.edges[id].rel === "ASSERTS" && graph.edges[id].dst === n.id);
    const sp = eid && graph.nodes[graph.edges[eid].src];
    if (sp) text = `${initial(sp.name)}: ${clip(n.name || n.label || "", MAXCH.claim - 14)}`;
  }
  if (n.kind === "source" && n.sub) text = `${text}\n${n.sub}`;
  return n.confidence === "low" ? `${text}\n(tentative)` : text;
}

function motionMs() {
  const d = parseFloat(css("--db-dur-node"));
  return Number.isFinite(d) ? d : 0;
}

// ---- card decoration: pin (or tape for claims) and the type icon, drawn as an SVG background
const ICON = {
  person: '<circle cx="12" cy="8" r="4"/><path d="M4 21c0-5 4-8 8-8s8 3 8 8"/>',
  place: '<path d="M12 22s7-7 7-12a7 7 0 1 0-14 0c0 5 7 12 7 12z"/><circle cx="12" cy="10" r="2.5"/>',
  item: '<circle cx="8" cy="15" r="4"/><path d="M11 12l9-9M16 7l3 3M14 9l2 2"/>',
  event: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3.5 2"/>',
  claim: '<path d="M4 6h16v10h-8l-5 4v-4H4z"/>',
  source: '<path d="M6 3h9l4 4v14H6zM14 3v5h5M9 12h7M9 16h7"/>',
};

function decoration(kind, fg, pin) {
  const [w, h] = BOX[kind];
  const icon = `<g transform="translate(${kind === "claim" ? 6 : w / 2 - 9},${kind === "claim" ? 4 : 13}) scale(.75)" fill="${kind === "claim" ? fg : "none"}" fill-opacity=".25" stroke="${fg}" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">${ICON[kind]}</g>`;
  const pinSvg = kind === "claim"
    ? `<rect x="${w - 46}" y="-5" width="34" height="11" rx="1.5" transform="rotate(4 ${w - 29} 0)" fill="${pin}" fill-opacity=".55" stroke="${pin}" stroke-width="1"/>`
    : `<circle cx="${w / 2}" cy="3" r="6.5" fill="${pin}" stroke="${css("--db-text")}" stroke-width="1.4"/><circle cx="${w / 2 - 2}" cy="1" r="1.8" fill="#fff" fill-opacity=".75"/>`;
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}">${icon}${pinSvg}</svg>`;
  return "data:image/svg+xml;utf8," + encodeURIComponent(svg);
}

function styleSheet() {
  const bg = css("--db-bg-board");
  const ink = css("--db-text");
  const paper = css("--db-bg-surface");
  const halo = css("--db-halo");
  const pin = css("--db-pin");
  const s = [
    { selector: "node", style: { label: "data(label)", "text-valign": "center", "text-halign": "center", "text-wrap": "wrap", "text-max-width": 112, "line-height": 1.15, "font-size": 13, "font-weight": 600, "font-family": css("--db-font-ui"), color: css("--db-text-on-fill"), "text-margin-y": 8, width: 150, height: 78, "border-width": 2.5, "background-opacity": 1, "min-zoomed-font-size": 0, "background-fit": "none", "background-clip": "none", "background-image-containment": "over", "background-position-x": "50%", "background-position-y": "50%", "bounds-expansion": 10, "z-index-compare": "manual", "z-index": 5 } },
    { selector: "node[?seed]", style: { "border-width": 5, "border-style": "double" } },
    { selector: "node.tentative", style: { "border-style": "dashed", "border-width": 3, "background-opacity": 0.78 } },
    { selector: "node.cited", style: { "border-width": 4.5, "underlay-color": halo, "underlay-opacity": 0.55, "underlay-padding": 5, "underlay-shape": "round-rectangle" } },
    { selector: "node.fresh", style: { "overlay-color": css("--db-focus"), "overlay-opacity": 0.22, "overlay-padding": 10 } },
    { selector: "node.sel", style: { "border-color": css("--db-selected-ring"), "border-width": 5.5, "outline-width": 3, "outline-color": css("--db-focus"), "outline-offset": 2, "outline-opacity": 1 } },
    { selector: "node.dim", style: { opacity: 0.38 } },
    // strings: a slight sag so they read as thread, not as graph-theory lines
    { selector: "edge", style: { width: 2, "line-color": css("--db-edge"), "target-arrow-color": css("--db-edge"), "target-arrow-shape": "triangle", "curve-style": "unbundled-bezier", "control-point-distances": [11], "control-point-weights": [0.5], label: "", "font-size": 11, "font-weight": 700, "font-family": css("--db-font-ui"), color: css("--db-text"), "text-background-color": bg, "text-background-opacity": 0.92, "text-background-padding": 3, "text-background-shape": "roundrectangle", "text-rotation": "none", "arrow-scale": 1.1, "z-index-compare": "manual", "z-index": 2 } },
    { selector: "edge.rel-asserts", style: { width: 1.5, "target-arrow-shape": "none", "control-point-distances": [0], "z-index": 1 } },
    { selector: "edge.rel-about", style: { width: 1.2, "line-style": "dotted", opacity: 0.7, "arrow-scale": 0.8 } },
    { selector: "edge.lowconf", style: { "line-style": "dashed", opacity: 0.85 } },
    { selector: "edge.showlabel", style: { label: "data(label)" } },
    { selector: "edge.support", style: { "line-color": css("--db-edge-support"), "target-arrow-color": css("--db-edge-support") } },
    { selector: "edge.conflict", style: { "line-color": css("--db-edge-conflict"), "target-arrow-color": css("--db-edge-conflict"), width: 3.2, "z-index": 40 } },
    { selector: "edge.unknown", style: { "line-color": css("--db-edge-unknown"), "line-style": "dotted", "target-arrow-color": css("--db-edge-unknown") } },
    { selector: "edge.conflict.showlabel", style: { color: paper, "text-background-color": css("--db-edge-conflict"), "text-background-opacity": 1 } },
    // derived/conditional: a double line (a wide stroke with a board-coloured core drawn on top) and an ink stamp
    { selector: "edge.derived", style: { width: 8, "z-index": 50 } },
    { selector: "edge.derived.conflict", style: { width: 9 } },
    { selector: "edge.derived.showlabel", style: { color: paper, "text-background-color": ink, "text-background-opacity": 1, "text-background-padding": 4 } },
    { selector: "edge.conditional", style: { "line-style": "dashed" } },
    { selector: "edge.inner", style: { width: 3, "line-color": bg, "target-arrow-shape": "none", "line-style": "solid", events: "no", label: "", "z-index": 51 } },
    { selector: "edge.inner.cond", style: { "line-style": "dashed" } },
    { selector: "edge.cited", style: { "underlay-color": halo, "underlay-opacity": 0.5, "underlay-padding": 3 } },
    { selector: "edge.sel", style: { "overlay-color": css("--db-focus"), "overlay-opacity": 0.28, "overlay-padding": 6 } },
    { selector: "edge.dim", style: { opacity: 0.25 } },
  ];
  for (const k of Object.keys(KIND_SHAPE)) {
    const [w, h] = BOX[k];
    const textW = { person: 104, place: 124, item: 74, event: 144, claim: 130, source: 124 }[k];
    const fg = css(`--db-${k === "source" ? "text-muted" : k + "-fg"}`);
    const fill = k === "source" ? css("--db-bg-surface") : css(`--db-${k}-fill`);
    s.push({ selector: `node[kind = '${k}']`, style: { shape: KIND_SHAPE[k], width: w, height: h, "text-max-width": textW, "border-color": fg, "background-color": fill, "background-image": decoration(k, fg, pin), "text-margin-y": k === "claim" ? 5 : k === "item" ? 9 : 8, "font-size": k === "claim" || k === "event" ? 13 : 14, "font-weight": k === "claim" ? 500 : 600 } });
  }
  return s;
}

export function createGraph(container, { onSelect, onDoubleSelect } = {}) {
  const cy = cytoscape({ container, elements: [], style: styleSheet(), minZoom: 0.2, maxZoom: 2.5, wheelSensitivity: 0.3, boxSelectionEnabled: false, autoungrabify: false });
  const positions = {};
  const kinds = {};
  let selected = null;
  let order = [];
  let latest = null;
  let seedNow = new Set();
  let cited = { nodes: new Set(), edges: new Set() };
  let queue = [];
  let timer = null;
  const timers = new Set();

  cy.on("tap", "node", (ev) => onSelect && onSelect({ kind: "node", id: ev.target.id() }));
  cy.on("tap", "edge.real", (ev) => onSelect && onSelect({ kind: "edge", id: ev.target.id() }));
  cy.on("dbltap", "node", (ev) => onDoubleSelect && onDoubleSelect({ kind: "node", id: ev.target.id() }));
  cy.on("tap", (ev) => { if (ev.target === cy && onSelect) onSelect(null); });
  cy.on("mouseover", "edge.real", (ev) => ev.target.addClass("showlabel"));
  cy.on("mouseout", "edge.real", (ev) => { if (!ev.target.hasClass("keeplabel")) ev.target.removeClass("showlabel"); });
  cy.on("dragfree", "node", (ev) => { positions[ev.target.id()] = { ...ev.target.position() }; });

  const later = (fn, ms) => { const t = setTimeout(() => { timers.delete(t); fn(); }, ms); timers.add(t); };

  function addNode(id, animate) {
    const n = latest.nodes[id];
    if (!n || cy.getElementById(id).length) return;
    const p = positions[id];
    const ele = cy.add({ group: "nodes", classes: n.confidence === "low" ? "tentative" : "", data: { id, kind: n.kind, label: nodeLabel(n, latest), conf: n.confidence || "", seed: seedNow.has(id) }, position: animate ? { x: p.x, y: p.y - 26 } : p });
    if (cited.nodes.has(id)) ele.addClass("cited");
    if (animate) {
      ele.style("opacity", 0);
      ele.addClass("fresh");
      ele.animate({ position: p, style: { opacity: 1 } }, { duration: animate, easing: "ease-out-cubic" });
      later(() => ele.removeClass("fresh"), animate + 500);
    }
    order.push(id);
  }

  // an edge is drawn as soon as both of its cards are on the board
  function addReadyEdges(animate) {
    for (const id of latest.edgeOrder) {
      if (cy.getElementById(id).length) continue;
      const e = latest.edges[id];
      if (!cy.getElementById(e.src).length || !cy.getElementById(e.dst).length) continue;
      const sem = edgeSemantics(e);
      const cls = ["real", sem, `rel-${String(e.rel).toLowerCase()}`];
      if (isDerived(e)) cls.push("derived");
      if (e.provenance === "conditional") cls.push("conditional");
      if (e.confidence === "low" && !isDerived(e)) cls.push("lowconf");
      const ele = cy.add({ group: "edges", classes: cls.join(" "), data: { id, source: e.src, target: e.dst, label: edgeLabel(e) } });
      if (sem === "conflict" || isDerived(e)) ele.addClass("showlabel keeplabel");
      if (cited.edges.has(id)) ele.addClass("cited");
      let inner = null;
      if (isDerived(e)) inner = cy.add({ group: "edges", classes: "inner" + (e.provenance === "conditional" ? " cond" : ""), data: { id: id + "~in", source: e.src, target: e.dst } });
      if (animate) {
        for (const x of [ele, inner]) if (x) { x.style("opacity", 0); x.animate({ style: { opacity: 1 } }, { duration: animate * 1.4, easing: "ease-out" }); }
      }
    }
  }

  function applyCited() {
    cy.elements().removeClass("cited");
    for (const id of cited.nodes) cy.getElementById(id).addClass("cited");
    for (const id of cited.edges) cy.getElementById(id).addClass("cited");
  }

  function drain() {
    timer = null;
    if (!queue.length) return;
    const ms = motionMs();
    const id = queue.shift();
    addNode(id, ms);
    addReadyEdges(ms);
    if (queue.length) {
      const gap = Math.max(130, Math.min(340, 3600 / (queue.length + 1)));
      timer = setTimeout(drain, gap);
    }
  }

  // graph: {nodes, edges, nodeOrder, edgeOrder}; cited: {nodes:Set, edges:Set}; seeds: ids
  function sync(g, citedNow, seeds = []) {
    latest = g;
    cited = citedNow;
    seedNow = new Set(seeds);
    for (const id of g.nodeOrder) kinds[id] = g.nodes[id].kind;
    const known = new Set([...order, ...queue]);
    const fresh = g.nodeOrder.filter((id) => !known.has(id));
    if (fresh.length) {
      const edgesList = g.edgeOrder.map((id) => g.edges[id]);
      Object.assign(positions, placeNew(positions, fresh, edgesList, kinds));
      fitView(); // frame the final picture first, so nothing jumps while the cards appear
    }
    applyCited();
    const ms = motionMs();
    if (!ms) {
      if (timer) { clearTimeout(timer); timer = null; }
      for (const id of [...queue, ...fresh]) addNode(id, 0);
      queue = [];
      addReadyEdges(0);
    } else {
      queue.push(...fresh);
      addReadyEdges(0);
      if (!timer && queue.length) drain();
    }
    // keep labels of cards already on the board current (a claim may get its speaker later)
    cy.nodes().forEach((ele) => { const n = g.nodes[ele.id()]; if (n) { ele.data("label", nodeLabel(n, g)); ele.data("seed", seedNow.has(ele.id())); } });
  }

  function fitView(animate) {
    const ids = Object.keys(positions).filter((id) => latest && latest.nodes[id]);
    const b = boundsOf(Object.fromEntries(ids.map((id) => [id, positions[id]])), kinds);
    if (!b) return;
    const w = cy.width(), h = cy.height();
    if (!w || !h) return;
    const pad = 34;
    const z = Math.max(0.2, Math.min(1.15, (w - 2 * pad) / b.w, (h - 2 * pad) / b.h));
    const target = { zoom: z, pan: { x: w / 2 - z * (b.x0 + b.w / 2), y: h / 2 - z * (b.y0 + b.h / 2) } };
    const ms = motionMs();
    if (animate && ms) cy.animate(target, { duration: ms * 1.5, easing: "ease-in-out" });
    else cy.viewport(target);
  }

  function select(sel) {
    cy.elements().removeClass("sel");
    selected = sel;
    if (sel) cy.getElementById(sel.id).addClass("sel");
  }

  function move(dir) {
    if (!order.length) return null;
    const i = selected && selected.kind === "node" ? order.indexOf(selected.id) : -1;
    const next = order[(i + dir + order.length) % order.length];
    return { kind: "node", id: next };
  }

  function clear() {
    if (timer) clearTimeout(timer);
    timer = null;
    for (const t of timers) clearTimeout(t);
    timers.clear();
    queue = [];
    cy.elements().remove();
    for (const k in positions) delete positions[k];
    for (const k in kinds) delete kinds[k];
    selected = null; order = []; latest = null;
  }

  return {
    cy,
    sync,
    select,
    fit: () => fitView(true),
    move,
    resize() { cy.resize(); },
    zoom(f) { cy.zoom({ level: Math.max(0.2, Math.min(2.5, cy.zoom() * f)), renderedPosition: { x: cy.width() / 2, y: cy.height() / 2 } }); },
    pan(dx, dy) { cy.panBy({ x: dx, y: dy }); },
    clear,
    restyle() { cy.style(styleSheet()); },
    center(id) { const e = cy.getElementById(id); if (e.length) cy.animate({ center: { eles: e } }, { duration: motionMs() }); },
    // test/proof hook: how many cards are on the board right now, how many are still queued
    counts() { return { shown: cy.nodes().length, queued: queue.length, edges: cy.edges(".real").length }; },
  };
}
