// Replay of a saved event list at its original timing (the backup recording).
// File format: a JSON array of trace events, or {meta?, events: [...]}; each event keeps its `ts`.

export function normaliseRecording(json) {
  const events = Array.isArray(json) ? json : json && Array.isArray(json.events) ? json.events : null;
  if (!events) throw new Error("recording must be an array of events or {events: [...]}");
  const meta = !Array.isArray(json) && json.meta && typeof json.meta === "object" ? json.meta : {};
  for (const e of events) if (!e || typeof e !== "object" || typeof e.type !== "string") throw new Error("recording contains an item without a type");
  return { meta, events };
}

// Delay before each event, from the ts differences. speed > 1 is faster; cap (ms, optional)
// limits one gap. Unparseable or decreasing timestamps give a zero gap.
export function replayDelays(events, { speed = 1, cap = Infinity } = {}) {
  const s = speed > 0 ? speed : 1;
  let prev = null;
  return events.map((e) => {
    const t = Date.parse(e.ts);
    let d = 0;
    if (Number.isFinite(t)) {
      if (prev !== null && t > prev) d = t - prev;
      prev = t;
    }
    return Math.min(d, cap) / s;
  });
}

export async function* playReplay(events, { speed = 1, cap = Infinity, signal, sleep = defaultSleep } = {}) {
  const delays = replayDelays(events, { speed, cap });
  for (let i = 0; i < events.length; i++) {
    if (delays[i] > 0) await sleep(delays[i], signal);
    if (signal && signal.aborted) return;
    yield events[i];
  }
}

function defaultSleep(ms, signal) {
  return new Promise((resolve) => {
    const id = setTimeout(resolve, ms);
    if (signal) signal.addEventListener("abort", () => { clearTimeout(id); resolve(); }, { once: true });
  });
}

// Only same-origin relative paths below the page, no scheme, no "..".
export function safeReplayPath(p) {
  if (typeof p !== "string" || !p || p.length > 200) return null;
  if (/^[a-z][a-z0-9+.-]*:/i.test(p) || p.startsWith("/") || p.startsWith("\\") || p.includes("..") || p.includes("\\")) return null;
  return /^[A-Za-z0-9._\/-]+$/.test(p) ? p : null;
}
