#!/usr/bin/env python3
"""Build the fresh held-out cases from Project Gutenberg 'The Innocence of Father Brown' (#204).

    python eval/suspects/prepare_heldout.py /path/to/father-brown.txt

Writes data/heldout/clean/<slug>.txt (cleaned with scripts/corpus/ingest.py), data/heldout/chunks.jsonl (only the
chunks before each cut, same chunker as the main corpus), eval/suspects/heldout_cases.jsonl and
eval/suspects/heldout_manifest.json (sha256 of the raw file). The truth (culprit, cleared, victim) and the cut come
from reading each story's explanation; they are AI-marked and need a human check.
The three novels the user also approved (Styles, Sign of the Four, Study in Scarlet) are real whodunits but their
text before the reveal (72 to 277 thousand characters) does not fit the 14k-token context of the frozen method, so
they are NOT used.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "corpus"))
import ingest  # noqa: E402

# slug, title in the book, cut anchor (the cut is the start of the paragraph that contains it), question,
# kind, culprit names, cleared names, victim names, note
CASES = [
    ("fb-hammer-of-god", "The Hammer of God", "“Might be the map of the world, mightn’t it?”",
     "Who killed Colonel Norman Bohun?", "human", ["Wilfred Bohun", "Wilfred"],
     ["Simeon Barnes", "Simeon"], ["Norman Bohun"],
     "The blacksmith is suspected by the village; the killer is the colonel's priest brother."),
    ("fb-invisible-man", "The Invisible Man", "“There is only one thing to be done,” said Flambeau",
     "Who killed Isidore Smythe?", "human", ["Welkin", "James Welkin"], [], ["Isidore Smythe"],
     "Welkin is named as the writer of threats before the cut; the twist is how he got in."),
    ("fb-secret-garden", "The Secret Garden", "Father Brown had turned round at last",
     "Who killed Julius K. Brayne?", "human", ["Aristide Valentin", "Valentin"], [],
     ["Julius K. Brayne", "Brayne"], "The culprit is the chief of police who runs the investigation."),
    ("fb-eye-of-apollo", "The Eye of Apollo", "Father Brown suddenly sprang erect",
     "Who killed Pauline Stacey?", "human", ["Kalon"], ["Joan Stacey", "Joan"], ["Pauline Stacey"],
     "Kalon accuses the sister Joan out loud; Joan only committed the smaller crime."),
    ("fb-three-tools", "The Three Tools of Death", "“Sir,” said Alice Armstrong in a low tone",
     "Who killed Sir Aaron Armstrong?", "non_human", ["accident", "mad"], ["Patrick Royce", "Royce"],
     ["Aaron Armstrong"], "Armstrong died in a fall while delirious; no murderer. His daughter's cut rope was an accident."),
    ("fb-wrong-shape", "The Wrong Shape", "“Of all these crooked things, the crookedest was the shape of that piece of paper.",
     "Who killed Leonard Quinton?", "human", ["James Erskine Harris", "Harris", "Dr. Harris"], [],
     ["Leonard Quinton"], "The doctor stages a suicide; revealed by his own letter at the end."),
]  # fmt: skip
TITLES = ["The Blue Cross", "The Secret Garden", "The Queer Feet", "The Flying Stars", "The Invisible Man",
          "The Honour of Israel Gow", "The Wrong Shape", "The Sins of Prince Saradine",
          "The Hammer of God", "The Eye of Apollo", "The Sign of the Broken Sword",
          "The Three Tools of Death"]  # fmt: skip


def main() -> None:
    raw_path = Path(sys.argv[1])
    raw = raw_path.read_text()
    lines = ingest.strip_gutenberg(raw).splitlines()
    strip = [ln.strip() for ln in lines]
    starts = sorted((max(i for i, ln in enumerate(strip) if ln == t), t) for t in TITLES)
    stories = {}
    for n, (i, t) in enumerate(starts):
        j = starts[n + 1][0] if n + 1 < len(starts) else len(lines)
        stories[t] = ingest.clean_story("\n".join(lines[i + 1 : j]))
    out = ROOT / "data" / "heldout"
    (out / "clean").mkdir(parents=True, exist_ok=True)
    cases, chunk_rows = [], []
    for slug, title, anchor, q, kind, cul, clr, vic, note in CASES:
        text = stories[title]
        a = text.find(anchor)
        assert a > 0 and text.count(anchor) == 1, (slug, a)
        cut = text.rfind("\n\n", 0, a) + 2  # start of the paragraph holding the anchor
        (out / "clean" / f"{slug}.txt").write_text(text)
        rows = [r for r in ingest.build_chunks(slug, text) if r["char_end"] <= cut]
        chunk_rows += rows
        cases.append({
            "id": "su-" + slug, "story": slug, "question": q, "cut_char": cut, "culprit_kind": kind,
            "culprit_names": cul, "cleared_names": clr, "victim_names": vic, "solvable": "partly",
            "solvable_by": "AI (to be human-checked)", "note": note, "source": "Gutenberg #204",
        })  # fmt: skip
        print(f"{slug}: cut {cut} of {len(text)}, {len(rows)} pre-cut chunks")
    (out / "chunks.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in chunk_rows) + "\n"
    )
    (ROOT / "eval" / "suspects" / "heldout_cases.jsonl").write_text(
        "\n".join(json.dumps(c, ensure_ascii=False) for c in cases) + "\n"
    )
    manifest = {"source": "https://www.gutenberg.org/cache/epub/204/pg204.txt", "bytes": len(raw.encode()),
                "sha256": hashlib.sha256(raw.encode()).hexdigest(), "ebook": "The Innocence of Father Brown #204"}  # fmt: skip
    (ROOT / "eval" / "suspects" / "heldout_manifest.json").write_text(
        json.dumps(manifest, indent=1)
    )


if __name__ == "__main__":
    main()
