// Cytoscape wrapper. Elements are added incrementally; placed nodes never move (see layout.js).
import cytoscape from "../vendor/cytoscape.esm.min.mjs";
import { placeNew } from "./layout.js";

export const KIND_SHAPE = { person: "ellipse", place: "round-rectangle", item: "diamond", event: "hexagon", claim: "round-tag" };
export const KIND_GLYPH = { person: "P", place: "L", item: "I", event: "E", claim: "C" };

const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
export const isDerived = (e) => e.provenance === "derived" || e.provenance === "conditional";

export function edgeSemantics(e) {
  const t = `${e.rel || ""} ${(e.props && (e.props.verdict || e.props.status)) || ""}`.toLowerCase();
  if (/contradict|conflict|violat/.test(t)) return "conflict";
  if (/support|consistent/.test(t)) return "support";
  if (/unknown|insufficient/.test(t)) return "unknown";
  return "relation";
}

function motionMs() {
  const d = parseFloat(css("--db-dur-node"));
  return Number.isFinite(d) ? d : 0;
}

function styleSheet() {
  const bg = css("--db-bg-board");
  const s = [
    { selector: "node", style: { label: "data(label)", "text-valign": "center", "text-halign": "center", "text-wrap": "ellipsis", "text-max-width": 96, "font-size": 12, "font-family": css("--db-font-ui"), color: css("--db-text-on-fill"), width: 108, height: 54, "border-width": 2, "background-opacity": 1, "min-zoomed-font-size": 0 } },
    { selector: "node[?seed]", style: { "border-width": 4, "border-style": "double" } },
    { selector: "node[conf = 'low']", style: { "border-style": "dashed" } },
    { selector: "node.cited", style: { "border-width": 5, "underlay-color": css("--db-quote-bg"), "underlay-opacity": 1, "underlay-padding": 7, "underlay-shape": "ellipse" } },
    { selector: "node.sel", style: { "border-color": css("--db-selected-ring"), "border-width": 5, "outline-width": 3, "outline-color": css("--db-focus"), "outline-offset": 2, "outline-opacity": 1 } },
    { selector: "edge", style: { width: 2, "line-color": css("--db-edge"), "target-arrow-color": css("--db-edge"), "target-arrow-shape": "triangle", "curve-style": "bezier", label: "", "font-size": 11, color: css("--db-text"), "text-background-color": bg, "text-background-opacity": 0.9, "text-background-padding": 2, "text-rotation": "autorotate", "arrow-scale": 1.2 } },
    { selector: "edge.showlabel", style: { label: "data(label)" } },
    { selector: "edge.support", style: { "line-color": css("--db-edge-support"), "target-arrow-color": css("--db-edge-support") } },
    { selector: "edge.conflict", style: { "line-color": css("--db-edge-conflict"), "target-arrow-color": css("--db-edge-conflict"), width: 3 } },
    { selector: "edge.unknown", style: { "line-color": css("--db-edge-unknown"), "target-arrow-color": css("--db-edge-unknown"), "line-style": "dotted" } },
    // derived/conditional: double line = a wide stroke with a board-coloured core drawn on top
    { selector: "edge.derived", style: { width: 8 } },
    { selector: "edge.derived.conflict", style: { width: 9 } },
    { selector: "edge.conditional", style: { "line-style": "dashed" } },
    { selector: "edge.inner", style: { width: 3, "line-color": bg, "target-arrow-shape": "none", "line-style": "solid", events: "no", label: "", "z-index": 20 } },
    { selector: "edge.inner.cond", style: { "line-style": "dashed" } },
    { selector: "edge.cited", style: { "underlay-color": css("--db-quote-bg"), "underlay-opacity": 1, "underlay-padding": 5 } },
    { selector: "edge.sel", style: { "overlay-color": css("--db-focus"), "overlay-opacity": 0.28, "overlay-padding": 6 } },
  ];
  for (const k of Object.keys(KIND_SHAPE)) {
    s.push({ selector: `node[kind = '${k}']`, style: { shape: KIND_SHAPE[k], "border-color": css(`--db-${k}-fg`), "background-color": css(`--db-${k}-fill`) } });
  }
  return s;
}

export function createGraph(container, { onSelect, onDoubleSelect } = {}) {
  const cy = cytoscape({ container, elements: [], style: styleSheet(), minZoom: 0.2, maxZoom: 2.5, wheelSensitivity: 0.3, boxSelectionEnabled: false, autoungrabify: false });
  const positions = {};
  let selected = null;
  let order = [];

  cy.on("tap", "node", (ev) => onSelect && onSelect({ kind: "node", id: ev.target.id() }));
  cy.on("tap", "edge.real", (ev) => onSelect && onSelect({ kind: "edge", id: ev.target.id() }));
  cy.on("dbltap", "node", (ev) => onDoubleSelect && onDoubleSelect({ kind: "node", id: ev.target.id() }));
  cy.on("tap", (ev) => { if (ev.target === cy && onSelect) onSelect(null); });
  cy.on("mouseover", "edge.real", (ev) => ev.target.addClass("showlabel"));
  cy.on("mouseout", "edge.real", (ev) => { if (!ev.target.hasClass("keeplabel")) ev.target.removeClass("showlabel"); });
  cy.on("dragfree", "node", (ev) => { positions[ev.target.id()] = { ...ev.target.position() }; });

  function sync(graph, cited, seeds = []) {
    const newNodeIds = graph.nodeOrder.filter((id) => !cy.getElementById(id).length);
    const edgesList = graph.edgeOrder.map((id) => graph.edges[id]);
    const added = placeNew(positions, newNodeIds, edgesList);
    Object.assign(positions, added);
    const ms = motionMs();
    const seedSet = new Set(seeds);
    cy.batch(() => {
      for (const id of newNodeIds) {
        const n = graph.nodes[id];
        const ele = cy.add({ group: "nodes", data: { id, kind: n.kind, label: `${KIND_GLYPH[n.kind] || "?"} ${n.name}`, conf: n.confidence || "", seed: seedSet.has(id) }, position: positions[id] });
        ele.style("opacity", ms ? 0 : 1);
      }
      for (const id of graph.edgeOrder) {
        if (cy.getElementById(id).length) continue;
        const e = graph.edges[id];
        if (!cy.getElementById(e.src).length || !cy.getElementById(e.dst).length) continue; // wait for the endpoint
        const sem = edgeSemantics(e);
        const cls = ["real", sem];
        if (isDerived(e)) cls.push("derived");
        if (e.provenance === "conditional") cls.push("conditional");
        const ele = cy.add({ group: "edges", classes: cls.join(" "), data: { id, source: e.src, target: e.dst, label: sem === "conflict" ? `${e.rel} (conflicts)` : e.rel } });
        if (sem === "conflict") { ele.addClass("showlabel keeplabel"); }
        if (isDerived(e)) cy.add({ group: "edges", classes: "inner" + (e.provenance === "conditional" ? " cond" : ""), data: { id: id + "~in", source: e.src, target: e.dst } });
        ele.style("opacity", ms ? 0 : 1);
      }
      // cited highlighting (recomputed every time: citations arrive at the end)
      cy.elements().removeClass("cited");
      for (const id of cited.nodes) cy.getElementById(id).addClass("cited");
      for (const id of cited.edges) cy.getElementById(id).addClass("cited");
    });
    order = graph.nodeOrder.slice();
    if (ms) {
      cy.elements().filter((e) => e.style("opacity") == 0).forEach((e, i) => e.animate({ style: { opacity: 1 } }, { duration: ms, queue: false, easing: "ease-out" }));
    }
    if (newNodeIds.length) fitSoon();
  }

  let fitTimer = null;
  function fitSoon() {
    clearTimeout(fitTimer);
    fitTimer = setTimeout(() => fit(), 60);
  }
  function fit() {
    if (cy.nodes().length === 0) return;
    const ms = motionMs();
    const opts = { eles: cy.nodes(), padding: 40 };
    if (ms) cy.animate({ fit: opts }, { duration: ms });
    else cy.fit(opts.eles, opts.padding);
    if (cy.zoom() > 1.3) cy.zoom({ level: 1.3, renderedPosition: { x: cy.width() / 2, y: cy.height() / 2 } });
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

  return {
    cy,
    sync,
    select,
    fit,
    move,
    resize() { cy.resize(); },
    zoom(f) { cy.zoom({ level: Math.max(0.2, Math.min(2.5, cy.zoom() * f)), renderedPosition: { x: cy.width() / 2, y: cy.height() / 2 } }); },
    pan(dx, dy) { cy.panBy({ x: dx, y: dy }); },
    clear() { cy.elements().remove(); for (const k in positions) delete positions[k]; selected = null; order = []; },
    restyle() { cy.style(styleSheet()); },
    center(id) { const e = cy.getElementById(id); if (e.length) cy.animate({ center: { eles: e } }, { duration: motionMs() }); },
  };
}
