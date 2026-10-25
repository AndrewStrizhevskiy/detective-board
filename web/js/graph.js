// The investigation board: evidence cards pinned on cork, threads between the pins, a desk lamp
// over it. Plain DOM + SVG; the page CSP forbids style attributes, so every dynamic style is set
// through the CSSOM. Cards are revealed one by one in arrival order; placed cards never move
// unless the user drags them (layout.js).
import { placeNew, boundsOf, BOX } from "./layout.js";
import { personArt, placeArt, itemArt, exhibitLetter, stringGeom, shadowVector, initialName, storyTitle, hashStr } from "./board-art.js";

// The card's form carries the entity type together with the word on the card (never colour alone).
export const KIND_SHAPE = { person: "cabinet portrait", place: "landscape print", item: "exhibit tag", event: "newspaper clipping", claim: "index card", source: "torn book page" };
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

const MAXCH = { person: 40, place: 40, item: 40, event: 120, claim: 110, source: 40 };
function clip(s, n) { s = String(s || ""); return s.length > n ? s.slice(0, n - 1).trimEnd() + "…" : s; }

function speakerOf(n, graph) {
  if (n.props && n.props.speaker) return n.props.speaker;
  const eid = graph.edgeOrder.find((id) => graph.edges[id].rel === "ASSERTS" && graph.edges[id].dst === n.id);
  const sp = eid && graph.nodes[graph.edges[eid].src];
  return sp ? sp.name : "";
}

// One-line text for the card (also its accessible name).
export function nodeLabel(n, graph) {
  let text = clip(n.name || n.label || n.id, MAXCH[n.kind] || 40);
  if (n.kind === "claim") {
    const sp = speakerOf(n, graph);
    if (sp) text = `${initialName(sp)}: ${text}`;
  }
  if (n.kind === "source" && n.sub) text = `${text} (${n.sub})`;
  return n.confidence === "low" ? `${text} (tentative)` : text;
}

function motionMs() {
  const d = parseFloat(css("--db-dur-node"));
  return Number.isFinite(d) ? d : 0;
}

// ---------------------------------------------------------------- DOM helpers

const SVG = "http://www.w3.org/2000/svg";
function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  return e;
}
function sv(tag, attrs = {}, ...kids) {
  const e = document.createElementNS(SVG, tag);
  for (const k in attrs) e.setAttribute(k, attrs[k]);
  for (const k of kids) if (k) e.append(k);
  return e;
}
const paths = (d, cls) => sv("path", { d, class: cls });

// Shared paint servers: sepia print, engraving hatch, film grain, pin heads, steel needles.
function boardDefs() {
  const defs = sv("defs");
  const stops = (g, list) => { for (const [o, color, op] of list) { const s = sv("stop", { offset: o }); s.style.stopColor = color; if (op != null) s.style.stopOpacity = op; g.append(s); } return g; };
  defs.append(
    stops(sv("radialGradient", { id: "db-sepia", cx: "50%", cy: "38%", r: "75%" }), [["0", "#e6d3a8"], ["0.55", "#b8976a"], ["1", "#6f5333"]]),
    stops(sv("linearGradient", { id: "db-sky", x1: "0", y1: "0", x2: "0", y2: "1" }), [["0", "#eadab2"], ["1", "#b99a6b"]]),
    stops(sv("radialGradient", { id: "db-oval", cx: "50%", cy: "46%", r: "62%" }), [["0.72", "#e9dcc0", 0], ["0.9", "#e9dcc0", 1]]),
    stops(sv("radialGradient", { id: "db-vignette", cx: "50%", cy: "50%", r: "70%" }), [["0.6", "#3b2a1a", 0], ["1", "#3b2a1a", 0.55]]),
    sv("pattern", { id: "db-hatch", width: "4", height: "4", patternUnits: "userSpaceOnUse", patternTransform: "rotate(35)" }, paths("M0 0 L0 4", "hatch-line")),
    sv("filter", { id: "db-grain", x: "0", y: "0", width: "100%", height: "100%" },
      sv("feTurbulence", { type: "fractalNoise", baseFrequency: "0.9", numOctaves: "2", stitchTiles: "stitch" }),
      sv("feColorMatrix", { type: "matrix", values: "0 0 0 0 0.24  0 0 0 0 0.16  0 0 0 0 0.08  0 0 0 0.6 0" })),
    sv("filter", { id: "db-blur", x: "-50%", y: "-50%", width: "200%", height: "200%" }, sv("feGaussianBlur", { stdDeviation: "1.8" })),
    stops(sv("linearGradient", { id: "db-steel", x1: "0", y1: "0", x2: "1", y2: "1" }), [["0", "#f4f5f7"], ["0.5", "#9ba0a8"], ["1", "#50545b"]]),
  );
  for (const k of Object.keys(BOX)) {
    const v = `var(--db-pin-${k})`;
    defs.append(stops(sv("radialGradient", { id: `db-pin-${k}`, cx: "50%", cy: "50%", r: "55%", fx: "34%", fy: "30%" }),
      [["0", `color-mix(in srgb, ${v} 25%, #fff)`], ["0.55", v], ["1", `color-mix(in srgb, ${v} 45%, #000)`]]));
  }
  return defs;
}

// ---------------------------------------------------------------- card pictures (engravings)

function portrait(node) {
  const a = personArt(node);
  const hats = {
    none: null,
    bowler: [sv("ellipse", { cx: "67", cy: "44", rx: "20", ry: "14", class: "ink-2" }), sv("ellipse", { cx: "67", cy: "50", rx: "31", ry: "5", class: "ink-2" })],
    cap: [paths("M42 52 Q66 30 93 46 L98 53 Q67 46 38 56 Z", "ink-2")],
    top: [sv("rect", { x: "51", y: "14", width: "32", height: "32", class: "ink-2" }), sv("ellipse", { cx: "67", cy: "46", rx: "28", ry: "5", class: "ink-2" })],
  }[a.hat];
  return sv("svg", { viewBox: "0 0 134 150", class: "art", "aria-hidden": "true" },
    sv("rect", { width: "134", height: "150", fill: "url(#db-sepia)" }),
    sv("rect", { width: "134", height: "150", fill: "url(#db-hatch)", class: "hatch" }),
    sv("rect", { x: "58", y: "86", width: "18", height: "22", class: "ink" }),
    paths("M12 150 C16 118 40 104 67 102 C94 104 118 118 122 150 Z", "ink"),
    paths("M58 103 L67 122 L76 103", "collar"),
    sv("ellipse", { cx: "67", cy: "64", rx: "21", ry: "26", class: "ink" }),
    a.beard ? paths("M46 70 Q67 116 88 70 Q67 84 46 70 Z", "ink-2") : null,
    ...(hats || []),
    sv("rect", { width: "134", height: "150", fill: "url(#db-oval)" }),
    sv("rect", { width: "134", height: "150", filter: "url(#db-grain)", class: "grain" }));
}

const PRINTS = {
  water: () => [
    paths("M0 54 C10 42 18 48 26 40 C34 32 42 46 50 38 C60 30 68 44 78 36 C88 30 96 42 106 35 C116 29 126 44 136 37 C148 30 158 44 168 38 C176 34 184 42 184 42 L184 64 L0 64 Z", "ink-3"),
    sv("rect", { y: "63", width: "184", height: "47", class: "water" }),
    paths("M18 74 H70 M96 72 H160 M30 84 H120 M138 86 H176 M8 96 H60 M84 98 H150", "ripples"),
    paths("M6 110 L9 82 M12 110 L13 86 M17 110 L21 84 M166 110 L163 84 M172 110 L172 80 M178 110 L181 86", "reeds"),
  ],
  house: () => [
    paths("M0 80 C40 62 90 72 120 66 C150 60 170 68 184 64 L184 110 L0 110 Z", "ink-4"),
    paths("M66 50 L92 32 L120 50 Z", "ink-2"),
    sv("rect", { x: "104", y: "30", width: "6", height: "12", class: "ink-2" }),
    sv("rect", { x: "70", y: "49", width: "46", height: "26", class: "ink" }),
    sv("rect", { x: "76", y: "56", width: "8", height: "8", class: "window" }),
    sv("rect", { x: "102", y: "56", width: "8", height: "8", class: "window" }),
    paths("M0 88 L60 84 M6 84 V92 M20 83 V91 M34 83 V91 M48 83 V91", "fence"),
    sv("circle", { cx: "150", cy: "56", r: "13", class: "ink" }),
    sv("rect", { x: "148", y: "64", width: "4", height: "12", class: "ink" }),
  ],
  street: () => [
    paths("M0 110 V40 H22 V28 H40 V44 H58 V20 H70 V14 H76 V20 H88 V46 H110 V30 H132 V50 H150 V24 H170 V38 H184 V110 Z", "ink-3"),
    paths("M8 52 h6 v8 h-6z M30 50 h6 v8 h-6z M64 30 h6 v8 h-6z M64 50 h6 v8 h-6z M118 40 h6 v8 h-6z M158 34 h6 v8 h-6z M158 56 h6 v8 h-6z", "window-path"),
    paths("M0 92 H184 M0 100 H184 M20 92 L14 110 M60 92 L56 110 M100 92 L100 110 M140 92 L144 110", "cobbles"),
    paths("M98 92 V56 M92 56 H104 L101 50 H95 Z", "lamp-post"),
  ],
  room: () => [
    sv("rect", { width: "184", height: "110", class: "wall" }),
    sv("rect", { x: "18", y: "18", width: "52", height: "62", class: "window-big" }),
    paths("M44 18 V80 M18 49 H70", "mullion"),
    paths("M104 110 V60 H170 V110 M110 66 H164 V110 M118 110 V84 H156 V110", "ink-path"),
    paths("M0 96 H184", "skirting"),
  ],
  country: () => [
    paths("M0 70 C30 52 60 60 92 54 C124 48 150 58 184 50 L184 110 L0 110 Z", "ink-4"),
    paths("M0 86 C40 74 80 84 120 78 C150 74 170 80 184 76 L184 110 L0 110 Z", "ink-3"),
    sv("circle", { cx: "40", cy: "52", r: "11", class: "ink" }),
    sv("rect", { x: "38", y: "60", width: "4", height: "12", class: "ink" }),
    sv("circle", { cx: "140", cy: "44", r: "14", class: "ink" }),
    sv("rect", { x: "138", y: "54", width: "4", height: "14", class: "ink" }),
    paths("M70 104 C80 96 90 92 104 90", "path-line"),
  ],
};
function landscape(node) {
  return sv("svg", { viewBox: "0 0 184 110", class: "art", "aria-hidden": "true" },
    sv("rect", { width: "184", height: "110", fill: "url(#db-sky)" }),
    ...PRINTS[placeArt(node)](),
    sv("rect", { width: "184", height: "110", fill: "url(#db-hatch)", class: "hatch-soft" }),
    sv("rect", { width: "184", height: "110", fill: "url(#db-vignette)" }),
    sv("rect", { width: "184", height: "110", filter: "url(#db-grain)", class: "grain" }));
}

const SKETCH = {
  gun: ["M4 14 H78 L84 12 H88 V18 H80", "M4 17 H78", "M80 18 C86 20 92 24 98 32 L116 28 L112 16 L88 14 Z", "M78 18 C78 24 84 24 84 20"],
  letter: ["M22 6 H98 V40 H22 Z", "M22 6 L60 26 L98 6", "M22 40 L50 22 M98 40 L70 22", "M54 26 a6 6 0 1 0 12 0 a6 6 0 1 0 -12 0"],
  snake: ["M8 30 C20 10 34 10 44 24 C54 38 68 38 78 24 C86 12 98 10 108 18", "M108 18 C112 14 118 16 116 22 C114 26 108 24 108 18", "M20 22 l3 3 M34 16 l2 3 M60 32 l2 -3 M74 28 l2 -3"],
  key: ["M14 22 a10 10 0 1 0 20 0 a10 10 0 1 0 -20 0", "M34 22 H104 V32 M92 22 V30 M80 22 V28"],
  cloth: ["M60 4 C54 4 52 10 46 12 C36 16 30 26 26 42 L94 42 C90 26 84 16 74 12 C68 10 66 4 60 4 Z", "M44 18 L40 42 M60 14 V42 M76 18 L80 42 M30 30 H90"],
  tag: ["M30 8 H90 L104 24 L90 40 H30 Z", "M44 24 a4 4 0 1 0 8 0 a4 4 0 1 0 -8 0", "M60 18 H86 M60 26 H82 M60 34 H76"],
};
function sketch(node) {
  return sv("svg", { viewBox: "0 0 120 46", class: "art sketch", "aria-hidden": "true" }, ...SKETCH[itemArt(node)].map((d) => paths(d, "sketch-line")));
}

// ---------------------------------------------------------------- cards

function buildCard(n, graph, exhibitNo) {
  const card = el("button", `bcard bcard-${n.kind}`);
  card.type = "button";
  card.tabIndex = -1; // the board is one tab stop; arrow keys move between cards (app.js)
  const [w, h] = BOX[n.kind] || BOX.person;
  card.style.width = `${w}px`;
  card.style.height = `${h}px`;
  card.style.setProperty("--rot", `${((hashStr(n.id) % 7) - 3) * 0.8}deg`);
  const tentative = n.confidence === "low";
  const kicker = (word) => el("span", "kicker", tentative ? `${word} · tentative` : word);
  const story = storyTitle(n.story);
  if (n.kind === "person") {
    const alias = (n.aliases || [])[0];
    card.append(el("span", "photo", null), el("span", "cap name", clip(n.name, MAXCH.person)), kicker(alias ? `person · ${clip(alias, 22)}` : "person"));
    card.firstChild.append(portrait(n));
  } else if (n.kind === "place") {
    card.append(el("span", "photo", null), el("span", "cap name", clip(n.name, MAXCH.place)), kicker("place"));
    card.firstChild.append(landscape(n));
  } else if (n.kind === "item") {
    card.append(el("span", "exhibit", `EXHIBIT ${exhibitLetter(exhibitNo)}`), sketch(n), el("span", "cap name", clip(n.name, MAXCH.item)), kicker("item"));
  } else if (n.kind === "event") {
    const when = n.props && (n.props.time_text || n.props.time_norm);
    card.append(el("span", "masthead", story ? story.toUpperCase() : "EVENT"), el("span", "headline", clip(n.name || n.label, MAXCH.event)), kicker(when ? `event · ${clip(when, 24)}` : "event"));
  } else if (n.kind === "claim") {
    const sp = speakerOf(n, graph);
    card.append(el("span", "speaker", sp ? `${initialName(sp).toUpperCase()} · CLAIM` : "CLAIM"), el("span", "said", `“${clip(n.name || n.label, MAXCH.claim)}”`), kicker(`~ ${n.provenance || "extracted"}${n.confidence ? ` (${n.confidence})` : ""}`));
  } else {
    card.append(el("span", "kicker top", "source text"), el("span", "cap name", story || clip(n.name, MAXCH.source)), el("span", "sub", n.sub || (n.chunk_id ? String(n.chunk_id) : "")));
  }
  if (tentative) card.classList.add("tentative");
  card.dataset.id = n.id;
  card.id = `card-${hashStr(n.id).toString(36)}`;
  return card;
}

function pinGroup(kind) {
  const g = sv("g", { class: "pin" });
  const shadow = sv("circle", { r: "7.2", class: "p-shadow", filter: "url(#db-blur)" });
  const needleShadow = paths("", "p-needle-shadow");
  needleShadow.setAttribute("filter", "url(#db-blur)");
  const knot = sv("g", { class: "p-knot" },
    sv("ellipse", { rx: "10", ry: "3.6", transform: "rotate(-18)", class: "k-casing" }),
    sv("ellipse", { rx: "10", ry: "3.6", transform: "rotate(-18)", class: "k-core" }),
    sv("ellipse", { rx: "9", ry: "3.2", transform: "rotate(32)", class: "k-casing" }),
    sv("ellipse", { rx: "9", ry: "3.2", transform: "rotate(32)", class: "k-core k-core-2" }),
    paths("M6 5 C10 8 9 13 13 16", "k-end"),
    paths("M-5 6 C-7 10 -11 11 -12 15", "k-end"));
  const needleBack = paths("", "p-needle-back");
  const needle = paths("", "p-needle");
  g.append(shadow, needleShadow, knot, needleBack, needle,
    sv("circle", { r: "7.6", fill: `url(#db-pin-${kind})` }),
    sv("circle", { r: "7.6", class: "p-rim" }),
    sv("ellipse", { cx: "-2.6", cy: "-3", rx: "2.4", ry: "1.7", transform: "rotate(-30 -2.6 -3)", class: "p-spec" }),
    sv("circle", { cx: "2.8", cy: "3.2", r: "3.4", class: "p-bounce" }));
  return { g, shadow, needleShadow, needle, needleBack, knot };
}

// ---------------------------------------------------------------- the board

const PIN_Y = 13; // pin centre below the top edge of a card (the pin zone holds no text)
const Z_MIN = 0.2, Z_MAX = 2.5;

export function createGraph(container, { onSelect, onDoubleSelect } = {}) {
  container.classList.add("board-view");
  const world = el("div", "board-world");
  const cardsLayer = el("div", "board-cards");
  // thread hit areas lie under the cards, so a card always wins a click where a thread crosses it
  const hits = sv("svg", { class: "board-hits", width: "1", height: "1", "aria-hidden": "true" });
  const threads = sv("svg", { class: "board-threads", width: "1", height: "1", "aria-hidden": "true" });
  const pinsSvg = sv("svg", { class: "board-pins", width: "1", height: "1", "aria-hidden": "true" }, boardDefs());
  const tagsLayer = el("div", "board-tags");
  world.append(hits, cardsLayer, threads, pinsSvg, tagsLayer);
  const glow = el("div", "lamp-glow");
  const shade = el("div", "lamp-shade");
  container.append(world, glow, shade);

  const positions = {};
  const kinds = {};
  const cards = new Map(); // id -> {el, pin}
  const strings = new Map(); // edge id -> {g, parts, tag, e}
  let selected = null;
  let order = [];
  let latest = null;
  let seedNow = new Set();
  let cited = { nodes: new Set(), edges: new Set() };
  let queue = [];
  let timer = null;
  let items = 0;
  const timers = new Set();
  const view = { x: 0, y: 0, z: 1 };
  let vw = container.clientWidth || 800, vh = container.clientHeight || 600;
  let shadeQueued = false;

  const later = (fn, ms) => { const t = setTimeout(() => { timers.delete(t); fn(); }, ms); timers.add(t); };
  const dimsOf = (id) => BOX[kinds[id]] || BOX.person;
  const pinAt = (id) => { const p = positions[id]; const [, hh] = dimsOf(id); return { x: p.x, y: p.y - hh / 2 + PIN_Y }; };

  // ---- view: pan and zoom of the board, the cork texture moves with it
  function applyView(glide, ease) {
    world.classList.toggle("glide", !!glide && motionMs() > 0);
    world.classList.toggle("ease", !!ease && !glide && motionMs() > 0);
    world.style.transform = `translate(${view.x}px, ${view.y}px) scale(${view.z})`;
    const z = view.z;
    container.style.backgroundSize = `${7 * z}px ${7 * z}px, ${11 * z}px ${11 * z}px, ${23 * z}px ${23 * z}px`;
    container.style.backgroundPosition = `${view.x}px ${view.y}px, ${view.x + 3 * z}px ${view.y + 5 * z}px, ${view.x + 9 * z}px ${view.y + 13 * z}px`;
    queueShade();
  }

  // ---- the lamp: it hangs over the selected card, else over the middle of the board
  function lampScreen() {
    if (selected && selected.kind === "node" && positions[selected.id]) {
      const p = positions[selected.id];
      return { x: p.x * view.z + view.x, y: (p.y + 40) * view.z + view.y };
    }
    if (focusOn && positions[focusOn.e.src] && positions[focusOn.e.dst]) {
      const a = positions[focusOn.e.src], b = positions[focusOn.e.dst];
      return { x: ((a.x + b.x) / 2) * view.z + view.x, y: ((a.y + b.y) / 2 + 40) * view.z + view.y };
    }
    return { x: vw / 2, y: vh * 0.42 };
  }
  // While the user drags, pans or zooms only the lamp follows; the card shadows (drop-shadow
  // filters, expensive to repaint) are recomputed once the board has been still for a moment.
  let interacting = false;
  let settleTimer = null;
  function settle() {
    clearTimeout(settleTimer);
    settleTimer = setTimeout(() => { interacting = false; container.classList.remove("zooming"); queueShade(); }, 160);
  }
  function queueShade() {
    if (shadeQueued) return;
    shadeQueued = true;
    requestAnimationFrame(() => { shadeQueued = false; updateLamp(); if (!interacting) updateShadows(); });
  }
  // The lamp glides when it follows a card or a finding, but is set in place without a glide the
  // first time and after a resize, so it never slides in from the corner on load.
  let lampPlaced = false;
  function updateLamp(instant) {
    const ls = lampScreen();
    const jump = instant || !lampPlaced;
    if (jump) container.classList.add("lamp-still");
    glow.style.translate = shade.style.translate = `${ls.x}px ${ls.y}px`; // own GPU layers: no repaint
    if (jump) {
      lampPlaced = true;
      requestAnimationFrame(() => requestAnimationFrame(() => container.classList.remove("lamp-still")));
    }
  }
  function updateShadows() {
    const ls = lampScreen();
    const lamp = { x: (ls.x - view.x) / view.z, y: (ls.y - view.y) / view.z };
    for (const [id, c] of cards) {
      const p = positions[id];
      const v = shadowVector({ x: p.x, y: p.y + 60 }, lamp, 1.6);
      const halo = cited.nodes.has(id) ? "drop-shadow(0 0 4px var(--db-halo)) drop-shadow(0 0 12px var(--db-halo)) " : "";
      c.el.style.filter = `${halo}drop-shadow(${v.x}px ${v.y + 3}px ${9}px rgba(0, 0, 0, var(--db-shadow-alpha)))`;
      const pv = shadowVector(pinAt(id), lamp, 1);
      c.pin.shadow.setAttribute("cx", pv.x);
      c.pin.shadow.setAttribute("cy", pv.y);
      const nx = (pv.x * 1.9).toFixed(1), ny = (pv.y * 1.9).toFixed(1);
      c.pin.needle.setAttribute("d", `M0 0 L${nx} ${ny}`);
      c.pin.needleBack.setAttribute("d", `M0 0 L${nx} ${ny}`);
      c.pin.needleShadow.setAttribute("d", `M${pv.x} ${pv.y} L${(pv.x * 3.3).toFixed(1)} ${(pv.y * 3.3).toFixed(1)}`);
    }
    const tv = shadowVector({ x: 0, y: 200 }, { x: 0, y: 0 }, 0.8);
    for (const s of strings.values()) s.parts.shadow.setAttribute("transform", `translate(${tv.x} ${tv.y + 2.5})`);
  }

  // What a hanging tag says: the finding in big letters, then how it was made and between which
  // two cards ("= derived · rule R3 · claim ✕ event"); hovering the tag rings those two cards.
  function findingTag(e, sem, derived) {
    const word = (id) => (KIND_WORD[kinds[id]] || "card").toLowerCase();
    const r = ruleOf(e);
    const title = { conflict: "! Contradiction", support: "\u2713 Supports", unknown: "? Unknown" }[sem] || `= ${(e.props && e.props.predicate) || REL_WORD[e.rel] || String(e.rel).toLowerCase().replace(/_/g, " ")}`;
    const how = derived ? `${e.provenance === "conditional" ? "=? conditional" : "= derived"}${r ? ` · rule ${r}` : ""}` : "~ extracted";
    const between = `${word(e.src)} ${sem === "conflict" ? "\u2715" : "\u2192"} ${word(e.dst)}`;
    const name = (id) => { const n = latest && latest.nodes[id]; return n ? nodeLabel(n, latest) : id; };
    const spoken = `${title.replace(/^[!?=\u2713] /, "")}${derived ? `, ${e.provenance === "conditional" ? "conditional, " : ""}found by rule ${r || "?"}` : ""}, between ${word(e.src)} "${name(e.src)}" and ${word(e.dst)} "${name(e.dst)}"`;
    return { title, sub: `${how} · ${between}`, spoken };
  }

  // ---- cards and pins
  function placeCard(id) {
    const c = cards.get(id);
    const p = positions[id];
    const [w, h] = dimsOf(id);
    c.el.style.translate = `${p.x - w / 2}px ${p.y - h / 2}px`; // composited, no layout per frame
    const pin = pinAt(id);
    c.pin.g.setAttribute("transform", `translate(${pin.x} ${pin.y})`);
  }

  function addNode(id, animate) {
    const n = latest.nodes[id];
    if (!n || cards.has(id)) return;
    const card = buildCard(n, latest, n.kind === "item" ? items++ : 0);
    card.setAttribute("aria-label", `${KIND_WORD[n.kind] || n.kind}: ${nodeLabel(n, latest)}`);
    if (seedNow.has(id)) card.classList.add("seed");
    if (cited.nodes.has(id)) card.classList.add("cited");
    const pin = pinGroup(KIND_WORD[n.kind] ? n.kind : "person");
    if (animate) {
      card.classList.add("fresh");
      pin.g.classList.add("fresh");
      later(() => { card.classList.remove("fresh"); pin.g.classList.remove("fresh"); }, animate + 600);
    }
    cardsLayer.append(card);
    pinsSvg.append(pin.g);
    cards.set(id, { el: card, pin });
    placeCard(id);
    order.push(id);
    queueShade();
  }

  function threadParts(cls) {
    const g = sv("g", { class: cls });
    const mk = (c) => paths("", c);
    const parts = { hit: mk("t-hit"), shadow: mk("t-shadow"), halo: mk("t-halo"), casing: mk("t-casing"), core: mk("t-core"), twist: mk("t-twist"), casing2: mk("t-casing"), core2: mk("t-core"), twist2: mk("t-twist"), dir: mk("t-dir") };
    parts.shadow.setAttribute("filter", "url(#db-blur)");
    g.append(parts.shadow, parts.halo, parts.casing, parts.core, parts.twist, parts.casing2, parts.core2, parts.twist2, parts.dir);
    const hitG = sv("g", { class: "thread-hit" }, parts.hit);
    return { g, hitG, parts };
  }

  function placeString(id) {
    const s = strings.get(id);
    const a = pinAt(s.e.src), b = pinAt(s.e.dst);
    const g1 = stringGeom(a, b, 0);
    const p = s.parts;
    for (const k of ["hit", "shadow", "halo", "casing", "core", "twist"]) p[k].setAttribute("d", g1.d);
    if (s.double) { const g2 = stringGeom(a, b, 5); for (const k of ["casing2", "core2", "twist2"]) p[k].setAttribute("d", g2.d); }
    if (s.arrow) p.dir.setAttribute("transform", `translate(${g1.mid.x} ${g1.mid.y}) rotate(${g1.angle})`);
    if (s.tag) {
      s.tag.style.left = `${g1.mid.x}px`;
      // a hover label sits on the thread; an always-shown tag hangs from it (from the lower line of a double)
      s.tag.style.top = `${g1.mid.y + (s.double ? 5 : 0)}px`;
    }
  }

  // an edge is drawn as soon as both of its cards are on the board
  function addReadyEdges(animate) {
    for (const id of latest.edgeOrder) {
      if (strings.has(id)) continue;
      const e = latest.edges[id];
      if (!cards.has(e.src) || !cards.has(e.dst) || e.src === e.dst) continue;
      const sem = edgeSemantics(e);
      const cls = ["thread", `sem-${sem}`, `rel-${String(e.rel).toLowerCase()}`];
      const derived = isDerived(e);
      if (derived) cls.push("derived");
      if (e.provenance === "conditional") cls.push("conditional");
      if (e.confidence === "low" && !derived) cls.push("lowconf");
      if (cited.edges.has(id)) cls.push("cited");
      if (animate) cls.push("fresh");
      const { g, hitG, parts } = threadParts(cls.join(" "));
      if (!derived) for (const k of ["casing2", "core2", "twist2"]) parts[k].remove();
      const arrow = e.rel !== "ASSERTS";
      if (arrow) parts.dir.setAttribute("d", "M-4 -3.5 L2.5 0 L-4 3.5");
      else parts.dir.remove();
      parts.hit.addEventListener("click", (ev) => { ev.stopPropagation(); onSelect && onSelect({ kind: "edge", id }); });
      parts.hit.addEventListener("pointerenter", () => s.tag && s.tag.classList.add("hover"));
      parts.hit.addEventListener("pointerleave", () => s.tag && s.tag.classList.remove("hover"));
      const label = edgeLabel(e);
      let tag = null;
      if (sem !== "relation" || derived) {
        // threads all share one colour, so a finding is named on a tag that hangs from its thread
        const t = findingTag(e, sem, derived);
        tag = el("button", `tag-label always ${derived ? "stamp" : "finding"} tag-${sem}`);
        tag.append(el("span", "tag-title", t.title), el("span", "tag-sub", t.sub));
        tag.type = "button";
        tag.tabIndex = -1;
        tag.setAttribute("aria-label", `${t.spoken}. Show why.`);
        tag.title = t.spoken;
        tag.addEventListener("click", (ev) => { ev.stopPropagation(); onSelect && onSelect({ kind: "edge", id }); });
        tag.style.setProperty("--sway", `${(hashStr(String(id)) % 9) - 4}deg`);
        const hot = (on) => {
          g.classList.toggle("hot", on);
          for (const end of [e.src, e.dst]) { const c = cards.get(end); if (c) c.el.classList.toggle("linked", on); }
        };
        for (const [evName, on] of [["pointerenter", true], ["pointerleave", false], ["focus", true], ["blur", false]]) tag.addEventListener(evName, () => hot(on));
      } else if (label) {
        tag = el("span", "tag-label", label);
        tag.setAttribute("aria-hidden", "true");
      }
      const s = { g, hitG, parts, tag, e, double: derived, arrow };
      strings.set(id, s);
      threads.append(g);
      hits.append(hitG);
      // only the always-visible tags are stamped in; a hover label must stay hidden after it
      if (tag) { tagsLayer.append(tag); if (animate && tag.classList.contains("always")) tag.classList.add("fresh"); }
      if (animate) later(() => { g.classList.remove("fresh"); if (tag) tag.classList.remove("fresh"); }, animate * 1.4 + 600);
      placeString(id);
      cards.get(e.src).pin.knot.classList.add("on");
      cards.get(e.dst).pin.knot.classList.add("on");
    }
    applySelection();
  }

  function applyCited() {
    for (const [id, c] of cards) c.el.classList.toggle("cited", cited.nodes.has(id));
    for (const [id, s] of strings) s.g.classList.toggle("cited", cited.edges.has(id));
    queueShade();
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
    scheduleFocus();
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
      if (!focusOn && !flyRaf) fitView(); // frame the final picture first, so nothing jumps while the cards appear
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
    // keep cards already on the board current (a claim may get its speaker later)
    for (const [id, c] of cards) {
      const n = g.nodes[id];
      if (!n) continue;
      c.el.setAttribute("aria-label", `${KIND_WORD[n.kind] || n.kind}: ${nodeLabel(n, g)}`);
      c.el.classList.toggle("seed", seedNow.has(id));
      if (n.kind === "claim") {
        const sp = speakerOf(n, g);
        const head = c.el.querySelector(".speaker");
        if (head && sp) head.textContent = `${initialName(sp).toUpperCase()} · CLAIM`;
      }
    }
  }

  // the view that frames bounds b (board px) with a margin, zoomed in at most to maxZ
  function viewFor(b, maxZ, pad = 40) {
    const z = Math.max(Z_MIN, Math.min(maxZ, (vw - 2 * pad) / b.w, (vh - 2 * pad) / b.h));
    return { z, x: vw / 2 - z * (b.x0 + b.w / 2), y: vh / 2 - z * (b.y0 + b.h / 2) };
  }
  function overview() {
    const ids = Object.keys(positions).filter((id) => latest && latest.nodes[id]);
    const b = boundsOf(Object.fromEntries(ids.map((id) => [id, positions[id]])), kinds);
    measure();
    return b && vw && vh ? viewFor(b, 1.1) : null;
  }
  function fitView(animate) {
    const t = overview();
    if (!t) return;
    Object.assign(view, t);
    applyView(animate);
  }

  // ---- camera: when the rules find a contradiction and its evidence is pinned, fly to the two
  // cards, ring them and swing the tag, hold, then fly back to the whole board. Once per board,
  // never with motion off, and any pan, zoom, drag or key hands the camera back to the user.
  const FOCUS_HOLD_MS = 3600;
  let focusTimer = null;
  let flyRaf = 0;
  let focusOn = null;
  let focusDone = false;
  let lastUserAt = -Infinity;
  function userActed() {
    lastUserAt = performance.now();
    if (flyRaf) { cancelAnimationFrame(flyRaf); flyRaf = 0; settle(); }
  }
  function animateView(target, ms, done) {
    if (flyRaf) cancelAnimationFrame(flyRaf);
    const from = { ...view };
    let t0 = performance.now();
    interacting = true;
    clearTimeout(settleTimer);
    container.classList.add("zooming"); // the board moves as one composited layer while flying
    const step = (now) => {
      const k = Math.min(1, (now - t0) / ms);
      const e = k < 0.5 ? 4 * k * k * k : 1 - Math.pow(-2 * k + 2, 3) / 2;
      view.x = from.x + (target.x - from.x) * e;
      view.y = from.y + (target.y - from.y) * e;
      view.z = from.z * Math.pow(target.z / from.z, e);
      applyView(false);
      if (k < 1) { flyRaf = requestAnimationFrame(step); return; }
      flyRaf = 0;
      settle();
      if (done) done();
    };
    // start one frame late: the layer is promoted in its own frame, not in the first moving one
    flyRaf = requestAnimationFrame(() => { flyRaf = requestAnimationFrame((now) => { t0 = now; step(now); }); });
  }
  function spotlight(s, on) {
    s.g.classList.toggle("hot", on);
    for (const end of [s.e.src, s.e.dst]) { const c = cards.get(end); if (c) c.el.classList.toggle("linked", on); }
    if (s.tag) {
      s.tag.classList.toggle("spot", on);
      // a second swing on the tag that never fades it (restarting the arrival animation would
      // start from opacity 0 and make the tag blink)
      if (on && s.tag.animate) {
        s.tag.classList.remove("fresh");
        const sway = parseFloat(s.tag.style.getPropertyValue("--sway")) || -5;
        const at = (d) => ({ transform: `translate(-50%, 15px) rotate(${sway + d}deg)` });
        s.tag.animate([at(0), at(11), at(-7), at(3), at(0)], { duration: motionMs() * 3.4, easing: "ease-out" });
      }
    }
    queueShade();
  }
  function scheduleFocus() {
    if (focusDone || !motionMs()) return;
    clearTimeout(focusTimer);
    focusTimer = setTimeout(runFocus, 900); // wait until the board has been quiet for a moment
  }
  function runFocus() {
    focusTimer = null;
    if (focusDone || !motionMs()) return;
    if (queue.length || timer) { scheduleFocus(); return; }
    if (drag || performance.now() - lastUserAt < 2500) return;
    const s = [...strings.values()].find((x) => x.tag && x.tag.classList.contains("tag-conflict"));
    if (!s || !positions[s.e.src] || !positions[s.e.dst]) return;
    focusDone = true;
    measure();
    const ends = { a: positions[s.e.src], b: positions[s.e.dst] };
    const b = boundsOf(ends, { a: kinds[s.e.src], b: kinds[s.e.dst] });
    const room = { ...b, y1: b.y1 + 70, h: b.h + 70 }; // the tag hangs below the thread
    const started = performance.now();
    focusOn = s;
    spotlight(s, true);
    animateView(viewFor(room, 1.5, 70), motionMs() * 3, () => {
      focusTimer = setTimeout(() => {
        focusTimer = null;
        if (focusOn === s) { spotlight(s, false); focusOn = null; }
        const back = overview();
        if (back && lastUserAt < started) animateView(back, motionMs() * 3);
        else queueShade();
      }, FOCUS_HOLD_MS);
    });
  }

  function measure() { vw = container.clientWidth || vw; vh = container.clientHeight || vh; }

  function zoomAt(cx, cy, factor, ease) {
    const z = Math.max(Z_MIN, Math.min(Z_MAX, view.z * factor));
    const k = z / view.z;
    view.x = cx - (cx - view.x) * k;
    view.y = cy - (cy - view.y) * k;
    view.z = z;
    applyView(false, ease);
  }

  function applySelection() {
    const nodeSel = selected && selected.kind === "node" ? selected.id : null;
    const edgeSel = selected && selected.kind === "edge" ? selected.id : null;
    for (const [id, c] of cards) c.el.classList.toggle("sel", id === nodeSel);
    for (const [id, s] of strings) {
      const touches = nodeSel ? s.e.src === nodeSel || s.e.dst === nodeSel : edgeSel ? id === edgeSel : true;
      s.g.classList.toggle("sel", id === edgeSel);
      s.g.classList.toggle("dim", !!selected && !touches);
      if (s.tag) { s.tag.classList.toggle("sel", id === edgeSel || (!!nodeSel && touches)); s.tag.classList.toggle("dim", !!selected && !touches); }
    }
    queueShade();
  }

  function select(sel) {
    selected = sel;
    applySelection();
    const c = sel && sel.kind === "node" ? cards.get(sel.id) : null;
    if (c) container.setAttribute("aria-activedescendant", c.el.id);
    else container.removeAttribute("aria-activedescendant");
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
    clearTimeout(focusTimer);
    focusTimer = null;
    if (flyRaf) cancelAnimationFrame(flyRaf);
    flyRaf = 0;
    focusOn = null;
    focusDone = false;
    for (const t of timers) clearTimeout(t);
    timers.clear();
    queue = [];
    cardsLayer.replaceChildren();
    tagsLayer.replaceChildren();
    for (const c of cards.values()) c.pin.g.remove();
    for (const s of strings.values()) { s.g.remove(); s.hitG.remove(); }
    cards.clear();
    strings.clear();
    for (const k in positions) delete positions[k];
    for (const k in kinds) delete kinds[k];
    selected = null; order = []; latest = null; items = 0;
    queueShade();
  }

  // ---- pointer: drag a card to re-pin it, drag the cork to pan, wheel to zoom
  let drag = null;
  let suppressClick = false;
  const cssScale = () => { const r = container.getBoundingClientRect(); return container.offsetWidth ? r.width / container.offsetWidth : 1; };

  container.addEventListener("pointerdown", (ev) => {
    if (ev.button !== 0) return;
    userActed();
    if (ev.target.closest(".tag-label") || ev.target.classList.contains("t-hit")) return;
    const cardEl = ev.target.closest(".bcard");
    const base = { sx: ev.clientX, sy: ev.clientY, s: cssScale(), moved: false, pointer: ev.pointerId };
    if (cardEl) {
      const id = cardEl.dataset.id;
      drag = { ...base, kind: "card", id, ox: positions[id].x, oy: positions[id].y, el: cardEl };
    } else {
      drag = { ...base, kind: "pan", vx: view.x, vy: view.y };
    }
  });
  // pointer moves only record where the pointer is; the board is updated once per frame
  function applyDrag() {
    const d = drag;
    if (!d) return;
    d.raf = 0;
    if (d.kind === "card") {
      positions[d.id] = { x: d.ox + d.dx / view.z, y: d.oy + d.dy / view.z };
      placeCard(d.id);
      for (const sid of d.links) placeString(sid);
    } else {
      view.x = d.vx + d.dx;
      view.y = d.vy + d.dy;
      applyView(false);
    }
  }
  container.addEventListener("pointermove", (ev) => {
    if (!drag || ev.pointerId !== drag.pointer) return;
    const dx = (ev.clientX - drag.sx) / drag.s;
    const dy = (ev.clientY - drag.sy) / drag.s;
    if (!drag.moved) {
      if (Math.hypot(dx, dy) < 4) return;
      drag.moved = true;
      interacting = true;
      clearTimeout(settleTimer);
      try { container.setPointerCapture(ev.pointerId); } catch { /* pointer already gone */ }
      container.classList.add(drag.kind === "card" ? "dragging-card" : "panning");
      if (drag.kind === "card") {
        drag.el.classList.add("lifted");
        drag.links = [...strings].filter(([, s]) => s.e.src === drag.id || s.e.dst === drag.id).map(([sid]) => sid);
      }
    }
    drag.dx = dx;
    drag.dy = dy;
    if (!drag.raf) drag.raf = requestAnimationFrame(applyDrag);
  });
  const endDrag = (ev) => {
    if (!drag || (ev && ev.pointerId !== drag.pointer)) return;
    const d = drag;
    if (d.raf) { cancelAnimationFrame(d.raf); applyDrag(); }
    drag = null;
    if (d.kind === "card" && d.moved) positions[d.id] = { x: Math.round(positions[d.id].x), y: Math.round(positions[d.id].y) };
    container.classList.remove("dragging-card", "panning");
    if (d.moved) settle();
    if (d.kind === "card") d.el.classList.remove("lifted");
    if (d.moved) { suppressClick = true; setTimeout(() => { suppressClick = false; }, 0); }
    else if (d.kind === "pan" && onSelect) onSelect(null);
  };
  container.addEventListener("pointerup", endDrag);
  container.addEventListener("pointercancel", endDrag);
  cardsLayer.addEventListener("click", (ev) => {
    const c = ev.target.closest(".bcard");
    if (!c || suppressClick) return;
    onSelect && onSelect({ kind: "node", id: c.dataset.id });
  });
  cardsLayer.addEventListener("dblclick", (ev) => {
    const c = ev.target.closest(".bcard");
    if (c && onDoubleSelect) onDoubleSelect({ kind: "node", id: c.dataset.id });
  });
  // A mouse notch (deltaY ~100) zooms about 27 %; a trackpad pinch arrives as ctrl+wheel with
  // small deltas, so it gets a higher gain. Short eased steps keep a notched wheel smooth.
  container.addEventListener("wheel", (ev) => {
    ev.preventDefault();
    const r = container.getBoundingClientRect();
    const s = cssScale();
    const unit = ev.deltaMode === 1 ? 16 : ev.deltaMode === 2 ? vh : 1;
    const gain = ev.ctrlKey ? 0.012 : 0.0032;
    userActed();
    const f = Math.max(0.5, Math.min(2, Math.exp(-ev.deltaY * unit * gain)));
    interacting = true;
    container.classList.add("zooming");
    zoomAt((ev.clientX - r.left) / s, (ev.clientY - r.top) / s, f, true);
    settle();
  }, { passive: false });

  applyView(false);

  return {
    sync,
    select,
    // fit() from a button or key hands the camera to the user; fit({ auto: true }) from a resize
    // does not, and waits while the camera is showing a finding
    fit(opts) {
      if (opts && opts.auto) { if (!focusOn && !flyRaf) fitView(false); return; }
      userActed();
      fitView(true);
    },
    userActed,
    move,
    resize() { measure(); updateLamp(true); queueShade(); },
    zoom(f) { userActed(); measure(); zoomAt(vw / 2, vh / 2, f, true); queueShade(); },
    pan(dx, dy) { userActed(); view.x += dx; view.y += dy; applyView(false); },
    clear,
    restyle() { queueShade(); },
    center(id) {
      userActed();
      const p = positions[id];
      if (!p) return;
      measure();
      view.x = vw / 2 - p.x * view.z;
      view.y = vh / 2 - p.y * view.z;
      applyView(true);
    },
    // test/proof hook: how many cards are on the board right now, how many are still queued
    counts() { return { shown: cards.size, queued: queue.length, edges: strings.size }; },
    element: container,
  };
}
