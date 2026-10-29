// Bare model against the agent (issue #13), pure helpers for the split view: what a bare-model
// recording must contain, how it is labelled, and how much of its text has "arrived" at a given
// moment of the playback. No DOM, no fetch; app.js wires them up.
// A bare recording is web/replay/bare/<id>.json, {meta, answer}, written by
// scripts/bare_recording.py from a real eval run: plain text, no trace events, never edited.

// Checks a bare recording; throws with a reason instead of showing something unlabelled.
export function normaliseBare(json) {
  if (!json || typeof json !== "object" || Array.isArray(json)) throw new Error("bare recording must be {meta, answer}");
  const { meta, answer } = json;
  if (!meta || typeof meta !== "object") throw new Error("bare recording has no meta");
  if (meta.label !== "RECORDING") throw new Error("bare recording is not labelled RECORDING");
  if (typeof answer !== "string" || !answer.trim()) throw new Error("bare recording has no answer text");
  return { meta, answer };
}

const fmt = (s) => (Number.isFinite(s) ? `${s < 10 ? s.toFixed(1) : Math.round(s)} s` : null);

// The labels of the left column: the badges, then one line on where the text comes from.
export function bareLabel(meta) {
  const run = [meta.git_sha && `eval run ${meta.git_sha}`, meta.split && `${meta.split} split`].filter(Boolean).join(", ");
  const times = [fmt(meta.ttft_s) && `first token ${fmt(meta.ttft_s)}`, fmt(meta.seconds) && `${fmt(meta.seconds)} in all`].filter(Boolean).join(", ");
  return {
    badges: ["NO SOURCES", "RECORDING"],
    line: [meta.model, meta.recorded_on, run, times].filter(Boolean).join(" · "),
    call: meta.call || "",
  };
}

// Characters of the answer shown `elapsedMs` after the start: nothing before the recorded first
// token, then an even pace up to the recorded total time (the eval run keeps no per-token times,
// so the pace within the answer is an approximation; start and end are the recorded ones).
export function revealedChars(answer, meta, elapsedMs, speed = 1) {
  const n = answer.length;
  const s = speed > 0 ? speed : 1;
  const t = (elapsedMs * s) / 1000;
  const first = Number.isFinite(meta.ttft_s) ? meta.ttft_s : 0;
  const total = Number.isFinite(meta.seconds) && meta.seconds > first ? meta.seconds : first;
  if (t < first) return 0;
  if (t >= total) return n;
  return Math.min(n, Math.max(1, Math.round((n * (t - first)) / (total - first))));
}

// Seconds of the recorded run that `elapsedMs` of playback stands for, capped at its total.
export function recordedSeconds(meta, elapsedMs, speed = 1) {
  const t = (elapsedMs * (speed > 0 ? speed : 1)) / 1000;
  return Number.isFinite(meta.seconds) ? Math.min(t, meta.seconds) : t;
}
