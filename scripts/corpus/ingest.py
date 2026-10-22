"""Clean Gutenberg Holmes collections, split into stories and paragraph chunks.

Reads data/raw/<collection>.txt, writes data/clean/<story>.txt and data/chunks.jsonl.
Stdlib only. Chunk text is exactly clean[char_start:char_end] (offsets in code points).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"
CLEAN = ROOT / "data" / "clean"
CHUNKS = ROOT / "data" / "chunks.jsonl"

MIN_WORDS = 250
MAX_WORDS = 350
TAIL_MERGE_WORDS = 120

# collection -> ordered list of (slug, title, exact heading line). The heading list must cover
# every story of the collection so that story boundaries are found; `keep` selects the corpus.
COLLECTIONS: dict[str, list[tuple[str, str, str]]] = {
    "adventures": [
        ("scandal-in-bohemia", "A Scandal in Bohemia", "I. A SCANDAL IN BOHEMIA"),
        ("red-headed-league", "The Red-Headed League", "II. THE RED-HEADED LEAGUE"),
        ("case-of-identity", "A Case of Identity", "III. A CASE OF IDENTITY"),
        (
            "boscombe-valley-mystery",
            "The Boscombe Valley Mystery",
            "IV. THE BOSCOMBE VALLEY MYSTERY",
        ),
        ("five-orange-pips", "The Five Orange Pips", "V. THE FIVE ORANGE PIPS"),
        (
            "man-with-the-twisted-lip",
            "The Man with the Twisted Lip",
            "VI. THE MAN WITH THE TWISTED LIP",
        ),
        (
            "blue-carbuncle",
            "The Adventure of the Blue Carbuncle",
            "VII. THE ADVENTURE OF THE BLUE CARBUNCLE",
        ),
        (
            "speckled-band",
            "The Adventure of the Speckled Band",
            "VIII. THE ADVENTURE OF THE SPECKLED BAND",
        ),
        (
            "engineers-thumb",
            "The Adventure of the Engineer's Thumb",
            "IX. THE ADVENTURE OF THE ENGINEER’S THUMB",
        ),
        (
            "noble-bachelor",
            "The Adventure of the Noble Bachelor",
            "X. THE ADVENTURE OF THE NOBLE BACHELOR",
        ),
        (
            "beryl-coronet",
            "The Adventure of the Beryl Coronet",
            "XI. THE ADVENTURE OF THE BERYL CORONET",
        ),
        (
            "copper-beeches",
            "The Adventure of the Copper Beeches",
            "XII. THE ADVENTURE OF THE COPPER BEECHES",
        ),
    ],
    "memoirs": [
        ("silver-blaze", "Silver Blaze", "I. Silver Blaze"),
        (
            "cardboard-box",
            "The Adventure of the Cardboard Box",
            "II. The Adventure of the Cardboard Box",
        ),
        ("yellow-face", "The Yellow Face", "III. The Yellow Face"),
        ("stockbrokers-clerk", "The Stockbroker's Clerk", "IV. The Stockbroker’s Clerk"),
        ("gloria-scott", "The Gloria Scott", "V. The “_Gloria Scott_”"),
        ("musgrave-ritual", "The Musgrave Ritual", "VI. The Musgrave Ritual"),
        ("reigate-squires", "The Reigate Squires", "VII. The Reigate Squires"),
        ("crooked-man", "The Crooked Man", "VIII. The Crooked Man"),
        ("resident-patient", "The Resident Patient", "IX. The Resident Patient"),
        ("greek-interpreter", "The Greek Interpreter", "X. The Greek Interpreter"),
        ("naval-treaty", "The Naval Treaty", "XI. The Naval Treaty"),
        ("final-problem", "The Final Problem", "XII. The Final Problem"),
    ],
    "return": [
        ("empty-house", "The Adventure of the Empty House", "THE ADVENTURE OF THE EMPTY HOUSE"),
        (
            "norwood-builder",
            "The Adventure of the Norwood Builder",
            "THE ADVENTURE OF THE NORWOOD BUILDER",
        ),
        ("dancing-men", "The Adventure of the Dancing Men", "THE ADVENTURE OF THE DANCING MEN"),
        (
            "solitary-cyclist",
            "The Adventure of the Solitary Cyclist",
            "THE ADVENTURE OF THE SOLITARY CYCLIST",
        ),
        (
            "priory-school",
            "The Adventure of the Priory School",
            "THE ADVENTURE OF THE PRIORY SCHOOL",
        ),
        ("black-peter", "The Adventure of Black Peter", "THE ADVENTURE OF BLACK PETER"),
        (
            "charles-augustus-milverton",
            "The Adventure of Charles Augustus Milverton",
            "THE ADVENTURE OF CHARLES AUGUSTUS MILVERTON",
        ),
        (
            "six-napoleons",
            "The Adventure of the Six Napoleons",
            "THE ADVENTURE OF THE SIX NAPOLEONS",
        ),
        (
            "three-students",
            "The Adventure of the Three Students",
            "THE ADVENTURE OF THE THREE STUDENTS",
        ),
        (
            "golden-pince-nez",
            "The Adventure of the Golden Pince-Nez",
            "THE ADVENTURE OF THE GOLDEN PINCE-NEZ",
        ),
        (
            "missing-three-quarter",
            "The Adventure of the Missing Three-Quarter",
            "THE ADVENTURE OF THE MISSING THREE-QUARTER",
        ),
        ("abbey-grange", "The Adventure of the Abbey Grange", "THE ADVENTURE OF THE ABBEY GRANGE"),
        ("second-stain", "The Adventure of the Second Stain", "THE ADVENTURE OF THE SECOND STAIN"),
    ],
    "last_bow": [
        ("wisteria-lodge", "The Adventure of Wisteria Lodge", "The Adventure of Wisteria Lodge"),
        (
            "bruce-partington-plans",
            "The Adventure of the Bruce-Partington Plans",
            "The Adventure of the Bruce-Partington Plans",
        ),
        ("devils-foot", "The Adventure of the Devil's Foot", "The Adventure of the Devil’s Foot"),
        ("red-circle", "The Adventure of the Red Circle", "The Adventure of the Red Circle"),
        (
            "lady-frances-carfax",
            "The Disappearance of Lady Frances Carfax",
            "The Disappearance of Lady Frances Carfax",
        ),
        (
            "dying-detective",
            "The Adventure of the Dying Detective",
            "The Adventure of the Dying Detective",
        ),
        ("his-last-bow", "His Last Bow", "His Last Bow: The War Service of Sherlock Holmes"),
    ],
    "casebook": [
        (
            "illustrious-client",
            "The Adventure of the Illustrious Client",
            "THE ADVENTURE OF THE ILLUSTRIOUS CLIENT",
        ),
        (
            "blanched-soldier",
            "The Adventure of the Blanched Soldier",
            "THE ADVENTURE OF THE BLANCHED SOLDIER",
        ),
        (
            "mazarin-stone",
            "The Adventure of the Mazarin Stone",
            "THE ADVENTURE OF THE MAZARIN STONE",
        ),
        ("three-gables", "The Adventure of the Three Gables", "THE ADVENTURE OF THE THREE GABLES"),
        (
            "sussex-vampire",
            "The Adventure of the Sussex Vampire",
            "THE ADVENTURE OF THE SUSSEX VAMPIRE",
        ),
        (
            "three-garridebs",
            "The Adventure of the Three Garridebs",
            "THE ADVENTURE OF THE THREE GARRIDEBS",
        ),
        ("thor-bridge", "The Problem of Thor Bridge", "THE PROBLEM OF THOR BRIDGE"),
        ("creeping-man", "The Adventure of the Creeping Man", "THE ADVENTURE OF THE CREEPING MAN"),
        ("lions-mane", "The Adventure of the Lion's Mane", "THE ADVENTURE OF THE LION'S MANE"),
        (
            "veiled-lodger",
            "The Adventure of the Veiled Lodger",
            "THE ADVENTURE OF THE VEILED LODGER",
        ),
        (
            "shoscombe-old-place",
            "The Adventure of Shoscombe Old Place",
            "THE ADVENTURE OF SHOSCOMBE OLD PLACE",
        ),
        (
            "retired-colourman",
            "The Adventure of the Retired Colourman",
            "THE ADVENTURE OF THE RETIRED COLOURMAN",
        ),
    ],
}

# Stories kept in the corpus (witness testimony / alibi / inquest heavy).
KEEP = {
    "scandal-in-bohemia",
    "red-headed-league",
    "boscombe-valley-mystery",
    "man-with-the-twisted-lip",
    "blue-carbuncle",
    "speckled-band",
    "beryl-coronet",
    "copper-beeches",
    "silver-blaze",
    "musgrave-ritual",
    "reigate-squires",
    "crooked-man",
    "resident-patient",
    "naval-treaty",
    "norwood-builder",
    "priory-school",
    "black-peter",
    "abbey-grange",
    "wisteria-lodge",
    "thor-bridge",
}

# Section markers: bare roman numeral ("I", "II.") or numbered sub-title ("1. The Tiger of San Pedro").
SECTION_RE = re.compile(r"^(?:[IVX]+\.?|\d+\.(?: .{1,80})?)$")
# Per-story leading lines (sub-title echoes of the table of contents) removed from the story.
LEADING_JUNK = {
    "wisteria-lodge": "The Singular Experience of Mr. John Scott Eccles The Tiger of San Pedro"
}
MIN_FLUSH_WORDS = 150
START_RE = re.compile(r"^\*\*\* START OF .*\*\*\*\s*$", re.M)
END_RE = re.compile(r"^\*\*\* END OF .*\*\*\*\s*$", re.M)


@dataclass
class Para:
    text: str
    start: int
    end: int
    section: str
    words: int


def strip_gutenberg(raw: str) -> str:
    """Return the body between the Gutenberg START and END markers."""
    start = START_RE.search(raw)
    end = END_RE.search(raw)
    if not start or not end:
        raise ValueError("Gutenberg START/END markers not found")
    return raw[start.end() : end.start()]


def split_stories(body: str, entries: list[tuple[str, str, str]]) -> dict[str, str]:
    """Slice the body into raw story texts by heading lines (last exact match = after the TOC)."""
    lines = body.splitlines()
    stripped = [ln.strip() for ln in lines]
    starts: list[tuple[int, str]] = []
    for slug, _title, heading in entries:
        idx = [i for i, ln in enumerate(stripped) if ln == heading]
        if not idx:
            raise ValueError(f"heading not found: {heading!r}")
        starts.append((idx[-1], slug))
    starts.sort()
    out: dict[str, str] = {}
    for n, (i, slug) in enumerate(starts):
        j = starts[n + 1][0] if n + 1 < len(starts) else len(lines)
        out[slug] = "\n".join(lines[i + 1 : j])  # drop the heading line itself
    return out


def clean_story(text: str, slug: str = "") -> str:
    """Normalise one story: dedent, unwrap hard-wrapped lines, one blank line between paragraphs."""
    paras: list[str] = []
    cur: list[str] = []
    for line in text.replace("\r\n", "\n").split("\n"):
        line = line.strip()
        if line:
            cur.append(line)
        elif cur:
            paras.append(" ".join(cur))
            cur = []
    if cur:
        paras.append(" ".join(cur))
    if paras and paras[0] == LEADING_JUNK.get(slug):
        paras.pop(0)
    while paras and SECTION_RE.match(paras[-1]):  # next story's numeral (casebook layout)
        paras.pop()
    return "\n\n".join(paras) + "\n"


def paragraphs(clean: str) -> list[Para]:
    """Paragraphs of a cleaned story with char offsets; bare roman numerals are section markers."""
    result: list[Para] = []
    section = ""
    pos = 0
    for block in clean.split("\n\n"):
        start = clean.index(block, pos)
        end = start + len(block.rstrip("\n"))
        pos = end
        text = clean[start:end]
        if SECTION_RE.match(text):
            section = text.rstrip(".")
            continue
        result.append(Para(text, start, end, section, len(text.split())))
    return result


def chunk_paragraphs(paras: list[Para]) -> list[list[Para]]:
    groups: list[list[Para]] = []
    cur: list[Para] = []
    words = 0
    for p in paras:
        if cur and words + p.words > MAX_WORDS and words >= MIN_FLUSH_WORDS:
            groups.append(cur)
            cur, words = [], 0
        cur.append(p)
        words += p.words
    if cur:
        if groups and words < TAIL_MERGE_WORDS:
            groups[-1].extend(cur)
        else:
            groups.append(cur)
    return groups


def build_chunks(slug: str, clean: str) -> list[dict]:
    paras = paragraphs(clean)
    index = {id(p): i for i, p in enumerate(paras)}
    rows = []
    for n, grp in enumerate(chunk_paragraphs(paras)):
        a, b = grp[0], grp[-1]
        rows.append(
            {
                "chunk_id": f"{slug}-{n:04d}",
                "story": slug,
                "section": a.section,
                "para_start": index[id(a)],
                "para_end": index[id(b)],
                "char_start": a.start,
                "char_end": b.end,
                "text": clean[a.start : b.end],
            }
        )
    return rows


def run(raw_dir: Path = RAW, clean_dir: Path = CLEAN, out: Path = CHUNKS) -> dict:
    clean_dir.mkdir(parents=True, exist_ok=True)
    stories = chunks = words = 0
    with out.open("w", encoding="utf-8") as fh:
        for coll, entries in COLLECTIONS.items():
            raw = (raw_dir / f"{coll}.txt").read_text(encoding="utf-8-sig")
            for slug, text in split_stories(strip_gutenberg(raw), entries).items():
                if slug not in KEEP:
                    continue
                clean = clean_story(text, slug)
                (clean_dir / f"{slug}.txt").write_text(clean, encoding="utf-8")
                rows = build_chunks(slug, clean)
                for r in rows:
                    fh.write(json.dumps(r, ensure_ascii=False) + "\n")
                stories += 1
                chunks += len(rows)
                words += len(clean.split())
    return {"stories": stories, "chunks": chunks, "words": words}


if __name__ == "__main__":
    print(run())
