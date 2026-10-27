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

// Edit distance between two strings (insertions, deletions, substitutions).
export function editDistance(a, b) {
  let prev = Array.from({ length: b.length + 1 }, (_, j) => j);
  for (let i = 1; i <= a.length; i++) {
    const cur = [i];
    for (let j = 1; j <= b.length; j++) cur[j] = Math.min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1));
    prev = cur;
  }
  return prev[b.length];
}

const NEGATIONS = new Set(["not", "no", "never", "nor", "neither", "nobody", "nothing", "none", "without", "isnt", "wasnt", "doesnt", "didnt", "dont", "cant", "cannot", "couldnt", "wouldnt", "hasnt", "havent", "hadnt", "arent", "werent"]);

// True when one question has a negation word the other lacks: a few characters, opposite meaning.
function negationDiffers(a, b) {
  const neg = (s) => s.split(" ").filter((w) => NEGATIONS.has(w)).sort().join(" ");
  return neg(a) !== neg(b);
}

// The stored run for a question: the same question after normalisation, else one within a few
// characters of it (a typo, a dropped "Dr" or "the": at most `maxEdits`, and at most 8 % of the
// length). Never a loose guess: one added word ("...Roylott's sister?") is another question and
// must not get somebody else's recording.
export function findRecording(recordings, question, { maxEdits = 6 } = {}) {
  const q = normQuestion(question);
  if (!q || !Array.isArray(recordings)) return null;
  const list = recordings.filter((r) => r && r.file && r.question);
  const exact = list.filter((r) => normQuestion(r.question) === q);
  if (exact.length) return preferReal(exact);
  const limit = Math.min(maxEdits, Math.floor(q.length * 0.08));
  let best = null;
  let bestD = Infinity;
  for (const r of list) {
    if (negationDiffers(q, normQuestion(r.question))) continue; // "...not contradict..." is the opposite question
    const d = editDistance(q, normQuestion(r.question));
    if (d < bestD || (d === bestD && best && r.kind === "real" && best.kind !== "real")) { best = r; bestD = d; }
  }
  return bestD <= limit ? best : null;
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
