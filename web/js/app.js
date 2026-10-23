// Detective Board UI: wiring between the pure modules, the DOM and the API.
import { askStream, getHealth, getEntities, getSubgraph, getSource, friendlyError } from "./api.js";
import { initialState, reduce, answerText, waitingStage, emptyGraph, boardGraph, citedBoard, progressSteps } from "./state.js";
import { traceRows, TYPE_LABEL, fmtSeconds, healthSummary } from "./trace.js";
import { splitHighlights, parseAnswer } from "./highlight.js";
import { normaliseRecording, playReplay, safeReplayPath } from "./replay.js";
import { createGraph, isDerived, KIND_GLYPH, KIND_WORD } from "./graph.js";

// replaceChildren() would print the text "null" for skipped optional children; drop them.
const _replace = Element.prototype.replaceChildren;
Element.prototype.replaceChildren = function (...kids) { return _replace.apply(this, kids.flat().filter((k) => k != null && k !== false)); };
const $ = (id) => document.getElementById(id);
function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const k in attrs || {}) {
    const v = attrs[k];
    if (v === false || v == null) continue;
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat()) if (kid != null && kid !== false) el.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
  return el;
}
const store = {
  get(k, d) { try { const v = localStorage.getItem(k); return v === null ? d : v; } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch { /* storage may be blocked */ } },
};

const params = new URLSearchParams(location.search);
const replayPath = safeReplayPath(params.get("replay"));
const replayRequested = params.has("replay");
const recordMode = params.get("record") === "1";
const replayOpts = { speed: Number(params.get("speed")) || 1, cap: params.has("cap") ? Number(params.get("cap")) * 1000 : Infinity };

// ---------------------------------------------------------------- state

let state = initialState();
let seeds = new Set();
let sel = null; // {kind: node|edge|citation|chunk, id}
let abortCtl = null;
let recorded = [];
let lastQuestion = "";
let health = null;
let renderQueued = false;
const traceDom = new Map();
let pinned = true;

function dispatch(action) {
  state = reduce(state, action);
  if (action.type === "event") {
    if (action.event.type === "graph_results") for (const s of action.event.seeds || []) seeds.add(String(s));
    if (action.event.type === "tool_result" && action.event.explanation) followEvidence(action.event.explanation, state.runId);
  }
  queueRender();
}
function queueRender() {
  if (renderQueued) return;
  renderQueued = true;
  requestAnimationFrame(() => { renderQueued = false; render(); });
}

// ---------------------------------------------------------------- settings

function applyTheme(t) {
  const root = document.documentElement;
  if (t === "light" || t === "dark") root.setAttribute("data-theme", t); else root.removeAttribute("data-theme");
  $("theme-btn").textContent = `Theme: ${t}`;
  $("theme-btn").setAttribute("aria-label", `Theme: ${t}. Activate to change.`);
  store.set("db-theme", t);
  if (graph) requestAnimationFrame(() => graph.restyle());
}
function applyMotion(on) {
  const root = document.documentElement;
  if (on) root.removeAttribute("data-motion"); else root.setAttribute("data-motion", "off");
  $("motion-btn").textContent = `Motion: ${on ? "on" : "off"}`;
  $("motion-btn").setAttribute("aria-pressed", String(on));
  store.set("db-motion", on ? "on" : "off");
}
$("theme-btn").addEventListener("click", () => {
  const order = ["auto", "light", "dark"];
  applyTheme(order[(order.indexOf(store.get("db-theme", "auto")) + 1) % 3]);
});
$("motion-btn").addEventListener("click", () => applyMotion(document.documentElement.hasAttribute("data-motion")));
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => graph && graph.restyle());

// ---------------------------------------------------------------- graph

let graph = null;
try {
  graph = createGraph($("cy"), {
    onSelect: (s) => select(s),
    onDoubleSelect: (s) => expandNode(s.id),
  });
} catch (e) {
  $("board-empty").textContent = "The graph view could not start in this browser. Use the list view (g).";
}

function select(s) {
  sel = s;
  if (graph) graph.select(s && (s.kind === "node" || s.kind === "edge") ? s : null);
  renderSelection();
  renderListView();
  renderAnswer();
}

async function expandNode(id) {
  try {
    const sub = await getSubgraph(id, 1);
    seeds.add(id);
    dispatch({ type: "graph_merge", nodes: sub.nodes, edges: sub.edges });
    banner(null);
  } catch (e) { banner(friendlyError(e)); }
}

// A rule finding names the people and facts it rests on. Pin their neighbourhood on the board
// (the router does not run a graph query for a contradiction question), one card at a time.
const factNeighbours = new Map();
async function followEvidence(expl, runId) {
  const speaker = expl.subject && expl.subject.speaker_id;
  const jobs = [];
  if (speaker) jobs.push([speaker, 2]);
  for (const f of expl.facts || []) if (f.kind === "event") jobs.push([f.fact_id, 1]);
  const done = new Set();
  const run = async ([id, hops]) => {
    if (done.has(id + hops)) return;
    done.add(id + hops);
    try {
      const sub = await getSubgraph(id, hops);
      if (state.runId !== runId) return; // a newer run owns the board now
      if (speaker && id === speaker) seeds.add(speaker);
      dispatch({ type: "graph_merge", nodes: sub.nodes, edges: sub.edges });
      return sub;
    } catch { return null; }
  };
  for (const j of jobs) await run(j);
  // the other people who took part in the contradicting event (e.g. the witness)
  for (const f of expl.facts || []) {
    if (f.kind !== "event" || state.runId !== runId) continue;
    for (const eid of state.graph.edgeOrder) {
      const e = state.graph.edges[eid];
      if (e.dst === f.fact_id && e.rel === "PARTICIPATED_IN" && e.src !== speaker) await run([e.src, 1]);
    }
  }
}

const DEMO_QUESTIONS = [
  "Are there contradictions in James McCarthy's account?",
  "What is a swamp adder?",
  "What is the weather in Paris today?",
];
$("demo-chips").replaceChildren(...DEMO_QUESTIONS.map((q) => h("button", { type: "button", title: q, onclick: () => { if (state.phase === "running" || replayPath) return; $("question").value = q; runLive(q); } }, q.length > 38 ? q.slice(0, 36).trimEnd() + "\u2026" : q)));

// ---------------------------------------------------------------- run control

const history = (() => { try { return JSON.parse(store.get("db-history", "[]")).slice(0, 20); } catch { return []; } })();
function saveHistory(entry) {
  history.unshift(entry);
  history.length = Math.min(history.length, 20);
  store.set("db-history", JSON.stringify(history));
  renderHistory();
}
function renderHistory() {
  $("history-count").textContent = `(${history.length})`;
  const ol = $("history-list");
  ol.replaceChildren(...history.map((e) => h("li", null, h("button", { type: "button", onclick: () => { $("question").value = e.question; $("history").open = false; $("question").focus(); } }, e.question), h("span", { class: "muted" }, ` ${e.status}`))));
  if (!history.length) ol.replaceChildren(h("li", { class: "muted" }, "No questions yet."));
}
$("history-clear").addEventListener("click", () => { history.length = 0; store.set("db-history", "[]"); renderHistory(); });
$("use-history").checked = store.get("db-use-history", "0") === "1";
$("use-history").addEventListener("change", (e) => store.set("db-use-history", e.target.checked ? "1" : "0"));

function historyPayload() {
  if (!$("use-history").checked) return [];
  return history.filter((e) => e.status === "answered" && e.answer).slice(0, 3).reverse().map((e) => ({ question: e.question.slice(0, 2000), answer: e.answer.slice(0, 2000) }));
}

async function runLive(question) {
  stop(true);
  lastQuestion = question;
  recorded = [];
  banner(null);
  resetBoard();
  dispatch({ type: "run_start", question, mode: "live", now: Date.now(), keepGraph: $("keep-graph").checked });
  abortCtl = new AbortController();
  const ctl = abortCtl;
  try {
    for await (const ev of askStream(question, historyPayload(), { signal: ctl.signal })) {
      recorded.push(ev);
      dispatch({ type: "event", event: ev, now: Date.now() });
    }
    dispatch({ type: "stream_end", now: Date.now() });
  } catch (e) {
    const fe = friendlyError(e);
    if (fe.kind === "aborted") return;
    if (fe.kind === "busy") {
      dispatch({ type: "reset" });
      banner({ ...fe, retry: () => runLive(question) });
    } else {
      dispatch({ type: "event", event: { type: "run_error", code: "unavailable", message: fe.text }, now: Date.now() });
      banner({ kind: fe.kind === "input" ? "input" : "error", text: fe.text, retry: () => runLive(question) });
    }
  } finally {
    if (abortCtl === ctl) abortCtl = null;
    onRunEnd();
  }
}

async function runReplay() {
  stop(true);
  recorded = [];
  banner(null);
  resetBoard();
  let rec;
  try {
    const res = await fetch(replayPath);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    rec = normaliseRecording(await res.json());
  } catch (e) {
    banner({ kind: "error", text: `Cannot load the recording "${replayPath}": ${e.message}`, retry: runReplay });
    return;
  }
  const q = rec.meta.question || "(recorded run)";
  $("question").value = q;
  dispatch({ type: "run_start", question: q, mode: "replay", now: Date.now() });
  abortCtl = new AbortController();
  const ctl = abortCtl;
  for await (const ev of playReplay(rec.events, { ...replayOpts, signal: ctl.signal })) dispatch({ type: "event", event: ev, now: Date.now() });
  if (!ctl.signal.aborted) dispatch({ type: "stream_end", now: Date.now() });
  if (abortCtl === ctl) abortCtl = null;
  onRunEnd();
}

function stop(silent) {
  if (abortCtl) { abortCtl.abort(); abortCtl = null; }
  if (state.phase === "running") dispatch({ type: "cancel", now: Date.now() });
  if (!silent) onRunEnd();
}

let autoOpened = null;
function resetBoard() {
  sel = null;
  autoOpened = null;
  seeds = new Set();
  traceDom.clear();
  $("trace").replaceChildren();
  if (graph && !$("keep-graph").checked) graph.clear();
  $("source").replaceChildren(h("p", { class: "empty" }, "Click a citation marker, a graph node or edge, or a trace hit to see the quote in its source chunk."));
}

function onRunEnd() {
  queueRender();
  if (state.mode === "live" && lastQuestion && state.phase !== "idle") {
    const f = state.final;
    saveHistory({ question: lastQuestion, status: f ? f.status : state.phase, answer: f && f.status !== "refused" ? f.answer : "" });
  }
  refreshHealth();
}

$("ask-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const q = $("question").value.trim();
  if (!q || state.phase === "running") return;
  if (replayPath) return;
  runLive(q);
});
$("stop-btn").addEventListener("click", () => stop(false));
$("keep-graph").addEventListener("change", () => {});
$("save-run").addEventListener("click", () => {
  const blob = new Blob([JSON.stringify({ meta: { question: lastQuestion, recorded_at: new Date().toISOString(), fake: !!(health && health.fake) }, events: recorded }, null, 1)], { type: "application/json" });
  const a = h("a", { href: URL.createObjectURL(blob), download: `run-${Date.now()}.json` });
  document.body.append(a); a.click(); a.remove();
});

function banner(b) {
  const el = $("banner");
  if (!b) { el.hidden = true; el.replaceChildren(); return; }
  el.hidden = false;
  el.dataset.kind = b.kind;
  const icon = b.kind === "busy" ? "⏳" : b.kind === "input" ? "⚠" : "✖";
  el.replaceChildren(h("span", { "aria-hidden": "true" }, icon), h("span", null, b.text), b.retry ? h("button", { type: "button", onclick: () => { banner(null); b.retry(); } }, "Try again") : null, h("button", { type: "button", onclick: () => banner(null), "aria-label": "Dismiss" }, "×"));
}

// ---------------------------------------------------------------- render

function render() {
  renderTop();
  renderProgress();
  renderTrace();
  renderAnswer();
  renderGraphView();
  renderStrip();
}

function renderTop() {
  const running = state.phase === "running";
  $("ask-btn").hidden = running;
  $("stop-btn").hidden = !running;
  $("question").disabled = !!replayPath;
  for (const c of $("demo-chips").children) c.disabled = running || !!replayPath;
  $("try-label").hidden = $("demo-chips").hidden = !!replayPath;
  const b = $("run-badge");
  const label = state.phase === "idle" && !replayRequested ? "IDLE" : state.mode === "replay" || (replayRequested && state.phase === "idle") ? "REPLAY" : "LIVE";
  b.textContent = label === "REPLAY" ? "RECORDING" : label;
  b.className = "badge " + (label === "REPLAY" ? "badge-replay" : label === "LIVE" ? "badge-live" : "badge-idle");
  b.title = label === "REPLAY" ? "RECORDING: a stored run is being played back, it is not computed now." : label === "LIVE" ? "This run is being computed now." : "No run yet.";
  $("rec-badge").hidden = !(recordMode && state.mode === "live" && state.phase !== "idle");
  $("save-run").hidden = !(state.mode === "live" && recorded.length && !running);
  const rn = $("replay-note");
  rn.hidden = !replayRequested;
  rn.textContent = replayRequested ? `Recording playback: ${replayPath || "invalid path"}${replayOpts.speed !== 1 ? ` at ${replayOpts.speed}x` : " at original timing"}. ` : "";
  if (replayRequested && !running) { rn.append(h("button", { type: "button", onclick: () => replayPath && runReplay() }, "Play again")); }
  const chips = $("route-chips");
  const routes = state.route ? state.route.routes : [];
  chips.replaceChildren(...routes.map((r) => h("span", { class: "chip", title: state.route.reason }, `${r.toUpperCase()} (${state.route.method})`)));
}

function renderTrace() {
  const rows = traceRows(state.events);
  const ol = $("trace");
  $("trace-empty").hidden = rows.length > 0;
  $("trace-count").textContent = rows.length ? `(${rows.length})` : "";
  const seen = new Set();
  for (const r of rows) {
    seen.add(r.key);
    let entry = traceDom.get(r.key);
    if (!entry) {
      entry = makeRow(r);
      traceDom.set(r.key, entry);
      ol.append(entry.li);
    }
    updateRow(entry, r);
  }
  for (const [k, e] of traceDom) if (!seen.has(k)) { e.li.remove(); traceDom.delete(k); }
  if (pinned) { const p = $("panel-trace"); p.scrollTop = p.scrollHeight; }
  $("jump-latest").hidden = pinned || rows.length === 0;
  const w = $("working");
  const stage = waitingStage(state, Date.now());
  if (!stage) w.hidden = true;
  else {
    w.hidden = false;
    const txt = stage.kind === "writing" ? `Writing the answer (${rate()})` : stage.kind === "first_token" ? `Waiting for the first token: ${stage.seconds} s (CPU generation is slow; evidence is already on screen)` : `Working: ${stage.seconds} s since the last step${stage.seconds >= 3 ? " (still working, waiting for the next step)" : ""}`;
    w.replaceChildren(h("span", { class: "dots" }, txt));
  }
}
function rate() {
  if (state.firstTokenAt === null || state.answer.tokens < 2) return "~ tok/s: -";
  const secs = ((state.endedAt || Date.now()) - state.firstTokenAt) / 1000;
  return secs > 0.2 ? `~${(state.answer.tokens / secs).toFixed(1)} tok/s` : "~ tok/s: -";
}

const GLYPH = { ok: "\u2713", running: "\u2026", warn: "\u25B2", error: "\u2716", info: "\u25C6" };
// 24x24 line icons, one per kind of step (shape, not colour, tells the steps apart)
const TICON = {
  route_decided: "M5 4v6a4 4 0 0 0 4 4h6M5 4L3 6M5 4l2 2M15 14l-3-3M15 14l-3 3M19 20v-6",
  retrieval_started: "M10 3a7 7 0 1 0 0 14 7 7 0 0 0 0-14zM15 15l6 6",
  retrieval_results: "M10 3a7 7 0 1 0 0 14 7 7 0 0 0 0-14zM15 15l6 6M7 10l2 2 4-4",
  graph_query: "M6 6h.01M18 8h.01M12 18h.01M6 6l6 12M18 8L6 6M18 8l-6 10",
  graph_results: "M6 6h.01M18 8h.01M12 18h.01M6 6l6 12M18 8L6 6M18 8l-6 10",
  tool_call: "M14 4a5 5 0 0 0-4 7l-7 7 3 3 7-7a5 5 0 0 0 7-4l-3 3-3-3 3-3z",
  tool_result: "M14 4a5 5 0 0 0-4 7l-7 7 3 3 7-7a5 5 0 0 0 7-4l-3 3-3-3 3-3z",
  enriched_query: "M12 3l9 5-9 5-9-5zM3 13l9 5 9-5M3 17l9 5 9-5",
  answer_token: "M4 20l4-1L19 8l-3-3L5 16zM14 7l3 3",
  citation_check: "M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6zM8.5 12l2.5 2.5 4.5-5",
  refusal: "M12 3l6 0 3 6v6l-3 6H6l-3-6V9l3-6zM8 12h8",
  final: "M5 21V4M5 4h12l-2 4 2 4H5",
  run_error: "M12 3l10 18H2zM12 10v5M12 18h.01",
  parse_error: "M12 3l10 18H2zM12 10v5M12 18h.01",
};
function ticon(type) {
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", "0 0 24 24"); svg.setAttribute("class", "ticon"); svg.setAttribute("aria-hidden", "true");
  const p = document.createElementNS(ns, "path");
  p.setAttribute("d", TICON[type] || "M12 4v16M4 12h16");
  p.setAttribute("fill", "none"); p.setAttribute("stroke", "currentColor"); p.setAttribute("stroke-width", "2"); p.setAttribute("stroke-linecap", "round"); p.setAttribute("stroke-linejoin", "round");
  svg.append(p);
  return svg;
}
function makeRow(r) {
  const li = h("li", { class: "new" });
  const det = h("details", null);
  const sum = h("summary", null, h("span", { class: "glyph" }), h("span", { class: "ticon-box" }, ticon(r.type)), h("span", { class: "head" }, h("span", { class: "type" }), h("span", { class: "when" }), h("span", { class: "dur" })), h("span", { class: "sum" }));
  const body = h("div", { class: "body" });
  det.append(sum, body);
  li.append(det);
  return { li, det, sum, body, version: -1 };
}
function sinceStart(r) {
  const t0 = state.events.length ? Date.parse(state.events[0].ts) : NaN;
  const t = Date.parse(r.ts || (r.firstTs));
  return Number.isFinite(t0) && Number.isFinite(t) ? `+${((t - t0) / 1000).toFixed(1)} s` : "";
}
function updateRow(e, r) {
  const [g, , head, sm] = e.sum.children;
  const when = head.children[1];
  g.textContent = GLYPH[r.status] || "\u2022";
  g.className = "glyph " + r.status;
  g.setAttribute("aria-label", r.status);
  e.li.dataset.status = r.status;
  head.children[0].textContent = TYPE_LABEL[r.type] || r.type;
  head.children[2].textContent = r.duration != null ? fmtSeconds(r.duration) : "";
  sm.textContent = r.summary;
  when.textContent = sinceStart(r);
  const v = r.raw.length + ":" + r.status + ":" + (r.count || 0);
  if (e.version === v) return;
  e.version = v;
  const kids = [];
  if (r.corpus) kids.push(h("div", null, h("span", { class: "tag" }, "corpus text = data")));
  if (r.lines.length) kids.push(h("dl", null, r.lines.flatMap(([k, val]) => [h("dt", null, k), h("dd", null, String(val))])));
  if (r.list.length) kids.push(h("ul", null, r.list.map((it) => h("li", null, it.chunk_id ? h("button", { type: "button", class: "hit", onclick: () => showChunk(it.chunk_id) }, it.text) : it.text))));
  kids.push(h("details", null, h("summary", null, "raw"), h("pre", null, r.raw.length > 6 ? `${r.raw.length} events; first and last:\n` + JSON.stringify([r.raw[0], r.raw.at(-1)], null, 1) : JSON.stringify(r.raw.length === 1 ? r.raw[0] : r.raw, null, 1))));
  e.body.replaceChildren(...kids);
}
$("panel-trace").addEventListener("scroll", () => {
  const p = $("panel-trace");
  pinned = p.scrollHeight - p.scrollTop - p.clientHeight < 40;
  $("jump-latest").hidden = pinned || traceDom.size === 0;
});
$("jump-latest").addEventListener("click", jumpLatest);
function jumpLatest() { pinned = true; const p = $("panel-trace"); p.scrollTop = p.scrollHeight; $("jump-latest").hidden = true; }

// ---------------------------------------------------------------- progress card

function renderProgress() {
  const box = $("progress");
  const running = state.phase === "running";
  const finished = state.phase === "done" && state.startedAt;
  box.hidden = !(running || finished);
  box.classList.toggle("done", !running);
  if (box.hidden) return;
  const steps = progressSteps(state, Date.now());
  const elapsed = (((running ? Date.now() : state.endedAt || Date.now()) - state.startedAt) / 1000);
  if (!running) {
    const n = steps.filter((x) => x.status === "done").length;
    box.replaceChildren(h("span", { class: "summary" }, `\u2713 Done in ${elapsed.toFixed(1)} s`), h("span", { class: "muted" }, ` / ${n} steps / ${state.mode === "replay" ? "recorded run" : "live run"}`));
    return;
  }
  const active = steps.find((x) => x.status === "active");
  const pre = steps.find((x) => x.key === "prefill");
  const bar = active && active.key === "prefill" && pre.est ? Math.min(95, (pre.elapsed / pre.est) * 100) : null;
  box.replaceChildren(
    h("div", { class: "top" }, h("div", { class: "what" }, active ? active.label + "\u2026" : "Working\u2026"), h("div", { class: "elapsed", "aria-hidden": "true" }, `${elapsed.toFixed(1)} s`)),
    bar !== null ? h("div", { class: "bar-track", role: "progressbar", "aria-label": "Estimated time the model needs to read the evidence", "aria-valuemin": 0, "aria-valuemax": 100, "aria-valuenow": Math.round(bar) }, fillBar(bar)) : null,
    active && active.key === "prefill" ? h("p", { class: "note" }, `This CPU reads about ${PREFILL} evidence tokens a second before the first word. The evidence is already on the board and in the trace; the estimate is not a promise.`) : null,
    h("ol", null, steps.map((x) => h("li", { "data-status": x.status }, h("span", { class: "mark", "aria-hidden": "true" }, x.status === "done" ? "\u2713" : x.status === "skipped" ? "\u2013" : x.status === "active" ? "" : "\u25CB"), h("span", null, x.label, h("span", { class: "sr" }, ` (${x.status})`)), h("span", { class: "det" }, x.detail)))));
}
const PREFILL = "14";
// The page's CSP forbids a style attribute; the CSSOM is allowed.
function fillBar(pct) { const f = h("div", { class: "bar-fill" }); f.style.width = `${pct.toFixed(0)}%`; return f; }

// ---------------------------------------------------------------- answer panel

const PROV_GLYPH = { extracted: "~", derived: "=", conditional: "=?", source_text: "\u201C\u201D" };
export function provBadge(label, conf) {
  const g = PROV_GLYPH[label] || "?";
  const t = { extracted: "extracted: model output, probabilistic", derived: "derived: produced by a deterministic rule", conditional: "conditional: derived, but rests on a doubtful extracted fact", source_text: "source text: verbatim from the book" }[label] || label;
  return h("span", { class: `prov prov-${label}`, title: t }, h("span", { "aria-hidden": "true" }, g), label + (conf ? ` (${conf})` : ""));
}

function statusInfo() {
  const f = state.final;
  switch (state.phase) {
    case "idle": return { cls: "st-run", icon: "○", text: "Ready" };
    case "running": return { cls: "st-run", icon: "…", text: "Investigating..." };
    case "cancelled": return { cls: "st-error", icon: "■", text: "Stopped" };
    case "error": return { cls: "st-error", icon: "✖", text: "Error" };
    default:
      if (f.status === "refused") return { cls: "st-refused", icon: "◆", text: f.refusal_code === "out_of_scope" || f.refusal_code === "no_evidence" ? "Refusal: not in the corpus" : `Refusal: ${f.refusal_code || "no answer"}` };
      if (f.status === "partial") return { cls: "st-partial", icon: "▲", text: "Partial answer: part unknown" };
      return { cls: f.verified ? "st-done" : "st-partial", icon: f.verified ? "✓" : "▲", text: f.verified ? "Answer (verified)" : "Answer (not verified)" };
  }
}

function citationFor(n) {
  const f = state.final;
  return f && f.citations.find((c) => c.n === n);
}
function sourceFor(n) {
  return state.sources.find((s) => s.n === n);
}

function renderAnswer() {
  const si = statusInfo();
  $("status-line").replaceChildren(h("span", { class: `st ${si.cls}` }, h("span", { "aria-hidden": "true" }, si.icon + " "), si.text), state.final && state.final.status !== "refused" ? h("span", { class: "muted" }, verifiedText()) : null);
  const text = answerText(state);
  const ans = $("answer");
  const finalDone = !!state.final;
  ans.className = "answer" + (finalDone ? "" : " draft");
  const notes = [];
  if (state.phase === "running" && text) notes.push("draft, not yet verified");
  if (state.answer.discardedAttempts > 0) notes.push(`attempt ${state.answer.attempt}: ${state.answer.discardedTokens} tokens of a failed attempt were dropped`);
  if (state.phase === "error" && text && !finalDone) notes.push("the run failed; this partial draft is unverified");
  $("answer-note").textContent = notes.join(" / ");
  $("answer-idle").hidden = state.phase !== "idle";
  ans.replaceChildren(...parseAnswer(text).map((seg) => {
    if (seg.t === "text") return document.createTextNode(seg.s);
    const wrap = document.createElement("span");
    seg.ns.forEach((n, i) => {
      const c = citationFor(n);
      const can = c || sourceFor(n);
      const pv = state.final && state.final.provenance.find((x) => x.n === n);
      const lab = (pv && pv.label) || (c && c.label) || "";
      const b = h("button", { type: "button", class: "cite " + lab + (c ? "" : " unverified"), disabled: !can, "aria-label": `Citation ${n}${lab ? `, ${lab}` : ""}${c ? `: ${c.anchor.chunk_id}` : " (not yet verified)"}`, title: c ? `${c.anchor.chunk_id}${lab ? " / " + lab : ""}` : "unverified", onclick: () => openCitation(n) }, h("span", { class: "g", "aria-hidden": "true" }, PROV_GLYPH[lab] || ""), `${n}`);
      if (sel && sel.kind === "citation" && sel.id === n) b.style.outline = "3px solid var(--db-selected-ring)";
      wrap.append(b);
      if (i < seg.ns.length - 1) wrap.append(" ");
    });
    return wrap;
  }));
  renderEvidence();
}

function verifiedText() {
  const f = state.final;
  const ck = state.checks.at(-1);
  if (!ck || !ck.citations.length) return f.verified ? "all claims verified" : "";
  const good = ck.citations.filter((c) => c.verbatim && c.source_exists).length;
  return `${good} of ${ck.citations.length} quotes verified`;
}

function renderEvidence() {
  const box = $("evidence");
  const rf = $("refusal");
  const f = state.final;
  const cards = [];
  if (f && f.status !== "refused") {
    f.citations.forEach((c, i) => {
      const p = f.provenance.find((x) => x.n === c.n);
      const label = (p && p.label) || c.label;
      const expl = p && (label === "derived" || label === "conditional") ? explanationForProv(p) : null;
      const pair = f.citations.length === 2;
      cards.push(h("div", { class: "card" + (sel && sel.kind === "citation" && sel.id === c.n ? " sel" : "") + (i === 1 && pair ? " b" : "") },
        h("div", { class: "meta" }, pair ? h("span", { class: "ab " + (i ? "b" : "a"), title: i ? "B: second quote of the pair" : "A: first quote of the pair" }, i ? "B" : "A") : null, h("strong", null, `[${c.n}]`), provBadge(label, p && p.confidence), h("span", null, `${c.anchor.story} / ${c.anchor.chunk_id}`),
          state.checks.length ? h("span", { title: "checked against the chunk text" }, (state.checks.at(-1).citations.find((x) => x.n === c.n) || {}).verbatim ? "✓ verbatim" : "? not confirmed") : null),
        h("blockquote", null, c.quote),
        p && p.summary ? h("div", { class: "muted" }, p.summary) : null,
        h("div", null, h("button", { type: "button", class: "open", onclick: () => openCitation(c.n) }, "Show in source"), " ",
          label === "derived" || label === "conditional" ? h("button", { type: "button", class: "open", onclick: () => { sel = { kind: "citation", id: c.n }; showWhy(expl, p, c); renderAnswer(); } }, "Why?") : null)));
    });
  } else if (!f && state.hits.length) {
    cards.push(h("div", { class: "muted" }, "Candidate evidence (retrieved, not yet used in the answer)"));
    for (const hit of state.hits.slice(0, 5)) {
      cards.push(h("div", { class: "card candidate" }, h("div", { class: "meta" }, h("strong", null, `#${hit.rank}`), provBadge("source_text"), h("span", null, `${hit.story} / ${hit.chunk_id}`), h("span", null, Object.entries(hit.ranks || {}).map(([k, v]) => `${k} #${v}`).join(", "))), h("button", { type: "button", class: "open", onclick: () => showChunk(hit.chunk_id) }, "Show chunk")));
    }
  }
  box.replaceChildren(...cards);
  if (f && f.status === "refused" && state.refusal) {
    const r = state.refusal;
    rf.hidden = false;
    rf.replaceChildren(h("strong", null, "Not in the corpus"), h("p", null, r.message), r.missing.length ? h("p", null, "Missing: " + r.missing.join(", ")) : null, h("p", null, "Searched: " + (r.searched.join("; ") || "-")),
      state.hits.length ? h("details", null, h("summary", null, `Nearest chunks, rejected as unrelated (${state.hits.length})`), h("ul", null, state.hits.map((x) => h("li", null, h("button", { type: "button", class: "hit", onclick: () => showChunk(x.chunk_id) }, x.chunk_id))))) : null);
  } else if (state.phase === "error") {
    rf.hidden = false;
    rf.replaceChildren(h("strong", null, "The run failed"), h("p", null, errorText(state.error)));
  } else rf.hidden = true;
}

function errorText(e) {
  if (!e) return "";
  const m = { unavailable: "The language model or the index is unavailable.", timeout: "The run took too long and was stopped.", internal: "The agent hit an internal error.", connection_lost: "The connection to the agent was lost." }[e.code];
  return `${m || "The run failed."} ${e.message && !m ? e.message : ""}`.trim() + (m && e.message && e.code !== "connection_lost" ? ` (${e.message})` : "");
}

// ---------------------------------------------------------------- source and "Why?" panel

let srcToken = 0;
const srcCache = new Map();

async function fetchSource(it) {
  const key = JSON.stringify([it.chunk_id, it.quote, it.start, it.end]);
  if (srcCache.has(key)) return srcCache.get(key);
  const data = await getSource(it.chunk_id, { quote: it.quote, start: it.start, end: it.end });
  srcCache.set(key, data);
  return data;
}

function passageEl(data, variant, label) {
  const segs = splitHighlights(data.text, data.highlights);
  const exact = data.highlights.every((x) => x.match === "exact" || x.match === "offsets");
  return h("div", null,
    h("div", { class: "hdr" }, h("span", { class: "tag" }, "corpus text"), ` ${data.story} / ${data.chunk_id} / chars ${data.char_start}-${data.char_end}`, label ? ` / ${label}` : "", !data.highlights.length ? " / quote not located in this chunk" : !exact ? " / whitespace-normalised match" : "", data.contiguous ? "" : " / non-contiguous chunk"),
    h("div", { class: "passage" + (variant === "b" ? " b" : "") }, segs.map((s) => (s.hl ? h("mark", null, s.text) : s.text))));
}

async function showSources(header, items) {
  const token = ++srcToken;
  const box = $("source");
  box.replaceChildren(...header, h("p", { class: "muted" }, "Loading source..."));
  try {
    const datas = await Promise.all(items.map(fetchSource));
    if (token !== srcToken) return;
    box.replaceChildren(...header, ...datas.map((d, i) => passageEl(d, i === 1 ? "b" : "a", items[i].label)));
  } catch (e) {
    if (token !== srcToken) return;
    const fe = friendlyError(e);
    box.replaceChildren(...header, h("p", { class: "empty" }, `Source unavailable: ${fe.text}`));
  }
}

function showChunk(chunkId, extra = {}) {
  sel = { kind: "chunk", id: chunkId };
  showSources([], [{ chunk_id: chunkId, ...extra }]);
}

function anchorItem(a, label) {
  return { chunk_id: a.chunk_id, start: a.char_start, end: a.char_end, quote: a.quote, label };
}

function openCitation(n) {
  sel = { kind: "citation", id: n };
  const c = citationFor(n);
  const s = sourceFor(n);
  if (c) showSources([h("h3", null, `Citation [${n}]`)], [anchorItem(c.anchor)]);
  else if (s) showSources([h("h3", null, `Source [${n}] (not yet verified)`)], [{ chunk_id: s.chunk_id, start: s.char_start, end: s.char_end }]);
  if (graph) graph.select(null);
  renderAnswer();
}

function explanationForProv(p) {
  if (p && p.explanation) return p.explanation;
  for (const f of state.findings) if (f.explanation && (!p.rule_id || f.explanation.rule_id === p.rule_id)) return f.explanation;
  for (const id of state.graph.edgeOrder) {
    const e = state.graph.edges[id];
    const x = e.explanation || (e.props && e.props.explanation);
    if (x && (!p.rule_id || x.rule_id === p.rule_id)) return x;
  }
  return null;
}

// Explanation object: docs/symbolic-layer.md section 3.1.
export function showWhy(expl, prov, cite) {
  const head = [h("h3", null, "Why? ", provBadge((prov && prov.label) || (expl && (expl.conditional ? "conditional" : "derived")) || "derived"))];
  if (!expl) {
    $("source").replaceChildren(...head, h("p", { class: "empty" }, "No explanation is attached to this derived item, so it cannot be shown as a finding. " + (prov && prov.summary ? `(Label summary: ${prov.summary})` : "")), cite ? h("button", { type: "button", onclick: () => openCitation(cite.n) }, "Show the cited quote instead") : null);
    return;
  }
  const out = [...head, h("p", null, h("strong", null, `Rule ${expl.rule_id}`), expl.rule_version ? ` v${expl.rule_version}` : "", ` / verdict ${expl.verdict} / ${expl.reason_code}`)];
  const weak = new Set(expl.weak || []);
  if (expl.conditional) {
    out.push(h("div", { class: "doubt" }, h("strong", null, "This depends on a low-confidence extraction. "), (expl.depends_on_extracted || []).filter((d) => weak.has(d.fact_id) || d.confidence === "low").map((d) => `${d.fact_id} (${d.confidence})`).join(", ") || [...weak].join(", ")));
  }
  const facts = [...(expl.facts || [])].sort((a, b) => (weak.has(b.fact_id) ? 1 : 0) - (weak.has(a.fact_id) ? 1 : 0));
  out.push(h("h3", null, "Facts used"), h("ol", null, facts.map((f) => h("li", null, provBadge(f.provenance || "extracted", f.confidence), ` ${f.summary || f.fact_id}`, weak.has(f.fact_id) ? " (doubtful input)" : "", (f.anchors || []).map((a) => h("div", { class: "anchor" }, h("blockquote", null, a.quote), h("button", { type: "button", onclick: () => showSources([h("h3", null, `Why? / ${f.fact_id}`)], [anchorItem(a)]) }, `${a.chunk_id}: show in chunk`)))))));
  if ((expl.edges || []).length) out.push(h("h3", null, "Edges used"), h("ul", null, expl.edges.map((e) => h("li", null, `${e.src} -[${e.rel}]-> ${e.dst}`, (e.anchors || []).map((a) => h("div", { class: "anchor" }, h("blockquote", null, a.quote)))))));
  out.push(h("h3", null, "Derivation"), h("ol", null, (expl.derivation || []).map((s) => h("li", null, `${s.op}(${(s.inputs || []).join(", ")}) → ${s.output}`))));
  if ((expl.missing || []).length) out.push(h("p", null, "Missing: " + expl.missing.join(", ")));
  if ((expl.notes || []).length) out.push(h("p", { class: "muted" }, expl.notes.join(" / ")));
  const box = $("source");
  srcToken++;
  box.replaceChildren(h("div", { class: "why" }, out));
}

async function renderSelection() {
  if (!sel) return;
  if (sel.kind === "node" && sel.id.startsWith("chunk:")) {
    const cid = sel.id.slice(6);
    const c = state.final && state.final.citations.find((x) => x.anchor.chunk_id === cid);
    showSources([h("h3", null, `${KIND_GLYPH.source} Source text`), h("div", { class: "meta" }, provBadge("source_text"), c ? " cited in the answer" : state.final && state.final.status === "refused" ? " retrieved, rejected as unrelated" : " retrieved")], [c ? anchorItem(c.anchor) : { chunk_id: cid }]);
    return;
  }
  if (sel.kind === "node") {
    const n = state.graph.nodes[sel.id];
    if (!n) return;
    const hdr = [h("h3", null, `${KIND_WORD[n.kind] || n.kind}: ${n.name}`), h("div", { class: "meta" }, n.confidence === "low" ? "tentative " : "", " ", provBadge(n.provenance || "extracted", n.confidence), n.story ? ` / ${n.story}` : "")];
    let anchors = n.anchors;
    if (!anchors || !anchors.length) {
      showSources(hdr, []);
      try {
        const sub = await getSubgraph(n.id, 0);
        const full = sub.nodes.find((x) => x.id === n.id);
        if (full) { dispatch({ type: "graph_merge", nodes: [full], edges: [] }); anchors = full.anchors; }
      } catch (e) { /* shown below */ }
      if (!sel || sel.id !== n.id) return;
    }
    if (!anchors || !anchors.length) { $("source").replaceChildren(...hdr, h("p", { class: "empty" }, "No source quote is available for this node.")); return; }
    showSources(hdr, anchors.slice(0, 3).map((a, i) => anchorItem(a, `mention ${i + 1} of ${n.anchor_total || anchors.length}`)));
  } else if (sel.kind === "edge") {
    const e = state.graph.edges[sel.id];
    if (!e) return;
    const s = state.graph.nodes[e.src], d = state.graph.nodes[e.dst];
    const label = e.provenance || "extracted";
    const hdr = [h("h3", null, `${s ? s.name : e.src}  —${e.rel}→  ${d ? d.name : e.dst}`), h("div", { class: "meta" }, provBadge(label, e.confidence), isDerived(e) ? h("button", { type: "button", onclick: () => showWhy(e.explanation || (e.props && e.props.explanation) || null, { label, summary: e.rel }) }, "Why?") : null)];
    if (isDerived(e)) showWhy(e.explanation || (e.props && e.props.explanation) || null, { label, summary: e.rel });
    else if (e.anchor) showSources(hdr, [anchorItem(e.anchor)]);
    else $("source").replaceChildren(...hdr, h("p", { class: "empty" }, "This edge has no anchor, so no quote can be shown."));
  }
}

// ---------------------------------------------------------------- graph view and list view

let lastGraphKey = "";
function emptyMsg(big, small) {
  const el = $("board-empty");
  el.replaceChildren(h("span", { class: "pinhint", "aria-hidden": "true" }), h("span", { class: "big" }, big), small);
}
function renderGraphView() {
  const g = boardGraph(state);
  const cited = citedBoard(g, state.final ? state.final.citations : []);
  const key = `${g.nodeOrder.length}:${g.edgeOrder.length}:${cited.nodes.size}:${cited.edges.size}:${state.final ? 1 : 0}`;
  $("board-empty").hidden = g.nodeOrder.length > 0;
  if (!g.nodeOrder.length && state.final) emptyMsg(state.final.status === "refused" ? "Nothing to pin" : "No cards for this answer", state.final.status === "refused" ? "The question is not covered by the corpus, so the board stays empty. The trace shows what was searched." : "It was answered from text search only; no graph nodes were used.");
  else if (!g.nodeOrder.length && state.phase === "running") emptyMsg("Looking for evidence\u2026", "Cards are pinned here the moment the agent finds them.");
  else if (!g.nodeOrder.length) emptyMsg("Ask a question", "Cards appear here, one by one, as the agent finds evidence.");
  $("graph-count").textContent = g.nodeOrder.length ? `(${g.nodeOrder.length} nodes / ${g.edgeOrder.length} edges)` : "";
  if (key !== lastGraphKey) {
    lastGraphKey = key;
    if (graph) graph.sync(g, cited, [...seeds]);
    renderListView();
    maybeAutoOpen();
  }
}

// When the answer lands, show its quote(s) in the source panel so the proof is on screen without a click.
function maybeAutoOpen() {
  const f = state.final;
  if (!f || sel || f.status === "refused" || !f.citations.length || autoOpened === state.runId) return;
  autoOpened = state.runId;
  if (f.citations.length === 2) {
    sel = { kind: "citation", id: f.citations[0].n };
    showSources([h("h3", null, "The two quotes side by side"), h("p", { class: "muted" }, "A and B come from different places in the story.")], f.citations.map((c, i) => anchorItem(c.anchor, i ? "B" : "A")));
  } else openCitation(f.citations[0].n);
}

let listMode = false;
function setListMode(on) {
  listMode = on;
  $("list-view").hidden = !on;
  $("view-toggle").setAttribute("aria-pressed", String(on));
  $("view-toggle").textContent = on ? "Graph view (g)" : "List view (g)";
  renderListView();
  if (!on && graph) graph.resize();
}
$("view-toggle").addEventListener("click", () => setListMode(!listMode));
function renderListView() {
  if (!listMode) return;
  const g = boardGraph(state);
  const cited = citedBoard(g, state.final ? state.final.citations : []);
  const nrows = g.nodeOrder.map((id) => { const n = g.nodes[id]; return h("tr", { "aria-selected": String(!!sel && sel.kind === "node" && sel.id === id) }, h("td", null, h("button", { type: "button", onclick: () => select({ kind: "node", id }) }, n.name)), h("td", null, n.kind), h("td", null, n.provenance || "extracted", n.confidence ? ` (${n.confidence})` : ""), h("td", null, cited.nodes.has(id) ? "cited" : ""), h("td", null, n.story || "")); });
  const erows = g.edgeOrder.map((id) => { const e = g.edges[id]; const s = g.nodes[e.src], d = g.nodes[e.dst]; return h("tr", { "aria-selected": String(!!sel && sel.kind === "edge" && sel.id === id) }, h("td", null, s ? s.name : e.src), h("td", null, h("button", { type: "button", onclick: () => select({ kind: "edge", id }) }, e.rel)), h("td", null, d ? d.name : e.dst), h("td", null, e.provenance || "extracted", isDerived(e) ? " (double line)" : ""), h("td", null, cited.edges.has(id) ? "cited" : ""), h("td", null, e.anchor ? e.anchor.chunk_id : "no anchor")); });
  $("list-view").replaceChildren(
    h("table", null, h("caption", null, `Nodes (${nrows.length})`), h("thead", null, h("tr", null, ["Name", "Type", "Provenance", "Cited", "Story"].map((x) => h("th", { scope: "col" }, x)))), h("tbody", null, nrows)),
    h("table", null, h("caption", null, `Edges (${erows.length})`), h("thead", null, h("tr", null, ["From", "Relation", "To", "Provenance", "Cited", "Source"].map((x) => h("th", { scope: "col" }, x)))), h("tbody", null, erows)));
}

$("fit-btn").addEventListener("click", () => graph && graph.fit());
$("zoom-in").addEventListener("click", () => graph && graph.zoom(1.25));
$("zoom-out").addEventListener("click", () => graph && graph.zoom(0.8));
$("cy").addEventListener("keydown", (e) => {
  if (!graph) return;
  const k = e.key;
  if (k === "ArrowRight" || k === "ArrowDown") { e.preventDefault(); const n = graph.move(1); if (n) select(n); }
  else if (k === "ArrowLeft" || k === "ArrowUp") { e.preventDefault(); const n = graph.move(-1); if (n) select(n); }
  else if (k === "Enter" && sel && sel.kind === "node") { e.preventDefault(); expandNode(sel.id); }
  else if (k === "Escape") { e.stopPropagation(); select(null); }
  else if (k === "+" || k === "=") graph.zoom(1.25);
  else if (k === "-") graph.zoom(0.8);
  else if (k === "0") graph.fit();
});

// ---------------------------------------------------------------- entity search

let entTimer = null, entItems = [], entIdx = -1, entToken = 0;
const entIn = $("entity-q"), entList = $("entity-list");
entIn.addEventListener("input", () => { clearTimeout(entTimer); entTimer = setTimeout(searchEntities, 200); });
entIn.addEventListener("focus", () => { if (!entItems.length) searchEntities(); });
async function searchEntities() {
  const t = ++entToken;
  try {
    const r = await getEntities(entIn.value.trim());
    if (t !== entToken) return;
    entItems = r.entities || [];
    entIdx = entItems.length ? 0 : -1;
    renderEntities(r.total);
  } catch (e) {
    entItems = [];
    entList.hidden = false;
    entList.replaceChildren(h("li", { class: "none" }, friendlyError(e).text));
  }
}
function renderEntities(total) {
  entList.hidden = false;
  entIn.setAttribute("aria-expanded", "true");
  entList.replaceChildren(...(entItems.length ? entItems.map((en, i) => h("li", { role: "option", id: `ent-${i}`, "aria-selected": String(i === entIdx), onmousedown: (ev) => { ev.preventDefault(); pickEntity(en); } }, `${KIND_GLYPH[en.kind] || ""} ${en.name}`, h("span", { class: "muted" }, ` ${en.kind}, ${en.story}, ${en.mentions} mentions`))) : [h("li", { class: "none" }, "No entity matches.")]));
  if (entIdx >= 0) entIn.setAttribute("aria-activedescendant", `ent-${entIdx}`);
}
function closeEntities() { entList.hidden = true; entIn.setAttribute("aria-expanded", "false"); entIn.removeAttribute("aria-activedescendant"); }
entIn.addEventListener("blur", closeEntities);
entIn.addEventListener("keydown", (e) => {
  if (e.key === "ArrowDown" || e.key === "ArrowUp") { e.preventDefault(); if (entList.hidden) searchEntities(); else if (entItems.length) { entIdx = (entIdx + (e.key === "ArrowDown" ? 1 : -1) + entItems.length) % entItems.length; renderEntities(); } }
  else if (e.key === "Enter" && entIdx >= 0 && !entList.hidden) { e.preventDefault(); pickEntity(entItems[entIdx]); }
  else if (e.key === "Escape" && !entList.hidden) { e.stopPropagation(); closeEntities(); }
});
async function pickEntity(en) {
  closeEntities();
  entIn.value = en.name;
  await expandNode(en.id);
  select({ kind: "node", id: en.id });
  if (graph) graph.center(en.id);
}

// ---------------------------------------------------------------- health, strip, keys

async function refreshHealth() {
  let hd = null;
  try { hd = await getHealth(); } catch { hd = null; }
  health = hd;
  const s = healthSummary(hd);
  const btn = $("health");
  btn.dataset.level = s.level;
  $("health-icon").textContent = s.level === "ok" ? "✓" : s.level === "degraded" ? "▲" : "✖";
  $("health-text").textContent = s.text + (s.fake ? " (FAKE data)" : "");
  const pop = $("health-pop");
  pop.replaceChildren(h("strong", null, s.text), s.problems.length ? h("ul", null, s.problems.map((p) => h("li", null, p))) : h("p", null, "All checks passed."), hd ? h("p", { class: "muted" }, `Index: ${hd.index && hd.index.chunks} chunks. Graph: ${hd.graph && hd.graph.present ? "present" : "missing"}. ${hd.fake ? "Fake mode: canned answers, no Ollama." : ""}`) : h("p", { class: "muted" }, "Start the server and reload."));
  $("strip-api").textContent = `API: ${s.level}${hd && hd.busy ? " (busy)" : ""}`;
}
$("health").addEventListener("click", () => { const pop = $("health-pop"); pop.hidden = !pop.hidden; $("health").setAttribute("aria-expanded", String(!pop.hidden)); if (!pop.hidden) refreshHealth(); });

function renderStrip() {
  const bg = boardGraph(state);
  $("strip-graph").textContent = `board: ${bg.nodeOrder.length} cards / ${bg.edgeOrder.length} strings`;
  $("strip-rate").textContent = rate();
}

setInterval(() => {
  const running = state.phase === "running";
  const start = state.startedAt;
  $("clock").textContent = start ? `${(((running ? Date.now() : state.endedAt || Date.now()) - start) / 1000).toFixed(1)} s` : "0.0 s";
  if (running) { renderTrace(); renderStrip(); renderProgress(); }
}, 250);

setInterval(() => { if (!document.hidden) refreshHealth(); }, 20000);

let announced = null;
const announce = (t) => { $("sr-announce").textContent = t; };
function announceIfDone() {
  if (state.phase === "done" && announced !== state.runId + "d") {
    announced = state.runId + "d";
    const f = state.final;
    announce(f.status === "refused" ? "Refusal: not in the corpus." : `Answer ready, ${verifiedText()}.`);
  } else if (state.phase === "error" && announced !== "e" + state.runId) { announced = "e" + state.runId; announce("The run failed."); }
}
// announce once per commit, outside the token stream
setInterval(announceIfDone, 500);

document.addEventListener("keydown", (e) => {
  const tag = (e.target.tagName || "").toLowerCase();
  const typing = tag === "input" || tag === "textarea" || e.target.isContentEditable;
  if (e.key === "Escape") {
    if (state.phase === "running") { stop(false); e.preventDefault(); }
    else if (sel) select(null);
    return;
  }
  if (typing || e.ctrlKey || e.metaKey || e.altKey) return;
  if (e.key === "/") { e.preventDefault(); $("question").focus(); }
  else if (e.key === "g") setListMode(!listMode);
  else if (e.key === "t") { jumpLatest(); $("panel-trace").focus?.(); }
});

for (const b of document.querySelectorAll(".tabs button")) {
  b.addEventListener("click", () => {
    document.querySelector(".cols").dataset.tab = b.dataset.tab;
    document.querySelectorAll(".tabs button").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
    if (b.dataset.tab === "board" && graph) requestAnimationFrame(() => { graph.resize(); graph.fit(); });
  });
}
let rzTimer = null;
new ResizeObserver(() => { if (!graph) return; graph.resize(); clearTimeout(rzTimer); rzTimer = setTimeout(() => graph.fit(), 150); }).observe($("cy"));

// ---------------------------------------------------------------- boot
if (innerWidth >= 1500) $("legend").open = true;

applyTheme(store.get("db-theme", "auto"));
applyMotion(store.get("db-motion", "on") !== "off");
renderHistory();
refreshHealth();
render();
$("panel-trace").tabIndex = -1;
if (replayRequested) {
  if (!replayPath) banner({ kind: "error", text: "Invalid ?replay= path. Use a relative path such as replay/run.json." });
  else runReplay();
}
// test hook for browser checks (read-only snapshot)
window.__db = { get state() { return state; }, get board() { return graph ? graph.counts() : null; }, get cy() { return graph ? graph.cy : null; } };
