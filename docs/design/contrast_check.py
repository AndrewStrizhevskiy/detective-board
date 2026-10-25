#!/usr/bin/env python3
"""WCAG 2.x contrast check for docs/design/tokens.css (stdlib only).

Usage: python3 docs/design/contrast_check.py [path/to/tokens.css]
Parses the light block (:root) and the dark block (data-theme="dark"), computes
relative luminance and contrast ratio, prints a table, exits 1 if any pair fails.
Thresholds: 4.5 for text, 3.0 for non-text UI/graphics (WCAG 1.4.3, 1.4.11).
"""
import re
import sys
from pathlib import Path


def parse_blocks(css: str) -> dict[str, dict[str, str]]:
    blocks = {}
    # light: first ":root {" block; dark: ':root[data-theme="dark"] {' block
    for name, pat in (("light", r"^:root \{(.*?)^\}"), ("dark", r'^:root\[data-theme="dark"\] \{(.*?)^\}')):
        m = re.search(pat, css, re.S | re.M)
        if not m:
            raise SystemExit(f"block {name} not found")
        blocks[name] = dict(re.findall(r"--([\w-]+):\s*(#[0-9a-fA-F]{6})", m.group(1)))
        blocks[name].update(re.findall(r"--([\w-]+-alpha):\s*([0-9.]+)\s*;", m.group(1)))
    # dark block only overrides some tokens; fall back to light for the rest
    blocks["dark"] = {**blocks["light"], **blocks["dark"]}
    for tok in blocks.values():
        for name, color, under, alpha in DRAWN:
            tok[name] = blend(tok[color], tok[under], float(tok[alpha]))
    return blocks


def blend(fg: str, bg: str, a: float) -> str:
    """fg painted with opacity a over bg, as the browser draws it."""
    f, b = (tuple(int(h.lstrip("#")[i : i + 2], 16) for i in (0, 2, 4)) for h in (fg, bg))
    return "#" + "".join(f"{round(a * x + (1 - a) * y):02x}" for x, y in zip(f, b))


# Colours as drawn, not as declared: (token made here, colour, drawn over, opacity token).
# The thread sheen is a translucent stroke over the thread core.
DRAWN = [("db-thread-sheen-drawn", "db-thread-sheen", "db-thread", "db-thread-sheen-alpha")]


def lum(hexcolor: str) -> float:
    h = hexcolor.lstrip("#")
    ch = [int(h[i : i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in ch]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def ratio(a: str, b: str) -> float:
    la, lb = lum(a), lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


TEXT, UI = 4.5, 3.0
ENT = ["person", "place", "item", "event", "claim"]
PAIRS = []  # (label, fg, bg, threshold); fg may be a tuple: the object is told apart by its most contrasting part
for e in ENT:
    PAIRS.append((f"{e} label/stroke on board", f"db-{e}-fg", "db-bg-board", TEXT))
    PAIRS.append((f"{e} label/stroke on surface", f"db-{e}-fg", "db-bg-surface", TEXT))
    PAIRS.append((f"{e} text on node fill", "db-text-on-fill", f"db-{e}-fill", TEXT))
    PAIRS.append((f"{e} stroke vs own fill", f"db-{e}-fg", f"db-{e}-fill", UI))
for ed in ("db-edge", "db-edge-support", "db-edge-conflict", "db-edge-unknown"):
    PAIRS.append((f"{ed} line on board", ed, "db-bg-board", UI))
for c in ("db-conf-high", "db-conf-mid", "db-conf-low", "db-refusal", "db-error", "db-ok", "db-warn"):
    PAIRS.append((f"{c} text on surface", c, "db-bg-surface", TEXT))
    PAIRS.append((f"{c} text on board", c, "db-bg-board", TEXT))
for c in ("db-conf-high", "db-conf-mid", "db-conf-low"):
    PAIRS.append((f"{c} bar vs track", c, "db-conf-track", UI))
PAIRS += [
    ("body text on board", "db-text", "db-bg-board", TEXT),
    ("body text on surface", "db-text", "db-bg-surface", TEXT),
    ("body text on surface-2", "db-text", "db-bg-surface-2", TEXT),
    ("muted text on surface", "db-text-muted", "db-bg-surface", TEXT),
    ("muted text on surface-2", "db-text-muted", "db-bg-surface-2", TEXT),
    ("muted text on board", "db-text-muted", "db-bg-board", TEXT),
    ("link on surface", "db-link", "db-bg-surface", TEXT),
    ("quote text on quote highlight", "db-quote-text", "db-quote-bg", TEXT),
    ("quote text on conflict highlight", "db-quote-text", "db-quote-bg-conflict", TEXT),
    ("border vs surface", "db-border", "db-bg-surface", UI),
    ("border vs board", "db-border", "db-bg-board", UI),
    ("focus ring vs surface", "db-focus", "db-bg-surface", UI),
    ("focus ring vs board", "db-focus", "db-bg-board", UI),
    ("selected ring vs board", "db-selected-ring", "db-bg-board", UI),
    ("replay badge text", "db-replay-text", "db-replay-bg", TEXT),
    ("replay badge vs surface", "db-replay-bg", "db-bg-surface", UI),
    ("card pin vs board", "db-pin", "db-bg-board", UI),
    ("card pin vs person fill", "db-pin", "db-person-fill", UI),
    ("cited halo vs board", "db-halo", "db-bg-board", UI),
    ("cited halo vs surface", "db-halo", "db-bg-surface", UI),
    # the board: ink on paper cards, threads and paper on cork, stamps on paper
    ("ink on paper card", "db-ink", "db-paper", TEXT),
    ("muted ink on paper card", "db-ink-muted", "db-paper", TEXT),
    ("ink on photo mount", "db-ink", "db-paper-photo", TEXT),
    ("muted ink on photo mount", "db-ink-muted", "db-paper-photo", TEXT),
    ("stamp ink on paper", "db-stamp", "db-paper", TEXT),
    ("verified stamp on paper", "db-stamp-verified", "db-paper", TEXT),
    ("card edge vs cork", "db-card-edge", "db-cork", UI),
    # every thread variant (about, derived, conditional, unknown, conflict) draws casing, core and sheen
    ("thread vs cork (casing, core or drawn sheen)", ("db-thread", "db-thread-sheen-drawn", "db-thread-casing"), "db-cork", UI),
    ("thread casing vs paper card", "db-thread-casing", "db-paper", UI),
    ("lettering on the wooden frame", "db-frame-text", "db-frame", TEXT),
    ("text on the manila folder", "db-folder-text", "db-folder", TEXT),
]


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).with_name("tokens.css")
    blocks = parse_blocks(path.read_text())
    fails = 0
    for theme, tok in blocks.items():
        print(f"\n== {theme} ==")
        print(f"{'pair':58s} {'fg':8s} {'bg':8s} {'ratio':>6s} {'need':>5s}  result")
        for label, fg, bg, need in PAIRS:
            r, fg = max((ratio(tok[f], tok[bg]), f) for f in (fg if isinstance(fg, tuple) else (fg,)))
            ok = r >= need
            fails += not ok
            print(f"{label:58s} {tok[fg]:8s} {tok[bg]:8s} {r:6.2f} {need:5.1f}  {'ok' if ok else 'FAIL'}")
    print(f"\nfailures: {fails}")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
