# Symbolic layer

Status: DRAFT, Phase 0, design only. Nothing was implemented or run. Decision record: `docs/adr/0004-symbolic-layer.md` (Proposed: plain Python rules). Data model: `docs/data-schema.md`. Tool contracts: `docs/mcp-contracts.md`. Marks: **[P]** provisional, **[U]** unverified, **[R]** requires a change in another zone (section 9).

## 0. Principle and limitation

Neuro-symbolic split:

- Neural, probabilistic: the LLM extracts entities, events, claims, relations from text (`extract/schema.py`). Output: provenance `extracted`.
- Storage: the graph (SQLite `g_node`/`g_edge`, optionally Ladybug), every fact with a source anchor.
- Symbolic, deterministic: rules R1-R3 read the graph and produce `derived` conclusions with an explanation. Same graph snapshot + same rule versions = same output, byte for byte. No LLM, no network, no randomness, no clock.

**Limitation (stated plainly): extraction errors pass into the symbolic layer.** A wrong participant, a wrong place or a misread time that is grounded in a real quote is indistinguishable from a right one to the rules. The layer guarantees that the conclusion follows from the stored facts, not that the facts are true. The mitigation is transparency: every conclusion lists the extracted facts it depends on, and a conclusion resting on a low-confidence fact is marked `conditional`. The layer never says "the alibi is false", only "the stored facts X and Y contradict each other".

## 1. Data model consumed

The layer reads a `FactBase`: an immutable snapshot built from the graph for one story (or a set of stories) by `load_facts(store, story)`. It never reads text or calls the model.

| Concept | Source in graph | Fields used |
|---|---|---|
| `Person` | node `person` | `id`, `name`, `aliases[]` |
| `Place` | node `place` | `id`, `name`, `aliases[]`, canonical id and parent (section 5) |
| `Event` | node `event` | `id`, `description`, `time_text`, `time_norm`, `place_id?`, participants via `PARTICIPATED_IN`, anchor |
| `Claim` | node `claim` | `id`, `speaker_id`, `content`, `about_id?`, `prop?` (structured proposition **[R]**), anchor |
| `Order edge` | `time_norm.rel` + `ref_event_id` | `rel in {before, after, during, at}`, reference event |
| `Anchor` | on every edge and on Event/Claim | `story`, `chunk_id`, `char_start`, `char_end`, `quote`, `ambiguous` (data-schema 3.3) |

### 1.1 Time

`Event.time_norm` (data-schema 3.1) is produced by the `time_norm` post-processor, never by the LLM. The layer needs an interval, which 3.1 only hints at (`range_min`/`range_max` **[P]**) **[R]**. The layer's own normalised type:

```
TimeSpec:
  day:   int | None          # story_day; None = unknown day
  lo:    int | None          # outer bound, minute of day, inclusive; None = unknown
  hi:    int | None          # outer bound, minute of day, inclusive
  exact: bool                # True: the event occupies exactly [lo, hi]; False: it lies somewhere inside [lo, hi]
  rel:   Rel | None          # relative anchoring, see below
  ref_event_id: str | None
  confidence: "high" | "low"
```

Absolute axis: `t = day * 1440 + minute`. A span has absolute bounds only if `day` and `lo`/`hi` are all known. Cases:

| Source text | TimeSpec |
|---|---|
| "at nine o'clock", day known | `exact=True, lo=hi=540` (an instant) |
| "from nine to eleven" | `exact=True, lo=540, hi=660` (interval, half-open for overlap purposes, see R1) |
| "that evening", "in the morning" | `exact=False`, lo/hi from a fixed lexicon **[P]**: morning 360-720, afternoon 720-1080, evening 1080-1320, night 1320-1440 (the wrap past midnight is not modelled: `night` spans only to 1440), `confidence=low` |
| "the next morning" | `rel=after, ref_event_id=<e>`, `day = ref.day + 1` only if the reference day is known, lexicon for the part of day; else day unknown |
| "later", "soon", "a little before" | `rel` set, no minutes: order information only, no interval |
| nothing / unparseable | all `None`, `rel=None` |

Narration order is **not** time: the order in which events appear in the text is never used as chronological evidence (flashbacks, stories told afterwards). Only `time_norm` yields time facts.

### 1.2 Claim proposition **[R]**

`Claim.content` is a free-text sentence, which is not checkable. R3 needs a structured form produced by an extraction/normalisation step (outside this layer, itself `extracted` with confidence):

```
Prop = PresenceProp(person_id, place_id, TimeSpec)      # "I was at the club at nine"
     | OrderProp(before_event_id, after_event_id)        # "he left before the shot"
```

`Claim.prop is None` means "unstructured": R3 returns `unknown` with reason `UNSTRUCTURED_CLAIM`. More proposition kinds can be added later without changing the interface.

## 2. Provenance, confidence, conditional

Every fact the layer touches has a provenance label:

| Label | Produced by | Carries | Trust |
|---|---|---|---|
| `extracted` | the model (and deterministic post-processing of its output: anchor resolution, `time_norm`, alias resolution) | `confidence`, anchor with quote | probabilistic |
| `derived` | a rule of this layer | `rule_id`, `rule_version`, `premises` (fact ids), `Explanation` | deterministic given its premises |

`derived` facts are computed on demand and never written back into `g_edge` in the same table as extracted facts. If materialised (cache, UI) they go to a separate table with `provenance='derived'` and the snapshot digest **[P]**:

```sql
CREATE TABLE g_derived (
  id TEXT PRIMARY KEY,            -- d:<rule_id>:<hash of premises>
  rule_id TEXT NOT NULL, rule_version TEXT NOT NULL, snapshot_digest TEXT NOT NULL,
  verdict TEXT NOT NULL, conditional INTEGER NOT NULL, explanation_json TEXT NOT NULL
);
```

### 2.1 Confidence of extracted facts

`schema.py` has no model-reported confidence field. Do not invent one. Confidence is computed deterministically upstream from signals the pipeline already has and handed to the layer as `high|low` (plus an optional `score`):

| Signal | `low` if |
|---|---|
| Anchor | quote found more than once (`ambiguous=true`) or only relative offsets valid (data-schema section 1) |
| Time | `time_norm.confidence == low`, lexicon-derived (`exact=False`), or relative to an event whose own time is low |
| Entity resolution | alias matched more than one entity, or matched by fuzzy method (`SAME_AS.method` is not exact) |
| Event participants/place | participant or place name had no exact entity match |
| Claim proposition | produced by the normaliser with low confidence |
| Agreement (optional) **[P]** | the same fact was not reproduced by a second extraction run/model |

A fact is `low` if any applicable signal is `low`. The thresholds are rules, not model outputs, so the confidence itself is reproducible. Numeric `score` (0-1) is optional **[P]**; if present, `low` means `score < 0.7` **[P]**. Eval may later calibrate these signals against gold cases.

### 2.2 The `conditional` rule

A derived conclusion `D` with premise set `P(D)`:

- `depends_on_extracted(D)` = all extracted facts reachable through `P` (transitively through intermediate derived facts), each with its confidence.
- `weak(D)` = the subset with `confidence == low`.
- `conditional(D) = (weak(D) != empty)`.

A conditional conclusion is shown and returned, never hidden, but the agent must phrase it as "if fact F is right, then ..." and cite the weak facts. A non-conditional conclusion is "high-confidence given extraction", not "true". `unknown` conclusions have no premise-based conditional flag; they list `missing` (what would be needed).

## 3. Result model

Three-valued verdict, plus the orthogonal `conditional` flag:

| Verdict | Meaning |
|---|---|
| `violated` | the stored facts contradict the rule: a definite overlap/cycle/incompatibility exists |
| `consistent` | the rule is satisfied for the examined facts (definite disjointness, definite order, corroboration). It is not a proof that nothing is wrong elsewhere |
| `unknown` | the facts do not decide: missing or fuzzy time, ambiguous place, unstructured claim, no path. Always with a `reason_code` and `missing[]` |

Closed-world is never assumed: absence of a fact never yields `consistent` or `violated`, only `unknown`.

### 3.1 Explanation object

```json
{
  "rule_id": "R1",
  "rule_version": "1",
  "verdict": "violated",
  "conditional": true,
  "reason_code": "OVERLAP_DIFFERENT_PLACES",
  "subject": {"person_id": "p:s:holmes"},
  "facts": [
    {"fact_id": "e:s-0007:2", "kind": "event", "provenance": "extracted", "confidence": "high",
     "summary": "Holmes at Baker Street, 21:00-22:00", "anchors": []}
  ],
  "edges": [
    {"edge_id": 118, "rel": "PARTICIPATED_IN", "src": "p:s:holmes", "dst": "e:s-0007:2", "anchors": []},
    {"edge_id": 121, "rel": "OCCURRED_AT", "src": "e:s-0007:2", "dst": "pl:s:baker-street", "anchors": []}
  ],
  "derivation": [
    {"step": 1, "op": "interval_overlap", "inputs": ["e:s-0007:2", "e:s-0009:1"], "output": "overlap [21:30,22:00)"},
    {"step": 2, "op": "place_distinct", "inputs": ["pl:s:baker-street", "pl:s:docks"], "output": "DISTINCT"}
  ],
  "anchors": [
    {"story": "s", "chunk_id": "s-0007", "char_start": 10234, "char_end": 10301, "quote": "verbatim", "rel_start": 112, "rel_end": 179}
  ],
  "depends_on_extracted": [{"fact_id": "e:s-0007:2", "confidence": "high"}, {"fact_id": "e:s-0009:1", "confidence": "low"}],
  "weak": ["e:s-0009:1"],
  "missing": [],
  "notes": ["travel time between places is not modelled"]
}
```

Rules for the object: (1) every fact and edge it names carries at least one anchor with a verbatim `quote` (the same invariant as data-schema 3.3); a `violated`/`consistent` finding without an anchor is a bug; (2) `facts`/`edges` are exactly those read by the rule on the decisive path, sorted by id; (3) `derivation` is a short ordered list of machine-readable steps so a UI or test can replay it; (4) `anchors` is the deduplicated union of all anchors, in `(story, char_start)` order; (5) the object is JSON-serialisable with no floats other than optional scores.

## 4. Rules

Common definitions. Interval overlap for spans `A=[a1,a2]`, `B=[b1,b2]` on the absolute axis: if both are non-degenerate (`a1<a2` and `b1<b2`), half-open: `a1 < b2 and b1 < a2` (touching intervals do not overlap). If at least one is an instant (`x1 == x2`): closed: `a1 <= b2 and b1 <= a2`. Instants are only comparable if both are `exact`.

Definite overlap `DEF_OVERLAP(A,B)`: both `exact` with known day and minutes, and the overlap test holds. Definite disjointness `DEF_DISJOINT(A,B)`: both days known and the *outer* bounds `[lo,hi]` fail the overlap test (so fuzzy spans prove disjointness when even their widest extents do not meet). Otherwise `UNDECIDED`.

`PlaceRel(P,Q)` in `{SAME, CONTAINS (either direction), DISTINCT, UNKNOWN}`, section 5.

### R1. One person, one place at a time

Formal condition. For person `p`, events `e1 != e2` with `p in participants(e1) and p in participants(e2)`, `place(e1)=P`, `place(e2)=Q`, spans `A=time(e1)`, `B=time(e2)`:

```
violated   iff  DEF_OVERLAP(A,B) and PlaceRel(P,Q) == DISTINCT and not same_occurrence(e1,e2)
consistent iff  DEF_DISJOINT(A,B)  or  PlaceRel(P,Q) in {SAME, CONTAINS}   # with the overlap being definite or undecided
unknown    otherwise  (UNDECIDED time, PlaceRel UNKNOWN, either place/time missing)
```

Precedence: if time is `DEF_OVERLAP` and place is `UNKNOWN` -> `unknown` (`PLACE_UNRESOLVED`); if time is `UNDECIDED` and place is `DISTINCT` -> `unknown` (`TIME_UNDECIDED`, with note `possible_overlap` when outer bounds intersect). `same_occurrence` is true if the two events are linked as duplicates (same `SAME_AS`/merged event) **[P]**; without that link two chunks describing the same occurrence can create a false R1 hit, so the event dedup step is a prerequisite and a documented risk.

Modes of use:

- `scan_presence_conflicts(person=None)`: all pairs, returns `Finding[]` (only `violated` and `unknown` with `possible_overlap` by default; `consistent` on request).
- `check_presence(person, place, window)`: hypothetical event "`person` at `place` during `window`" tested against all of `person`'s events (this is `check_alibi`): `violated` if some event is `DEF_OVERLAP` and `DISTINCT`; `consistent` with kind `supported` if a `DEF_OVERLAP` event is at `SAME/CONTAINS` place; `unknown` otherwise. A window query that has `supported` and `violated` evidence at once returns `violated` and lists both (a contradiction in the data must not be hidden).

Input (scan):

```json
{"story": "string", "person_id": "string|null", "include_consistent": false, "max_findings": 100}
```

Output: `{"rule_id":"R1","findings":[Finding],"stats":{"pairs_examined":int,"violated":int,"unknown":int,"consistent":int},"snapshot_digest":"string"}`.

Input (check_presence): `{"story","person_id","place_id","window":TimeSpec}`. Output: one `Finding`; `kind` in `supported|contradicted|unknown` maps to the MCP statuses (section 8).

Edge cases:

- Partial time (day known, minutes unknown; or minutes known, day unknown): `UNDECIDED`, `unknown`. Never "assume same day".
- Relative time ("the next morning"): resolved only if `ref_event` has a known day, otherwise day unknown. Resolution is a derivation step and inherits the reference's confidence; the result is `exact=False`, so it can prove disjointness (different days) but never a definite overlap.
- Touching intervals (`21:00-22:00` and `22:00-23:00`): not an overlap, consistent. Travel time between distant places is not modelled (note in output); a very tight but legal sequence is therefore `consistent`.
- Instants: `nine o'clock` at place X and `nine o'clock` at place Y on the same day is a definite overlap (violated); precision of the narration ("about nine") is expected in `time_norm.confidence=low`, which makes the finding `conditional`.
- Ambiguous or aliased place names ("the station", "the club", "Baker St" vs "Baker Street"): resolved through the alias table of the `Place` node; if one surface form maps to more than one place, or to none, `PlaceRel=UNKNOWN`. Never decide by string similarity inside the layer.
- Same place at different granularity ("221B Baker Street" in "Baker Street" in "London"): `CONTAINS` -> compatible, never `DISTINCT`. Needs a parent relation (section 5).
- Event without place or without participant link: not examined, counted in `stats.skipped_no_place` / `skipped_no_time`.
- A "went to X" event may describe the destination or the journey; the extraction schema does not distinguish presence from transit. Treated as presence; this is a known source of false `violated` and a reason for `conditional` on motion verbs **[P]** (flag `low` if `description` starts with a motion verb from a fixed list).
- Unreliable extracted facts: handled by `conditional` (section 2.2), not by dropping.

### R2. Order is transitive and acyclic

Fact `BEFORE(a, b)` means event `a` ends before event `b` starts. Sources of order edges (all explicit, none implied by text position):

1. `time_norm.rel == after` with `ref_event_id=r` on event `e`: `BEFORE(r, e)`; `rel == before`: `BEFORE(e, r)`. Provenance `extracted`.
2. Absolute times: if `A.hi < B.lo` on the absolute axis (strict gap; touching spans are disjoint for R1 but not ordered here): `BEFORE(a, b)`. Provenance `derived` from the two time facts (rule `R2.time`).
3. `during`/`at` give no order edge (`CONCURRENT` is not modelled).

Closure: `BEFORE+` = transitive closure; each derived pair stores the shortest path (BFS, ties broken by smallest edge id) as `edges[]`.

```
order(a,b) = "before"  iff  (a,b) in BEFORE+ and (b,a) not in BEFORE+     -> consistent
order(a,b) = "after"   symmetric                                          -> consistent
order(a,b) = "unknown" iff neither in BEFORE+                             -> unknown (NO_PATH)
cycle      : exists e with (e,e) in BEFORE+                                -> violated
```

Cycle detection: strongly connected components (Tarjan or iterative Kosaraju) on the `BEFORE` graph; every SCC with more than one node, or a self-loop, is a `violated` finding with `edges[]` = one minimal cycle (BFS inside the SCC from the smallest node id) and `suspects[]` = the extracted edges of that cycle ordered by lowest confidence first, then by edge id. A minimal cycle is an *indication*, the layer does not decide which edge is wrong.

Input: `{"story":"string","event_ids":["string"]|null}` (cycle scan) and `{"story","a","b"}` (pairwise `order`). Output: `Finding[]`, or `{"order":"before|after|unknown|cyclic","finding":Finding}`.

Edge cases:

- Partial time: events with no interval can still be ordered through relative edges. Events without any edge are `unknown`.
- Relative times: "the next morning" produces `BEFORE(ref, e)` only if the reference is resolvable; otherwise no edge and a `missing` entry.
- Equal or overlapping spans: no order edge (neither before nor after), `unknown` for the pair, not a violation.
- Aliased or duplicate events (the same occurrence extracted twice): must be merged or marked `same_occurrence` before closure, otherwise the duplicate pair can create false cycles through different relative references; documented risk.
- Granularity: an event on day 3 and one "that week" are not ordered unless the week bounds fall strictly before/after.
- Unreliable facts: a cycle through one low-confidence edge is `violated` + `conditional`, `weak=[that edge]`, which is the useful signal "this single extracted relation is probably wrong".
- Narration flashbacks: ignored by design (text position is never evidence).
- Scale: closure by BFS from each node, `O(V*(V+E))`, fine for a few hundred events per story **[U]** measure; compute on demand per story.

### R3. Witness claim vs established fact

Definitions. *Established fact* (`E`): an `Event` (or an order fact) stated in narrator voice (not wrapped by a `Claim` with a speaker), with confidence `high`, or a `derived` fact whose premises are all established. A witness `Claim` with `prop` is a hypothesis, never established by itself. Claim-vs-claim conflicts are out of scope in v1 (no authority to prefer one) and are reported as `unknown` with `CLAIM_VS_CLAIM`.

```
PresenceProp(p, X, T):  violated   iff exists established presence (p, Y, U) with DEF_OVERLAP(T,U) and PlaceRel(X,Y) == DISTINCT
                        consistent iff exists established presence with DEF_OVERLAP(T,U) and PlaceRel in {SAME, CONTAINS}     (corroborated)
                        unknown    otherwise
OrderProp(a, b):        violated   iff (b,a) in BEFORE+ over established order facts
                        consistent iff (a,b) in BEFORE+ over established order facts
                        unknown    otherwise
```

If a claim is both corroborated and contradicted by different established facts, the verdict is `violated` with both listed (the established base is itself inconsistent, and R1/R2 will also flag it). The witness is not called a liar: the finding is `claim_incompatible_with_fact`.

Input: `{"story","claim_id":"string"}` or `{"story","speaker_id":"string"|null}` for a scan. Output: `Finding` per claim with the claim anchor plus the anchors of the established facts used, so the agent can cite both quotes (PRD: "output lists both quotes").

Edge cases:

- Unstructured claim (`prop is None`): `unknown`, `UNSTRUCTURED_CLAIM`.
- Partial or relative time inside the claim: same TimeSpec rules as R1; no definite overlap -> `unknown`.
- Ambiguous place in the claim or the fact: `PlaceRel=UNKNOWN` -> `unknown`.
- Same place at different granularity: compatible, `consistent` (corroborated), never contradicted.
- The established fact is itself low confidence: it is not "established" (above). The layer may still report `violated` against a low-confidence event, but then the finding is `conditional` and the label is `claim_vs_extracted_event`, not `claim_vs_established`. Which of the two behaviours is on by default is **[P]**: default is to include it, always conditional.
- The speaker is unreliable by plot (a liar, mistaken, mistaken identity): the layer does not model unreliable narrators; an established narrator fact may itself be a first-person account. Stated in `notes`.
- Quotes: a claim or fact whose anchor failed the verbatim check is never used (it was dropped at extraction, data-schema 3.3).

## 5. Places: aliases and granularity

The layer needs `PlaceRel`. Source of truth, in order:

1. `Place.aliases` from extraction, merged by exact normalised string (lower-case, whitespace collapsed, leading "the" removed) into canonical places by the entity-resolution step (not by this layer).
2. A hand-curated gazetteer `data/gazetteer/places.yaml` (canonical id, aliases, `parent` id) for the Holmes corpus **[R]**. Deterministic, reviewable, small. If an alias is listed under two canonical places it is *ambiguous* and resolves to `UNKNOWN`.
3. `RELATION` edges whose predicate is in a fixed set {"in", "inside", "part of", "near"} **[P]**: `in/inside/part of` give containment (`extracted`, confidence applies); `near` gives nothing (not containment).

`PlaceRel(P,Q)`: `SAME` if canonical ids are equal; `CONTAINS` if one is an ancestor of the other; `DISTINCT` only if both resolve uniquely to canonical places, neither is an ancestor of the other and they are not linked as the same place; otherwise `UNKNOWN`. Siblings of a common parent are `DISTINCT` (two rooms in one house are different places, which is correct for R1 only if the rooms have no `parent` chain at that level: the gazetteer decides the level; coarse "Baker Street" vs "Baker Street 221B" are ancestor-related and so compatible).

## 6. Conclusion object returned to callers

```
Finding = {
  "finding_id": "R1:<hash of sorted fact ids>",     # stable, deterministic
  "rule_id": "R1|R2|R3", "rule_version": "1",
  "verdict": "violated|consistent|unknown",
  "conditional": bool,
  "provenance": "derived",
  "reason_code": "string",
  "explanation": Explanation,                       # section 3.1
  "snapshot_digest": "string"
}
```

`finding_id` and ordering of findings are deterministic: sorted by `(rule_id, verdict rank, finding_id)`.

## 7. Implementation shape (ADR-0004)

- Package `src/detective_board/symbolic/`; modules `model.py` (dataclasses/pydantic), `facts.py` (`FactBase`, `load_facts`), `time.py`, `places.py`, `rules/r1_presence.py`, `rules/r2_order.py`, `rules/r3_claims.py`, `api.py` (public functions, section 8). Contract stubs may re-export from `src/detective_board/contracts/` (tech-lead zone).
- Pure functions on an immutable `FactBase`. Only `load_facts` does I/O. No LLM, no network, no wall-clock, no `random`, no set/dict iteration without sorting.
- Rule registry: `RULES: dict[str, Rule]`; adding a rule = a function + id + version + tests. The `FactBase` normalisation (typed events with `TimeSpec`, place relations, order edges) is also what a Datalog backend would consume if ADR-0004 is ever reversed.
- `snapshot_digest` = sha256 over the sorted canonical JSON of facts used by the loaded story + rule versions (cheap, `hashlib`).

## 8. Python interface (single source of truth)

Both the agent and the `timeline-alibi` MCP server import only `detective_board.symbolic.api`. Models are pydantic v2 (`frozen=True`, `extra="forbid"`, like `extract/schema.py`), so the MCP output schemas can be generated from them. Signature sketch (final names settled at implementation; behaviour fixed by this spec):

```python
from __future__ import annotations
from enum import StrEnum
from typing import Literal, Protocol
from pydantic import BaseModel, ConfigDict

class _M(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

class Verdict(StrEnum):
    VIOLATED = "violated"; CONSISTENT = "consistent"; UNKNOWN = "unknown"

Confidence = Literal["high", "low"]
Rel = Literal["before", "after", "during", "at"]

class Anchor(_M):
    story: str; chunk_id: str; char_start: int; char_end: int; quote: str
    rel_start: int | None = None; rel_end: int | None = None; ambiguous: bool = False

class TimeSpec(_M):
    day: int | None = None; lo: int | None = None; hi: int | None = None
    exact: bool = False
    rel: Rel | None = None; ref_event_id: str | None = None
    confidence: Confidence = "low"
    time_text: str | None = None

class FactRef(_M):
    fact_id: str; kind: Literal["event", "claim", "entity", "order", "relation", "derived"]
    provenance: Literal["extracted", "derived"]
    confidence: Confidence | None   # None for derived
    summary: str; anchors: list[Anchor]

class EdgeRef(_M):
    edge_id: int | str; rel: str; src: str; dst: str; anchors: list[Anchor]

class Step(_M):
    step: int; op: str; inputs: list[str]; output: str

class Explanation(_M):
    rule_id: str; rule_version: str; verdict: Verdict; conditional: bool
    reason_code: str
    facts: list[FactRef]; edges: list[EdgeRef]; derivation: list[Step]
    anchors: list[Anchor]
    depends_on_extracted: list[FactRef]; weak: list[str]
    missing: list[str]; notes: list[str]
    subject: dict[str, str] = {}

class Finding(_M):
    finding_id: str; rule_id: str; rule_version: str
    verdict: Verdict; conditional: bool
    provenance: Literal["derived"] = "derived"
    reason_code: str; explanation: Explanation; snapshot_digest: str

class Report(_M):
    rule_id: str; findings: list[Finding]; stats: dict[str, int]; snapshot_digest: str

class FactSource(Protocol):                 # implemented by the GraphStore adapter
    def load(self, story: str) -> "FactBase": ...

class FactBase: ...                          # immutable snapshot, built by load_facts

def load_facts(source: FactSource, story: str) -> FactBase: ...

# R1
def scan_presence_conflicts(fb: FactBase, *, person_id: str | None = None,
                            include_consistent: bool = False, max_findings: int = 100) -> Report: ...
def check_presence(fb: FactBase, *, person_id: str, window: TimeSpec,
                   place_id: str | None = None) -> Finding: ...
# R2
def order_of(fb: FactBase, a: str, b: str) -> Finding: ...
def find_order_cycles(fb: FactBase, *, event_ids: list[str] | None = None) -> Report: ...
def timeline(fb: FactBase, *, person_id: str | None = None, place_id: str | None = None,
             include_undated: bool = False, limit: int = 50) -> list[FactRef]: ...
# R3
def check_claim(fb: FactBase, claim_id: str) -> Finding: ...
def scan_claims(fb: FactBase, *, speaker_id: str | None = None) -> Report: ...
# all rules
def run_all(fb: FactBase, rules: tuple[str, ...] = ("R1", "R2", "R3")) -> list[Report]: ...
```

Mapping to `docs/mcp-contracts.md` tools (the MCP layer only serialises; it adds no logic):

| MCP tool | Calls | Status mapping |
|---|---|---|
| `build_timeline` | `timeline`, plus `find_order_cycles` for a `warnings[]` field | `ok` / `insufficient_evidence` (no dated events) |
| `check_alibi` | `check_presence` | `violated`->`contradicted`, `consistent` with a same-place overlap->`supported`, `unknown`->`unknown` (`insufficient_evidence` when the person has no dated events) |
| `find_overlaps` | `scan_presence_conflicts` | list of findings |
| (new, proposed) `check_claim` | `check_claim` | `violated`->`contradicted` |

**[R]** `mcp-contracts.md` must add `conditional`, `depends_on_extracted` and `reason_code` to the outputs, and note that `window`/`when` are `TimeSpec`-compatible (`Interval` there has no `exact` or `day`-unknown handling). The agent presents `conditional` conclusions in the "if ... then" form and cites the weak facts. Tool errors never turn into `consistent` (ADR-0003).

## 9. Requests to other zones

| Zone | Request |
|---|---|
| graph-engineer (`docs/data-schema.md`) | extend `time_norm` with `lo`, `hi`, `exact`, `day`; add `same_occurrence`/duplicate-event link; define `g_derived` (section 2) if materialised |
| nlp-extraction-engineer | structured `Claim.prop` (`PresenceProp`/`OrderProp`) produced by a normalising step with confidence; events: presence vs transit flag if feasible |
| data-engineer | `data/gazetteer/places.yaml` seed for the corpus; entity resolution to canonical places |
| mcp-engineer | adopt section 8 mapping, add `conditional`/`explanation` fields to the contracts |
| eval-engineer | gold cases per rule; precision/recall of `violated` separately for `conditional` and non-conditional findings |
| qa-lead | unit tests below as `tests/symbolic/` |

## 10. Mini-graph unit tests

Hand-built `FactBase` objects (no DB, no model, no files). Times as `day:HH:MM`. All events exact and `high` unless noted. Places: `B` Baker Street, `H` = "221B" (child of `B`), `D` Docks, `X` an alias shared by `B` and `D` (ambiguous name). Persons: `W`, `H1`.

| Id | Graph | Expected | Why |
|---|---|---|---|
| R1-01 | W at B 1:21:00-22:00; W at D 1:21:30-22:30 | R1 violated, not conditional, overlap 21:30-22:00 | definite overlap, distinct places |
| R1-02 | W at B 1:21:00-22:00; W at D 1:22:00-23:00 | consistent (DEF_DISJOINT: half-open test finds no overlap) | boundary: touching intervals |
| R1-03 | W at B 1:21:00; W at D 1:21:00 (instants) | violated | boundary: equal instants overlap |
| R1-04 | W at B 1:21:00 (instant); W at D 1:21:01 (instant) | consistent | adjacent instants differ |
| R1-05 | W at B 1:21:00-22:00; W at H (child of B) 1:21:30-22:30 | consistent (PlaceRel CONTAINS) | granularity |
| R1-06 | W at B 1:21:00-22:00; W at D, day unknown, 21:30-22:30 | unknown, TIME_UNDECIDED | partial time |
| R1-07 | W at B 1:evening (fuzzy 18:00-22:00, exact=False); W at D 1:20:00-21:00 exact | unknown, possible_overlap | fuzzy cannot be definite |
| R1-08 | W at B 1:morning (06:00-12:00, fuzzy); W at D 1:20:00-21:00 | consistent | outer bounds disjoint proves disjointness |
| R1-09 | W at B 1:21:00-22:00; W at X 1:21:00-22:00 | unknown, PLACE_UNRESOLVED | ambiguous alias |
| R1-10 | W at B 1:21:00-22:00; W at D "the next morning" relative to an event with unknown day | unknown | relative time with unresolved reference |
| R1-11 | as R1-01 but the D event confidence low | violated, conditional=true, weak=[D event] | provenance rule |
| R1-12 | two chunks, one occurrence, marked same_occurrence, at B and D (extraction conflict) | no finding | dedup guard |
| R1-13 | W at B 1:21:00-22:00; H1 at D 1:21:00-22:00 | no finding | different persons |
| R1-14 | W at B 1:21:00-22:00; W with no place at 1:21:30 | not examined, `skipped_no_place` = 1 | missing place is not DISTINCT |
| R1-15 | check_presence(W, place=B, window 1:21:15-21:45); W at D 1:21:00-22:00 | contradicted/violated | alibi query |
| R1-16 | check_presence(W, place=B, window ...); W at B overlapping and W at D overlapping | violated, both listed | contradictory data is not hidden |
| R2-01 | e1<e2 (after), e2<e3 (after) | order(e1,e3)=before, path [e1e2, e2e3] | transitivity |
| R2-02 | e1<e2, e2<e3, e3<e1 | R2 violated, minimal cycle of 3 edges, suspects sorted | cycle |
| R2-03 | e1<e1 (self-reference) | violated | self-loop |
| R2-04 | e1 and e2 both on 1:21:00-22:00, no relative edge | order(e1,e2)=unknown | overlapping spans are not ordered |
| R2-05 | e1 at 1:21:00-22:00, e2 at 1:22:00-23:00 | order=unknown, NO_PATH | boundary: touching (meets); `A.hi < B.lo` is false (22:00 < 22:00), so no edge (see note) |
| R2-06 | e1 at 1:21:00-22:00, e2 at 1:22:01-23:00 | order=before | strict gap |
| R2-07 | e1 at 2:08:00 with relative edge "e2 after e1" and e2 at 1:10:00 | R2 violated (cycle: time says e2 < e1, relation says e1 < e2) | extracted relation contradicts times |
| R2-08 | cycle with one low-confidence edge | violated, conditional, suspect=[low edge] | provenance |
| R2-09 | two disconnected events | unknown, NO_PATH | no closed world |
| R2-10 | narration text order e2 before e1, no time info | order unknown | text position is not time |
| R3-01 | claim "W at B 1:21:00-22:00"; established "W at D 1:21:30" | violated | contradiction |
| R3-02 | claim "W at B 1:21:00-22:00"; established "W at H 1:21:30" | consistent (corroborated) | granularity |
| R3-03 | claim without prop | unknown, UNSTRUCTURED_CLAIM | |
| R3-04 | claim "W at B 1:21:00-22:00"; established event for W at D, day unknown | unknown | partial time |
| R3-05 | claim "e1 before e2"; established closure e2 < e1 | violated | order claim |
| R3-06 | claim "W at B", fact "W at D" from another witness's Claim | unknown, CLAIM_VS_CLAIM | claims are not established |
| R3-07 | claim vs a low-confidence narrator event | violated, conditional, label claim_vs_extracted_event | not established |
| R3-08 | claim corroborated by one established fact, contradicted by another | violated, both anchors listed | inconsistent base |
| ALL-01 | run the same FactBase twice, shuffled input order | identical `Report` JSON, identical `snapshot_digest` | determinism |
| ALL-02 | any `violated` or `consistent` finding | every fact and edge has at least one anchor with non-empty `quote`; `quote == chunk_text[rel_start:rel_end]` | explanation invariant |

Note on R2-05: the time rule yields `BEFORE(a,b)` only if `A.hi < B.lo` strictly, i.e. a gap exists; touching intervals (a ends exactly when b starts) are "meets" and are deliberately treated as not ordered in v1 **[P]** (R2-05 expects `unknown`; if the owner prefers `before` for meeting intervals, flip R2-05 and keep R2-06). R2-05 is listed with the boundary decision explicit so the test fixes it.
