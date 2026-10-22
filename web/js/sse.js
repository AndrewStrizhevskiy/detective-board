// Incremental Server-Sent Events parser (WHATWG HTML 9.2). Pure; no DOM, no fetch.
// push(text) returns the complete messages found so far: [{event, data, id}].

export class SseParser {
  constructor() {
    this.buf = "";
    this.started = false;
    this.cr = false; // last char of the previous chunk was "\r"
    this._reset();
    this.lastEventId = "";
  }

  _reset() {
    this.event = "";
    this.dataLines = [];
    this.id = null;
  }

  push(text) {
    if (!text) return [];
    if (!this.started) {
      this.started = true;
      if (text.charCodeAt(0) === 0xfeff) text = text.slice(1);
    }
    if (this.cr && text[0] === "\n") text = text.slice(1); // "\r" + "\n" split over chunks
    this.cr = text.endsWith("\r");
    this.buf += text;
    const lines = this.buf.split(/\r\n|\r|\n/);
    this.buf = lines.pop(); // incomplete tail (a bare trailing "\r" yields "" here, which is right)
    const out = [];
    for (const line of lines) {
      const msg = this._line(line);
      if (msg) out.push(msg);
    }
    return out;
  }

  _line(line) {
    if (line === "") {
      if (this.dataLines.length === 0) {
        this._reset();
        return null;
      }
      const msg = {
        event: this.event || "message",
        data: this.dataLines.join("\n"),
        id: this.id ?? this.lastEventId,
      };
      if (this.id !== null) this.lastEventId = this.id;
      this._reset();
      return msg;
    }
    if (line[0] === ":") return null; // comment, e.g. ": keepalive"
    const i = line.indexOf(":");
    let field = line;
    let value = "";
    if (i >= 0) {
      field = line.slice(0, i);
      value = line.slice(i + 1);
      if (value[0] === " ") value = value.slice(1);
    }
    if (field === "event") this.event = value;
    else if (field === "data") this.dataLines.push(value);
    else if (field === "id" && !value.includes("\0")) this.id = value;
    return null;
  }
}

// Turn one SSE message into a trace event object. `data` is JSON per docs/api.md.
export function decodeMessage(msg) {
  try {
    const obj = JSON.parse(msg.data);
    if (obj === null || typeof obj !== "object" || Array.isArray(obj)) throw new Error("not an object");
    if (!obj.type) obj.type = msg.event;
    return obj;
  } catch (e) {
    return { type: "parse_error", event: msg.event, raw: String(msg.data).slice(0, 500), message: String(e.message || e) };
  }
}
