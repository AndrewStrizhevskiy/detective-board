// Pure state reducer for one investigation run. No DOM, no network.
// Actions: run_start, event, stream_end, cancel, graph_merge, reset.

export const TERMINAL = new Set(["final", "run_error"]);

export function emptyGraph() {
  return { nodes: {}, edges: {}, nodeOrder: [], edgeOrder: [] };
}

export function initialState() {
  return {
    phase: "idle", // idle | running | done | error | cancelled
    mode: "live", // live | replay
    question: "",
    runId: null,
    events: [],
    lastSeq: -1,
    route: null,
    hits: [],
    gate: null,
    sources: [],
    answer: { attempt: 1, text: "", tokens: 0, discardedTokens: 0, discardedAttempts: 0 },
    checks: [],
    refusal: null,
    final: null,
    error: null,
    findings: [], // tool results carrying provenance (+ explanation when the event has one)
    graph: emptyGraph(),
    startedAt: null,
    firstTokenAt: null,
    endedAt: null,
    lastEventAt: null,
  };
}

function normNode(n) {
  const id = String(n.id);
  return { ...n, id, kind: n.kind || "person", name: n.name || n.label || id };
}

function normEdge(e) {
  return { ...e, id: String(e.id), src: String(e.src), dst: String(e.dst), rel: e.rel || "RELATION" };
}

// Merge nodes/edges into a graph, keeping insertion order and richer fields.
export function mergeGraph(graph, nodes = [], edges = []) {
  const g = { nodes: { ...graph.nodes }, edges: { ...graph.edges }, nodeOrder: graph.nodeOrder.slice(), edgeOrder: graph.edgeOrder.slice() };
  for (const raw of nodes) {
    const n = normNode(raw);
    const old = g.nodes[n.id];
    if (!old) {
      g.nodes[n.id] = n;
      g.nodeOrder.push(n.id);
    } else {
      const merged = { ...old };
      for (const k in n) if (n[k] !== undefined && n[k] !== null) merged[k] = n[k];
      if (old.anchors && n.anchors && old.anchors.length > n.anchors.length) merged.anchors = old.anchors;
      g.nodes[n.id] = merged;
    }
  }
  for (const raw of edges) {
    const e = normEdge(raw);
    const old = g.edges[e.id];
    if (!old) {
      g.edges[e.id] = e;
      g.edgeOrder.push(e.id);
    } else {
      const merged = { ...old };
      for (const k in e) if (e[k] !== undefined && e[k] !== null) merged[k] = e[k];
      g.edges[e.id] = merged;
    }
  }
  return g;
}

function overlap(a, b) {
  return a.chunk_id === b.chunk_id && a.char_start < b.char_end && b.char_start < a.char_end;
}

// Which graph elements are cited by the final answer. Edge: its anchor overlaps a citation
// anchor. Node: it has an overlapping anchor, or touches a cited edge.
export function citedGraphIds(graph, citations) {
  const anchors = (citations || []).map((c) => c.anchor).filter(Boolean);
  const nodes = new Set();
  const edges = new Set();
  if (!anchors.length) return { nodes, edges };
  for (const id of graph.edgeOrder) {
    const e = graph.edges[id];
    if (e.anchor && anchors.some((a) => overlap(a, e.anchor))) {
      edges.add(id);
      nodes.add(e.src);
      nodes.add(e.dst);
    }
  }
  for (const id of graph.nodeOrder) {
    const n = graph.nodes[id];
    if ((n.anchors || []).some((na) => anchors.some((a) => overlap(a, na)))) nodes.add(id);
  }
  return { nodes, edges };
}

export function reduce(state, action) {
  switch (action.type) {
    case "reset":
      return initialState();
    case "run_start":
      return { ...initialState(), phase: "running", mode: action.mode || "live", question: action.question || "", startedAt: action.now ?? Date.now(), lastEventAt: action.now ?? Date.now(), graph: action.keepGraph ? state.graph : emptyGraph() };
    case "cancel":
      return state.phase === "running" ? { ...state, phase: "cancelled", endedAt: action.now ?? Date.now() } : state;
    case "graph_merge":
      return { ...state, graph: mergeGraph(state.graph, action.nodes, action.edges) };
    case "stream_end":
      // The server closes the stream after `final`/`run_error`; anything else is a lost connection.
      if (state.phase !== "running") return state;
      return { ...state, phase: "error", endedAt: action.now ?? Date.now(), error: { code: "connection_lost", message: "The connection to the agent closed before the run finished." } };
    case "event":
      return applyEvent(state, action.event, action.now ?? Date.now());
    default:
      return state;
  }
}

function applyEvent(state, ev, now) {
  if (state.phase !== "running") return state; // late events after cancel/terminal are ignored
  if (typeof ev.seq === "number") {
    if (ev.seq <= state.lastSeq) return state; // duplicate
  }
  const s = { ...state, events: [...state.events, ev], lastEventAt: now, lastSeq: typeof ev.seq === "number" ? ev.seq : state.lastSeq, runId: state.runId || ev.run_id || null };
  switch (ev.type) {
    case "route_decided":
      s.route = ev;
      break;
    case "retrieval_results":
      s.hits = ev.hits || [];
      s.gate = ev.gate || null;
      break;
    case "graph_results":
      s.graph = mergeGraph(s.graph, ev.nodes, ev.edges);
      break;
    case "tool_result":
      s.findings = [...s.findings, { tool: ev.tool, ok: ev.ok, provenance: ev.provenance || null, summary: ev.summary, explanation: ev.explanation || null, seq: ev.seq }];
      break;
    case "enriched_query":
      s.sources = ev.sources || [];
      break;
    case "answer_token": {
      const a = ev.attempt ?? 1;
      const cur = s.answer;
      if (a < cur.attempt) break; // straggler from a discarded attempt
      if (a > cur.attempt) {
        // A retry starts a new attempt: everything written so far was from a failed attempt.
        s.answer = { attempt: a, text: ev.text || "", tokens: 1, discardedTokens: cur.discardedTokens + cur.tokens, discardedAttempts: cur.discardedAttempts + 1 };
      } else {
        s.answer = { ...cur, text: cur.text + (ev.text || ""), tokens: cur.tokens + 1 };
      }
      if (s.firstTokenAt === null) s.firstTokenAt = now;
      break;
    }
    case "citation_check":
      s.checks = [...s.checks, ev];
      break;
    case "refusal":
      s.refusal = ev;
      break;
    case "final":
      s.final = ev;
      s.phase = "done";
      s.endedAt = now;
      if (ev.route && !s.route) s.route = ev.route;
      break;
    case "run_error":
      s.error = { code: ev.code || "internal", message: ev.message || "The run failed." };
      s.phase = "error";
      s.endedAt = now;
      break;
    default:
      break; // unknown/parse_error events are kept in the trace only
  }
  return s;
}

// Text to show in the answer panel: the final (verified) answer once known, else the current draft.
export function answerText(state) {
  return state.final ? state.final.answer : state.answer.text;
}

// Waiting stage for the anti-freeze indicator.
export function waitingStage(state, now) {
  if (state.phase !== "running") return null;
  const since = (t) => Math.max(0, Math.floor((now - t) / 1000));
  if (state.firstTokenAt !== null) return { kind: "writing", seconds: since(state.firstTokenAt) };
  const enrichedAt = state.events.some((e) => e.type === "enriched_query");
  if (enrichedAt) return { kind: "first_token", seconds: since(state.lastEventAt) };
  return { kind: "working", seconds: since(state.lastEventAt) };
}
