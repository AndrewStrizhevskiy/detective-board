// Demo modes (backlog R-01, R-02, R-03), pure helpers: which stored run belongs to a question, how
// a recording is labelled, when a live run counts as stalled, and what the UI offers then.
// No DOM, no fetch; app.js wires them up.

// A live run is "connection lost" after this long without a single byte from the server. The API
// sends a keepalive comment every 15 s while the model is busy, so 90 s of silence is not a slow
// model but a dead or hung server.
export const STALL_MS = 90000;

// Gaps between events of a stored run started from the UI (key `c` or the picker) are capped, so a
// 40 s CPU prefill does not stall the stage; the timeline is otherwise the recorded one.
export const STORED_RUN_CAP_MS = 2000;

// Lower case, straight quotes, letters and digits only, single spaces.
export function normQuestion(q) {
  return String(q || "")
    .toLowerCase()
    .replace(/[‘’‛′]/g, "'")
    .replace(/[^\p{L}\p{N}' ]+/gu, " ")
    .replace(/'/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

const words = (q) => new Set(normQuestion(q).split(" ").filter(Boolean));

// The stored run for a question: the same question after normalisation, else the closest one if
// its words overlap at least `minOverlap` (Jaccard), so a typo or a missing "the" still matches.
// Never a loose guess: a different question must not get somebody else's recording.
export function findRecording(recordings, question, { minOverlap = 0.8 } = {}) {
  const q = normQuestion(question);
  if (!q || !Array.isArray(recordings)) return null;
  const list = recordings.filter((r) => r && r.file && r.question);
  const exact = list.filter((r) => normQuestion(r.question) === q);
  if (exact.length) return preferReal(exact);
  const mine = words(question);
  let best = null;
  let bestScore = 0;
  for (const r of list) {
    const theirs = words(r.question);
    let common = 0;
    for (const w of mine) if (theirs.has(w)) common++;
    const score = common / (mine.size + theirs.size - common || 1);
    if (score > bestScore || (score === bestScore && best && r.kind === "real" && best.kind !== "real")) { best = r; bestScore = score; }
  }
  return bestScore >= minOverlap ? best : null;
}

// Several recordings of the same question: a real run wins over a fake-backend one.
function preferReal(list) {
  return list.find((r) => r.kind === "real") || list[0];
}

const KIND_TEXT = {
  real: "real run on the target laptop",
  fake: "fake backend (demo fixture)",
  synthetic: "hand-written events, not a run",
};

// What the picker and the banner say about a recording. Every recording says RECORDING; a
// synthetic one says so too, so nothing stored can pass for a live run.
export function recordingLabel(rec) {
  const parts = [KIND_TEXT[rec.kind] || "recording"];
  if (rec.recorded_at) {
    const d = new Date(rec.recorded_at);
    if (!Number.isNaN(d.getTime())) parts.push(d.toISOString().slice(0, 16).replace("T", " ") + " UTC");
  }
  if (Number.isFinite(rec.seconds)) parts.push(`${rec.seconds} s`);
  if (rec.step) parts.push(rec.step);
  return { badge: rec.kind === "synthetic" ? "SYNTHETIC RECORDING" : "RECORDING", line: parts.join(" · ") };
}

export function stalled(lastActivityAt, now, limit = STALL_MS) {
  return Number.isFinite(lastActivityAt) && now - lastActivityAt >= limit;
}

// Recovery after a live run failed (server down, connection lost, stalled): play the stored run of
// the same question if there is one, else offer the picker; retrying live is always offered.
export function recoveryActions(question, recordings) {
  const rec = findRecording(recordings, question);
  const out = [];
  if (rec) out.push({ kind: "replay", file: rec.file, label: "Play the stored run (c)" });
  else out.push({ kind: "pick", label: "Pick a recording" });
  out.push({ kind: "retry", label: "Try live again" });
  return out;
}
