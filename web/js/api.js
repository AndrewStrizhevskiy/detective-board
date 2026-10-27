// Network layer: fetch + ReadableStream for POST /api/ask (EventSource cannot POST).
import { SseParser, decodeMessage } from "./sse.js";

export class ApiError extends Error {
  constructor(status, code, message) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

async function readError(res) {
  let code = "http_" + res.status;
  let message = `Request failed (${res.status}).`;
  try {
    const j = await res.json();
    if (j && j.error) {
      code = j.error.code || code;
      message = j.error.message || message;
    }
  } catch { /* not JSON */ }
  return new ApiError(res.status, code, message);
}

async function getJson(path, { signal, base = "", fetchImpl = fetch } = {}) {
  const res = await fetchImpl(base + path, { signal, headers: { accept: "application/json" } });
  if (!res.ok) throw await readError(res);
  return res.json();
}

export const getHealth = (o) => getJson("/api/health", o);
export const getEntities = (q, o = {}) => getJson(`/api/graph/entities?q=${encodeURIComponent(q)}&limit=${o.limit || 12}`, o);
export const getSubgraph = (entity, hops = 1, o = {}) => getJson(`/api/graph/subgraph?entity=${encodeURIComponent(entity)}&hops=${hops}`, o);

export function getSource(chunkId, { quote, start, end, ...o } = {}) {
  const p = new URLSearchParams();
  if (quote) p.set("quote", quote.slice(0, 1000));
  if (Number.isFinite(start)) p.set("start", String(start));
  if (Number.isFinite(end)) p.set("end", String(end));
  const qs = p.toString();
  return getJson(`/api/source/${encodeURIComponent(chunkId)}${qs ? "?" + qs : ""}`, o);
}

// Async generator of decoded trace events. Throws ApiError for non-200 (e.g. 429 busy).
// onActivity() runs on every chunk from the server, keepalive comments included, so the caller can
// tell a slow model (keepalives every 15 s) from a dead connection (nothing at all).
export async function* askStream(question, history, { signal, base = "", fetchImpl = fetch, onActivity } = {}) {
  const body = { question };
  if (history && history.length) body.history = history;
  const res = await fetchImpl(base + "/api/ask", {
    method: "POST",
    headers: { "content-type": "application/json", accept: "text/event-stream" },
    body: JSON.stringify(body),
    signal,
  });
  if (!res.ok) throw await readError(res);
  if (!res.body) throw new ApiError(0, "no_stream", "This browser cannot read a streamed response.");
  if (onActivity) onActivity();
  const reader = res.body.getReader();
  // an abort (Stop, or the stall watchdog) must end a read that is waiting on a silent server
  if (signal) signal.addEventListener("abort", () => { reader.cancel().catch(() => {}); }, { once: true });
  const dec = new TextDecoder("utf-8");
  const parser = new SseParser();
  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      if (onActivity) onActivity();
      for (const msg of parser.push(dec.decode(value, { stream: true }))) yield decodeMessage(msg);
    }
    for (const msg of parser.push(dec.decode() + "\n\n")) yield decodeMessage(msg);
  } finally {
    try { await reader.cancel(); } catch { /* already closed */ }
  }
}

export function friendlyError(e) {
  if (e instanceof ApiError) {
    if (e.status === 429 || e.code === "busy") return { kind: "busy", text: "The agent is busy with another run. Try again in a few seconds." };
    if (e.status === 400 || e.code === "invalid_input") return { kind: "input", text: e.message };
    if (e.status === 413 || e.code === "too_large") return { kind: "input", text: "The question or history is too long." };
    return { kind: "error", text: e.message };
  }
  if (e && e.name === "AbortError") return { kind: "aborted", text: "Stopped." };
  return { kind: "error", text: "Cannot reach the agent. Is the server running?" };
}
