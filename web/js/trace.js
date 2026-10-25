// Pure: turn raw trace events into display rows (one row per step; tokens are folded into one row).

const f2 = (x) => (typeof x === "number" ? x.toFixed(2) : String(x));
const f3 = (x) => (typeof x === "number" ? x.toFixed(3) : String(x));
const short = (s, n = 90) => (s && s.length > n ? s.slice(0, n - 1) + "…" : s || "");

export const TYPE_LABEL = {
  route_decided: "route",
  retrieval_started: "retrieve",
  retrieval_results: "retrieve",
  graph_query: "graph query",
  graph_results: "graph",
  tool_call: "tool call",
  tool_result: "tool result",
  enriched_query: "enrich",
  answer_token: "answer",
  citation_check: "citation check",
  refusal: "refusal",
  final: "final",
  run_error: "error",
  parse_error: "bad frame",
};

// status: running | ok | warn | error | info
export function describe(ev) {
  const lines = [];
  const list = [];
  let summary = "";
  let status = "ok";
  let corpus = false;
  switch (ev.type) {
    case "route_decided": {
      const r = (ev.routes || []).join(" + ").toUpperCase() || "NONE";
      summary = `→ ${r} (${ev.method}): ${ev.reason}`;
      lines.push(["why", ev.reason], ["method", ev.method]);
      if (ev.matched && ev.matched.length) lines.push(["matched rules", ev.matched.join(", ")]);
      if (ev.tools && ev.tools.length) lines.push(["tools", ev.tools.join(", ")]);
      if (ev.confidence != null) lines.push(["confidence", f2(ev.confidence)]);
      break;
    }
    case "retrieval_started":
      summary = `searching, k=${ev.k}, attempt ${ev.attempt}: ${short(ev.query, 70)}`;
      status = "running";
      lines.push(["query", ev.query]);
      break;
    case "retrieval_results": {
      const arms = new Set();
      for (const h of ev.hits || []) for (const a in h.ranks || {}) arms.add(a);
      summary = `${(ev.hits || []).length} chunks, gate ${ev.gate && ev.gate.passed ? "passed" : "FAILED"}${arms.size ? ` (${[...arms].join(" + ")})` : ""}`;
      status = ev.gate && !ev.gate.passed ? "warn" : "ok";
      if (ev.gate) lines.push(["gate", `${ev.gate.reason}; best ${f3(ev.gate.best_score)} vs threshold ${f3(ev.gate.threshold)}; support ${f2(ev.gate.support)} vs ${f2(ev.gate.min_support)}`]);
      for (const h of ev.hits || []) {
        const ranks = Object.entries(h.ranks || {}).map(([k, v]) => `${k} #${v}`).join(", ");
        list.push({ chunk_id: h.chunk_id, text: `#${h.rank} ${h.chunk_id}  rrf ${f3(h.rrf)}${ranks ? `  (${ranks})` : ""}` });
      }
      corpus = true;
      break;
    }
    case "graph_query":
      summary = `${ev.query_kind}(${Object.values(ev.args || {}).map((v) => JSON.stringify(v)).join(", ")})`;
      status = "running";
      lines.push(["kind", ev.query_kind], ["args", JSON.stringify(ev.args || {})]);
      break;
    case "graph_results":
      summary = `${(ev.nodes || ev.node_ids || []).length} nodes, ${(ev.edges || ev.edge_ids || []).length} edges${ev.truncated ? " (truncated)" : ""}`;
      status = ev.truncated ? "warn" : "ok";
      lines.push(["kind", ev.query_kind], ["seeds", (ev.seeds || []).join(", ") || "-"]);
      for (const n of ev.nodes || []) list.push({ text: `${n.kind}: ${n.name || n.id}` });
      for (const e of ev.edges || []) list.push({ text: `${e.src} -[${e.rel}]-> ${e.dst}`, chunk_id: e.anchor && e.anchor.chunk_id });
      break;
    case "tool_call":
      summary = `${ev.server}.${ev.tool}(${short(Object.entries(ev.arguments || {}).map(([k, v]) => `${k}=${JSON.stringify(v)}`).join(", "), 70)})`;
      status = "running";
      lines.push(["arguments", JSON.stringify(ev.arguments)], ["timeout", `${ev.timeout_s} s`]);
      break;
    case "tool_result":
      summary = `${ev.tool}: ${ev.ok ? short(ev.summary) : "error: " + short((ev.error && (ev.error.message || ev.error.code)) || ev.summary)}`;
      status = ev.ok ? "ok" : "warn";
      if (ev.provenance) lines.push(["provenance", ev.provenance]);
      if (ev.summary) lines.push(["summary", ev.summary]);
      if (ev.error) lines.push(["error", JSON.stringify(ev.error)], ["effect", "continuing without this evidence"]);
      break;
    case "enriched_query":
      summary = `${(ev.sources || []).length} evidence blocks, ${ev.prompt_chars} chars, ${ev.graph_facts} graph facts, ${ev.rule_facts} rule facts`;
      status = ev.injection_suspects && ev.injection_suspects.length ? "warn" : "ok";
      lines.push(["corpus text is data", ev.data_marked ? "yes, delimited and never followed as instructions" : "NO"]);
      if (ev.injection_suspects && ev.injection_suspects.length) lines.push(["injection suspects", `sources ${ev.injection_suspects.join(", ")}`]);
      for (const s of ev.sources || []) list.push({ chunk_id: s.chunk_id, text: `[${s.n}] ${s.chunk_id} (${s.origin}, ${s.label}) chars ${s.char_start}-${s.char_end}` });
      corpus = true;
      break;
    case "citation_check": {
      const cs = ev.citations || [];
      const good = cs.filter((c) => c.verbatim && c.source_exists).length;
      summary = `${ev.ok ? "ok" : "problem"}: ${good}/${cs.length} quotes verified, action ${ev.action}`;
      status = ev.ok ? "ok" : ev.action === "retry" ? "warn" : "error";
      for (const c of cs) list.push({ text: `[${c.n}] ${c.verbatim ? "verbatim" : "NOT verbatim"}, source ${c.source_exists ? "exists" : "MISSING"}` });
      if (ev.unsupported_claims && ev.unsupported_claims.length) lines.push(["unsupported claims", ev.unsupported_claims.join(" | ")]);
      if (ev.problems && ev.problems.length) lines.push(["problems", ev.problems.join(" | ")]);
      break;
    }
    case "refusal":
      summary = `refused: ${ev.code}`;
      status = "info";
      lines.push(["message", ev.message]);
      if (ev.missing && ev.missing.length) lines.push(["missing", ev.missing.join(", ")]);
      for (const q of ev.searched || []) list.push({ text: `searched: ${q}` });
      break;
    case "final":
      summary = `${ev.status}${ev.verified ? ", verified" : ", not verified"}, ${ev.attempts} attempt(s), ${(ev.citations || []).length} citations`;
      status = ev.status === "refused" ? "info" : ev.verified ? "ok" : "warn";
      break;
    case "run_error":
      summary = `${ev.code}: ${ev.message}`;
      status = "error";
      break;
    case "parse_error":
      summary = `could not read a stream frame (${ev.event})`;
      status = "error";
      lines.push(["raw", ev.raw]);
      break;
    default:
      summary = ev.type;
  }
  return { summary, status, lines, list, corpus };
}

export function traceRows(events) {
  const rows = [];
  for (const ev of events) {
    const last = rows[rows.length - 1];
    if (ev.type === "answer_token") {
      if (last && last.type === "answer_token" && last.attempt === (ev.attempt ?? 1)) {
        last.count += 1;
        last.text += ev.text || "";
        last.durationEnd = ev.ts;
        last.raw.push(ev);
        refreshTokens(last);
        continue;
      }
      const row = { key: `tok-${ev.seq}`, type: "answer_token", attempt: ev.attempt ?? 1, count: 1, text: ev.text || "", firstTs: ev.ts, raw: [ev], corpus: false, duration: null };
      refreshTokens(row);
      rows.push(row);
      continue;
    }
    const d = describe(ev);
    rows.push({ key: `ev-${ev.seq ?? rows.length}-${ev.type}`, type: ev.type, seq: ev.seq, ts: ev.ts, duration: ev.duration_ms ?? null, step: ev.step_id || null, raw: [ev], ...d });
  }
  // A "started" row is finished once its results row exists (same step_id).
  for (const r of rows) {
    if ((r.type === "retrieval_started" || r.type === "graph_query" || r.type === "tool_call") && rows.some((o) => o !== r && o.seq > r.seq && ((r.step && o.step === r.step) || (r.type === "tool_call" && o.type === "tool_result")))) {
      r.status = "ok";
    }
  }
  return rows;
}

function refreshTokens(row) {
  row.summary = `${row.count} tokens, attempt ${row.attempt}`;
  row.status = "ok";
  row.lines = [["draft so far", row.text]];
  row.list = [];
}

export function fmtSeconds(ms) {
  if (ms == null || !Number.isFinite(ms)) return "";
  return ms < 10000 ? `${(ms / 1000).toFixed(1)} s` : `${Math.round(ms / 1000)} s`;
}

// Run clock: milliseconds under a second (a fake or cached run finishes in a few ms, and "0.0 s"
// would look like a stopped clock), tenths up to a minute, then m:ss.
export function fmtElapsed(ms) {
  if (ms == null || !Number.isFinite(ms) || ms < 0) return "0.0 s";
  if (Math.round(ms) < 1000) return `${Math.max(1, Math.round(ms))} ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)} s`;
  const s = Math.floor(ms / 1000);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

// Health chip content. level: ok | degraded | down
export function healthSummary(h) {
  if (!h) return { level: "down", text: "API unreachable", problems: ["The API did not answer /api/health."] };
  const problems = [];
  if (h.ollama && h.ollama.reachable === false) problems.push("Ollama is not reachable");
  if (h.ollama && h.ollama.models) {
    if (h.ollama.models.llm === false) problems.push("LLM model is not installed");
    if (h.ollama.models.embedding === false) problems.push("Embedding model is not installed");
  }
  if (h.index && h.index.present === false) problems.push("Search index is missing");
  if (h.graph && h.graph.present === false) problems.push("Graph is missing");
  if (h.status !== "ok" && !problems.length) problems.push("The API reports a degraded state");
  const level = h.status === "ok" && !problems.length ? "ok" : "degraded";
  return { level, text: level === "ok" ? (h.busy ? "API ok, busy" : "API ok") : "API degraded", problems, fake: !!h.fake, busy: !!h.busy };
}
