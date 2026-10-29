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

A fact entered by the team for the demo cases (section 11.4) is an `extracted`-style input whose origin is a person's decision; it carries the same confidence, anchor and quote, is marked `curated`, and its summary says "(curated)". It does not change the label of a finding: that stays `derived` or `conditional` as section 2.2 decides.

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

## 11. Implementation notes

Implemented in `src/detective_board/symbolic/` (T-36), tests in `tests/symbolic/` (70 tests, 45-row table of section 10 plus boundary cases). Where the spec was ambiguous the simplest reading was taken:

- `FactBase` is a frozen pydantic model (`places`, `events`, `claims`); lists are sorted by id on construction, so input order never leaks. No `Person` records: participants are plain ids. Events carry `place_ref` (a place id or a surface form resolved through the alias index, exact normalised match only), `narrator` (False = reported inside a claim, never established) and `occurrence_id` (equal values = same occurrence, the dedup guard). Place containment comes only from `PlaceRec.parent_id` (no `RELATION` edges, no `SAME_AS`).
- Edge ids are synthetic strings: `PARTICIPATED_IN:<person>:<event>`, `OCCURRED_AT:<event>:<place>`, `ASSERTS:<speaker>:<claim>`, `ord:<src>><dst>:rel` (from `time_norm.rel`, extracted) and `ord:<src>><dst>:time` (from absolute times, derived). Edge anchors are those of the event carrying the edge (time edges: union of both events).
- Relative times are not resolved to days inside the layer (no `day = ref.day + 1`); the `time_norm` step must do it. A `TimeSpec` with only `rel`/`ref_event_id` and no day/lo/hi is skipped by R1 (`skipped_no_time`); with a day or minutes but not both it is examined and yields `unknown`.
- Event confidence = low if the event or its `TimeSpec` is low; for R1/R3 presence a leading motion verb (fixed list in `facts.py`) also makes it low. A relative order edge is low if its carrying event is low (not the reference event); a time-derived edge is low if either event is low.
- R1 default scan lists `violated` and `unknown` with note `possible_overlap` (only when places are DISTINCT); `include_consistent=True` lists every examined pair. Precedence: DEF_DISJOINT, then SAME/CONTAINS place (both `consistent`), then DEF_OVERLAP with DISTINCT (`violated`) or unresolved place, else `TIME_UNDECIDED`. `check_presence` with `place_id=None` or an unresolved place returns `unknown`; kinds `supported`/`contradicted`/`insufficient_evidence` are the reason codes `ALIBI_SUPPORTED`, `ALIBI_CONTRADICTED`, `NO_DATED_EVENTS`.
- R2: `order_of` returns a `Finding` whose `reason_code` is `BEFORE`, `AFTER`, `CYCLIC`, `NO_PATH` (instead of a separate `order` field). One finding per strongly connected component, with the shortest cycle through its smallest event id; shortest paths use BFS with neighbours in (dst, edge id) order. `Explanation` gained `suspects: list[str] = []` (named in section 4 but absent from the section 8 sketch): extracted edges of the cycle, low confidence first, then edge id. For R2, `depends_on_extracted` holds one `order` fact per extracted edge and the two events of each derived edge; `weak` is computed from those.
- R3: established = narrator-voice event with high presence confidence. Low-confidence narrator events are included by default and make the finding conditional (`CLAIM_VS_EXTRACTED_EVENT`; established: `CLAIM_INCOMPATIBLE_WITH_FACT`; both: the established label). Order claims use the closure over established edges first, then over any narrator-voice edge (conditional). `CLAIM_VS_CLAIM` also fires for non-narrator events and other presence claims that contradict the claim. A claim's own low confidence makes its non-unknown finding conditional.
- `unknown` findings never carry `conditional`/`weak`; they list `missing`. Findings sort by `(rule_id, violated < unknown < consistent, finding_id)`; `finding_id` is the first 12 hex of sha256 over the sorted ids it rests on. `snapshot_digest` hashes the canonical JSON of the whole `FactBase` plus rule versions.
- `load_facts` only delegates to `FactSource.load`; the `GraphStore` adapter is not part of this task.

### 11.1 Wiring to graph data (issue #3, `feat/agent-graph-route`)

- **Normaliser** `extract/normalise.py` (R-07, R-08, R-11; deterministic, no LLM). `normalise_time`
  reuses `graph.timenorm` for clock times and day parts; approximation words (about, nearly,
  shortly, ...) and "since X" make the time `low` ("since X" is stored as the instant X, since
  `TimeSpec` has no open interval; the Wisteria overlap rests on "nearly one" and "since one"
  both mapping to 01:00, which is why that finding is conditional); relative cues (next morning, following day,
  that night, the day before) set `rel` and `ref_event_id`, and a day only when the reference day
  is known. `resolve_days` builds a story calendar: explicit dates are `high`; a weekday is placed
  through a date named in the same expression ("June 3rd, that is, on Monday"), else on its own
  week scale, `low`; a relative cue takes the day of the nearest earlier item with a known day,
  `low` (the reference is chosen by narration order, so it is never `high`). No cue: day unknown.
  `claim_prop` maps the schema-v2 `about_person/about_place/about_time_text/polarity` to a
  `PresenceProp`; a denial, a missing or unparsed slot (`about_person` is never filled from the
  speaker), or a name with zero or several ids gives no proposition, with a reason code
  (`DENIAL_NOT_MODELLED`, `PERSON_MISSING`, `NO_PLACE`, `NO_TIME`, `TIME_UNPARSED`,
  `PERSON_AMBIGUOUS`, ...). Weekdays qualified by next/last/following get no day. No new
  proposition kinds were added here.
- `normalise.apply(store, story)` writes overlays `time` (full `TimeSpec`), `story_day` and `prop`
  with source `normaliser`; overlays with any other source (curation, `set_event_day`) are kept
  and win. `SqliteFactSource` prefers the `time` overlay. CLI for a built graph:
  `python -m detective_board.extract.normalise data/graph/graph.sqlite [--story SLUG]`.
- The graph keeps the v2 fields: claim `about_*`/`polarity` in the claim props, event `transit`;
  `in_speech=True` makes an event non-narrator (before: only claim-span containment).
  `GRAPH_BUILD_VERSION` 2.
- **Agent route.** Contradiction and alibi questions take the `graph` + `mcp` routes. Names are
  linked to person ids by `agent/linking.py` (R-12: exact normalised name or alias, then the
  surname; the story ranked highest by retrieval breaks a cross-story tie; several candidates =
  `ambiguous`, reported in the trace and the prompt, never guessed: `check_alibi` is skipped, a
  contradiction scan runs story-wide). The graph step is seeded on the linked id (R-16b). The rule
  tools are the `mcp/tools.py` functions, called over stdio when a FactBase file is configured,
  else in-process over the live graph (`agent/rules_client.py`, server label
  `timeline-alibi[in-process]`): one implementation either way.
- Regression cases on real passages (`tests/graph/test_real_quotes.py`): Boscombe "following my
  father" vs the game-keeper gives no `violated` finding (gold c042 is a consistent control: the
  denial is about intent and is not a checkable proposition); Wisteria Lodge (gold c001) gives
  R1 `violated`, conditional, once the story day of the two events is curated (the text says "on
  the night of his death", which the day resolver does not read).

### 11.1a Rule-first answers (`agent/rule_first.py`, `agent/honesty.py`)

Observed on the real stack (2026-10-26): for the Garcia question the router sent mcp + graph + vector, `find_contradictions` returned no finding (the graph has no story days, `events_dated=0`), and the 4B model still wrote "There is no conflict ..." and passed the self-check. An empty list is absence of a finding, not of a conflict. For routes whose answer the rule engine determines (`find_contradictions`, `check_alibi`) the answer is therefore a deterministic template over the tool result and its Explanation, with no model call (`AgentConfig.rule_first`, default true):

- **findings**: one sentence per finding (rule id, verdict, reason code, label `derived` or `conditional`), each with its verbatim anchor quotes as `[n: "quote"]`, and for `conditional` the low-confidence inputs from the Explanation.
- **no finding**: `The rule engine found no violation among the facts extracted for <story>. This does not show that the accounts are consistent: <coverage>`. Coverage is computed from the same fact source the rules read: events and claims of the story, events with an exact clock time, events with a story day, claims with a presence proposition, and the pairs R1 examined and could not decide. Up to three retrieved passages follow, labelled `source_text` and marked "not rule results". An `unknown` alibi verdict is reported as unknown, never as agreement.
- **error, skipped step, ambiguous or unknown person**: a sentence that says what was missing (the entity-link note with its candidates is reused).

Update (2026-10-27, `answer_mode`): the template applies only when a rule tool actually ran (an ambiguous person is still reported). A skipped or failed tool, for example "no person found", says nothing about the question, so it goes down the normal text path instead of producing "check_alibi was not run". When the tool ran and returned no decisive result, the empty template is followed in the default `extractive` mode by a `Text evidence:` line (a sentence the model chose from the retrieved text, verbatim) or the plain nothing-about-this sentence, because a rule engine with no finding does not answer a textual question; the passages block of the template is then not used. The honesty guard is unchanged: the rule line never asserts consistency.

The words that assert agreement ("no conflict", "consistent", "no contradiction") do not occur outside quoted source text, the negated sentence above, or a `consistent` verdict a rule really returned. The same check guards the LLM path (`rule_first=false`, or any route that carried a rule result): `answer.self_check(..., forbid_consistency=True)` rejects such a claim with a retry hint when the rule result is empty or failed. The template runs through the same verbatim self-check (sentences without a quote are statements of the engine; every quote present is verified), which passes by construction.

### 11.1b Chronology answers (`build_timeline`, `agent/rule_first.py`)

Questions such as "Give the timeline of the night Aloysius Garcia died", "What happened in Boscombe Valley, in order?" or "In what order did the events of The Speckled Band take place?" are routed (`router._TIMELINE`: timeline, chronolog*, order/sequence of events, in what order, what happened ... in order, day by day, step by step) to `["mcp","graph","vector"]` with the tool `build_timeline`. Alibi and contradiction wording wins when it also matches: "order" alone is not a chronology request, and a question that matches no timeline pattern is routed as before.

The agent calls `build_timeline` with `include_undated=true`, `limit=15`, the story (retrieval, or the entity link) and, when a person is linked, `person_id`; if that person has no events of their own the existing widening to the whole story applies and is said in the answer. The answer is a template with no model call (events as for the other rule-first answers; `enriched_query.strategy` reads `rule-first (timeline): no model call`):

- a head line: events the graph holds for the story (or the person in it), how many have a stated time, how many are shown;
- a numbered list, one line per event: a day (a date from the text, else an internal "day key") and `HH:MM` when the text gives them, else `time not stated`; then the label (`derived`/`conditional` as the tool reports, `curated` for human-checked events), the description and a verbatim `[n: "quote"]` from the event's first citable anchor, so the self-check passes by construction;
- the order note: "Dated events are ordered by the time stated in the text; the others follow in order of narration, which is not necessarily the order in which they happened.";
- notes (scope widened, ambiguous name, curated events, list cut off).

Dated events come first in `(story_day, start_min)` order exactly as the tool returns them, then the undated ones in text order (never interleaved). If the tool returns no event the answer says what is missing; an error or skipped tool falls through to the text path as for the other rules. The wording never says what the correct order is and never asserts consistency or completeness (honesty guard unchanged).

Tool change (additive): `build_timeline` also returns `total_events` (all events matching the filter, before the limit) and a `curated: true` key on human-checked events.

Honest limits. The automatic graph has a story day for only about 4.5 % of its events, so most timelines are mainly narration order and say so; narration order is not event order (flashbacks, reported speech). A story day is an internal key (an explicit date is an ordinal of a placeholder year and is shown as month and day; weekday indices, relative offsets and same-day groups are shown as `day key N`), and keys of different kinds do not share one scale, so the order of dated events across them is only as good as the keys; the answer says so. Only events with both a day and a clock time are ordered by time; an event with only a clock time stays in narration order and is shown with `day not stated`. Events are the extractor's, not a complete list of the story; the limit of 15 shows the start of a long list only. Whether the 12-15 events shown are the important ones is not claimed.

### 11.2 Field grounding of extracted items (`extract/repair.py`, branch `feat/field-grounding`)

Measured on qwen3:4b with prompt extract-2.1 over 64 cached Wisteria/Boscombe chunks (177 events,
226 claims): `participants` empty in all events; `time_text` and `place` filled in all events and
copied from the start of the chunk; `polarity` 'deny' in 222 of 226 claims; `about_person` filled in
222. R1/R3 therefore found nothing on Wisteria Lodge (133 `DENIAL_NOT_MODELLED`, 0 events dated).

`repair_extraction(extraction, chunk_text) -> (extraction, RepairReport)` (and `repair_items` on the
item dicts of a `ChunkResult`) checks each structured field against the item's own quote and fixes
it. It is deterministic and idempotent (a second pass changes nothing), needs no LLM, runs after
parsing and quote grounding in `Extractor.extract_chunk` (`ExtractConfig.repair`, default on) and
again in `extract.ingest.to_graph_input` for results that were not repaired. The raw cache is not
touched and `REPAIR_VERSION` is not part of the cache key, so `just graph` and cache hits give
repaired items. The model's original values stay in audit fields (`schema_v2.REPAIR_FIELDS`, not in
the schema sent to Ollama, stripped from model output): `participants_model`, `in_speech_model`,
`time_text_model`, `place_model`, `polarity_model`, `about_*_model`, plus `repair` (reason codes)
and `repair_version`. Matching is on text folded like `graph/normalize.py` (casefold, possessives,
punctuation, titles stripped), token-bounded.

| Rule | What it does | Reason codes |
|---|---|---|
| R1 participants | Person entities (name, alias, or a surname unique among the chunk's persons) mentioned in the event's quote or description are added; pronouns and determiners never match. Model-provided names stay only if grounded the same way. | `PARTICIPANTS_ADDED`, `PARTICIPANT_UNGROUNDED_DROPPED` |
| R2 polarity | 'deny' iff the claim's own quote has a negation cue (not, n't, never, no one, nobody, nothing, none, neither, nor, cannot, without, deny/denied, refuse/refused); else 'affirm'. A bare 'no' is not a cue ("no idea" is not a denial of a proposition). | `POLARITY_CHANGED` |
| R3 in_speech | True iff the event's quote lies inside one double-quotation span of the chunk (curly and straight marks; a paragraph opening with a mark continues an open quote; a chunk whose first mark is a closing curly mark starts inside a quote; single quotes ignored). A quote not found in the chunk gives false. | `IN_SPEECH_CHANGED`, `IN_SPEECH_QUOTE_NOT_LOCATED` |
| R4 time/place | `time_text` / `place` stay only if the expression appears in the event's quote or description. Otherwise they move to `time_text_inherited` / `place_inherited`. A time with no temporal cue, longer than 9 tokens or equal to the whole quote, and a place that is not a place entity, a locative noun or a capitalised name of the chunk are dropped (audit only). | `TIME_INHERITED`, `PLACE_INHERITED`, `TIME_NOT_TEMPORAL`, `PLACE_NOT_A_PLACE` |
| R5 claim about_* | `about_person/about_place/about_time_text` stay only if they appear in the claim's quote or content; `about_person` also if it is the speaker of a first-person quote (I, me, my, we). Else null. | `ABOUT_PERSON_NOT_IN_QUOTE`, `ABOUT_PLACE_NOT_IN_QUOTE`, `ABOUT_TIME_NOT_IN_QUOTE` |

Inherited values are context, not the event's own fact: the graph keeps `time_text_inherited` and
`place_inherited` in the event props and the event node is `low` (`conf_reason` `inherited_context`);
the `OCCURRED_AT` edge of an inherited place is `low` with `props.inherited`. `SqliteFactSource` and
`normalise.apply` read the inherited text when `time_text` is empty, but the `TimeSpec` is always
`low` and never `exact` (so R1 cannot report a definite overlap from it), and an inherited explicit
date never gives a `high` story day. `GRAPH_BUILD_VERSION` is now 3.

Evaluation: `uv run python scripts/eval/repair_eval.py CACHE.sqlite [...]` (copies the caches, no LLM).

### 11.3 Targeted presence pass (`extract/presence.py`, branch `feat/presence-pass`)

**Status: written and tested with canned model output only. The quality of the extraction is
UNMEASURED until `scripts/server_presence.sh` has run on the GPU server.** Nothing below says that a
model finds these facts; it says what happens to them if it does.

Why. 11.2 showed that the generic extraction (extract-2.1, qwen3:4b) gives R1/R3 no event with a clock
time of its own, no story day, and claims that are rarely a usable "who was where when". The second
pass asks one narrow question per chunk: *a named person was / went / stayed / was seen at a place at a
time*, including what a witness says about it and denials. Output is at most 6 facts, so a 7-8B model
(`qwen3:8b`, `qwen3:4b-instruct`) can run it over all 596 chunks quickly.

Pieces. `extract/presence_schema.py` (`PresenceFact`: person, place, time_text, day_text, polarity,
source, speaker, quote; `PresenceExtraction`; Ollama `format` schema, refs inlined, `maxItems` 6;
schema version `presence-1`), `prompts/extract/presence_v1.txt` (version `presence-1`, worked example on
an invented passage: narrator fact, witness statement, denial), `extract/presence.py` (grounding,
`PresenceExtractor`, runner), `GraphStore.ingest_presence`, `normalise.assign_text_days`,
`scripts/spike/presence_eval.py`, `scripts/server_presence.sh`. The cache key holds the chunk text,
model, prompt version, schema version and generation options (`ExtractCache`, own file
`data/cache/presence-cache.sqlite`); grounding runs after the cache, so it can change without new
model calls. Runner: `python -m detective_board.extract.presence --model M --chunks data/chunks.jsonl
[--story S ...] [--limit N] --cache C --graph-db G [--out F.jsonl] [--lenient] [--no-normalise]`; the
report has the same style as `extract.run` (valid JSON rate, kept/dropped by reason, quote grounding,
seconds per chunk) plus `facts_model`, `facts_kept`, `fact_survival_rate`.

Deterministic grounding (no LLM; reuses `ground.py`, `repair.py` helpers and `graph/normalize.py`):

| Field | Kept only if | Else |
|---|---|---|
| quote | grounded in the chunk (exact or fuzzy, rewritten to the chunk's characters), at most 500 characters | fact dropped (`quote_not_grounded`, `quote_too_long`) |
| person | a proper name (no pronoun, no description) found in the quote: full name, a known alias, or a surname no other known person of the story shares; resolved to the graph's canonical name when the story is in the graph (`known_from_graph`) | dropped (`PERSON_NOT_A_NAME`, `PERSON_NOT_IN_QUOTE`) |
| place | found in the quote; not deictic or possessive ("my door", "there", "his home"); a place the repair helper accepts, or a noun phrase right after a locative preposition ("in the conservatory") | dropped (`PLACE_DEICTIC`, `PLACE_NOT_A_PLACE`, `PLACE_NOT_IN_QUOTE`) |
| time_text | a temporal expression (`repair._is_time_expression`) found in the quote | dropped (`TIME_NOT_TEMPORAL`, `TIME_NOT_IN_QUOTE`) |
| day_text | found in the quote | nulled (`DAY_NOT_IN_QUOTE`) |
| source | decided by the chunk's quotation marks (`repair._ChunkIndex.in_speech`), not by the model | `SOURCE_CHANGED` is recorded |
| polarity | `deny` iff the model says deny AND the quote has a negation cue | dropped (`POLARITY_UNCLEAR`): a cue in an `affirm` quote ("I said that I had not") costs recall on purpose |
| speaker | speech only, a name found in the chunk text | nulled |

Duplicates collapse and the first 6 facts are kept. The model's original values stay in
`GroundedFact.model_values`. `--lenient` keeps person/place/time/day values that are NOT in the quote
and lists them in `context`; such facts are LOW and never exact. It is for comparing against strict, not
a default.

**`presence-2` (default; candidate lists).** Measured 2026-10-26 on the three c001 chunks
(wisteria-lodge-0006/-0009/-0010) with `presence-1`: qwen3:4b-instruct 16 facts, qwen3:8b 12, strict
grounding kept 0 of each (`PERSON_NOT_A_NAME`: the model writes "he" 7 and 8 times; `PERSON_NOT_IN_QUOTE`;
`PLACE_DEICTIC`). A small model cannot do coreference by free generation but can choose from a short
list. So for every chunk the runner builds the persons and places the generic extraction already found
there (`extract/presence_candidates.py`): `--candidates graph` (default: `g_mention` rows of the chunk
joined to named person/place `g_node` rows, mention counts, aliases shown as "(also: ...)", the presence
pass's own mentions left out so a rerun sees the same lists), falling back to `cache` (the chunk's
generic-extraction cache entry, `--generic-cache/--generic-model/--generic-prompt`) and then to `text` (a
deterministic capitalised-name detector). Each list is capped at 30 names (most mentioned first). The
lists go into the prompt (`prompts/extract/presence_v2.txt`, version `presence-2`, worked example with a
pronoun resolved from the list, an UNKNOWN case and a denial) AND into the `format` schema as `enum`
for `person` and `place`, plus the literal `UNKNOWN`. The cache key holds prompt version, schema version
`presence-2` and a hash of both lists, so a changed graph invalidates entries. Grounding: `UNKNOWN` is
dropped (`PERSON_UNKNOWN`, `PLACE_UNKNOWN`), a value outside the list too (`*_NOT_IN_CANDIDATES`); a list
entry not found in the quote is kept as `person_resolution: "context"` / `place_resolution: "context"`
(`context` lists the field), which the graph makes LOW exactly like `--lenient` (`inherited_context`);
`--literal` restores "must literally appear in the quote". time_text and day_text stay literal phrases
from the quote. Because the lists are per chunk, a "he" whose referent is only named in an earlier chunk
(c001's 0010: "He had been there since one o'clock") resolves only if the generic extraction put that
person in the chunk. **Run `presence-2` AFTER the generic extraction and graph build; the candidates
come from the graph.** `enum` in `format`: the Ollama docs (api.md, structured-outputs) do not mention
it; the llama.cpp JSON-schema-to-grammar converter Ollama builds on supports string enums. Quality is
UNMEASURED until a real run.
Carry-over (`--carry N`, default 3, prompt `presence-2.1`): a real run with chunk-local lists dropped
everything (`PERSON_UNKNOWN`, `PLACE_UNKNOWN`) because the dead man of -0010 is only "he". Candidates are now
this chunk's names (never cut), then those of the previous N chunks of the story (chunk index from the id,
nearest first), then the story's top 8 persons and top 5 places by mentions, de-duplicated, at most 30. The
carry setting is part of the candidates hash in the cache key. Names that come only from earlier chunks
are `context` resolved (LOW). The report has `PERSON_UNKNOWN` / `PLACE_UNKNOWN` counts and
`offered_by_chunk` (first 12 names offered per chunk); dropped facts carry the model's raw
person/place/time_text.

**Verification and self-consistency (`extract/presence_verify.py`, branch `feat/presence-verifier`; off by
default; UNMEASURED, tested with fake clients only).** Real runs of `presence-2.1` on the three c001 chunks kept wrong
facts (qwen3:8b 15 facts / 11 kept, several with a wrong person or place, e.g. "About eleven I was glad to go to bed" given
to Garcia; qwen3:4b-instruct 7 / 1, wrong person). Two optional steps work on the grounded facts. Order: sample ->
ground -> vote -> verify. (1) `--verify`: per kept fact one call with the verbatim quote, the previous and next sentence of the
chunk and the claim "PERSON was (NOT) at PLACE at TIME"; the answer is a closed enum schema
`{person_ok, place_ok, time_ok: yes|no, verdict: yes|partly|no}` (field verdicts first, verdict last, so the model decides the parts before the whole).
`yes` keeps the fact; `no`, a wrong person (`person_ok: no`, always), unparseable output or a call error rejects it with
reason `VERIFY_REJECTED` (+ `verify.detail` and the field verdicts in `dropped`); `partly` is rejected unless
`--verify-accept-partly`, which keeps it with the failing place/time moved into `context` (LOW, the time is not written
to the event, the place edge is weak; code `VERIFY_PARTLY`). A person is never nulled. The verification record and prompt
version are in `GroundedFact.verify`; confidence rules are unchanged (a verified `yes` never raises confidence; a
context-resolved person stays LOW). Wording: `prompts/extract/presence_verify_v1.txt` (versioned, invented worked
examples); cache: the extraction cache file, keys `verify:` + hash of the rendered prompt, verifier model, prompt and schema
version, options. Known limit: a fact whose person is only known from outside the three sentences shown (a pronoun resolved
from the candidate list) will be judged `no` by an honest verifier, so `--verify` costs recall on exactly the context-resolved facts. (2) `--samples N`: the presence call runs N
times (seed + k, temperature `--sample-temperature` 0.3, each sample cached); a fact is kept when at least N//2+1 samples
agree (same polarity, normalised person, place and time_text, overlapping quote); `votes`/`samples` are stored on the fact,
the others are dropped as `VOTE_BELOW_MAJORITY`; a failed sample counts as a vote for nothing. The report has `funnel`
(model / grounded / voted / verified) and `presence_eval.py` scores precision and recall per stage. Whether either step
improves precision, and what it costs in recall, has NOT been measured; the GPU run decides the default.

Graph. `GraphStore.ingest_presence(chunk, facts)` is independent of `ingest`: node ids are
`e:<chunk>:p<i>` and `c:<chunk>:p<i>`, and the set is replaced as a whole (unchanged input is a no-op,
hash in `g_meta` key `presence:<chunk>`). A generic re-ingest of the chunk purges the presence nodes too,
so run the presence pass after the generic graph build (`GRAPH_BUILD_VERSION` is unchanged: the generic
logic did not change). An affirmed fact is an event: person PARTICIPATED_IN, place OCCURRED_AT, `narrator`
from the source, `time_norm` from `normalise_time` on its own `time_text` (exact only for an explicit
clock time or noon), `occurrence` = chunk + quote span + person. Facts of one person from one quote
share an occurrence, so R1 skips that pair (`skipped_same_occurrence`): "left Hatherley ... walked down to
the Pool" is one sentence, not two places at 15:00 (the test shows the false R1 violation that appears
without the guard). A motion verb in the quote (`MOTION_VERBS`), a surname-only match to an existing
person, or any `context` field make the node LOW. A fact said in speech by a named speaker also becomes a
claim (ASSERTS speaker, ABOUT person) with the proposition fields (`about_person`, `about_place`,
`about_time_text`, `polarity`); `normalise.apply` turns an affirmed one into a `PresenceProp`. A denial
is a claim only, never an event; R3 still reports it `DENIAL_NOT_MODELLED` (no negative proposition
kind exists). A narrator denial has no asserter and is recorded in `g_dropped` (`denial_without_speaker`).

Story day (HEURISTIC). The text rarely gives a calendar date, so R1/R3 would stay `unknown`.
`normalise.assign_text_days`: presence facts of one story whose `day_text` has the same key
(`day_key`: casefolded, punctuation, leading on/in/during/at/of and "very" removed; "that night" and
"that very night" match, "that night" and "the night" do not) get the same synthetic story day
(`TEXT_DAY_BASE` + n in narration order, far from real dates), always `low`. Order of precedence: a
curated day, then an explicit date or weekday found by `resolve_days` (these keep working and stay
`high` for a date), then this heuristic. Two different nights called "that night" are not told apart,
so every finding resting on this day is conditional. `NORMALISER_VERSION` is 2.

Evaluation without a model: `uv run python scripts/spike/presence_eval.py PRED.jsonl [...]`. The gold is
built from `eval/extraction_gold/*.json` events (a named participant, a place, a time) plus the quotes
of c001, c003, c038, c043 and three hand-read Boscombe items. A gold item is `strict` when person, place
and time all occur in its own quote. Of 20 items only 4 are strict, because the gold events were
labelled with chunk-level places and the contradiction quotes use pronouns ("He had been there since
one o'clock"); the labels are AI-written and unreviewed. The score reports recall by quote overlap and
with all three fields, precision on chunks that have gold (a lower bound: the gold is not exhaustive),
fact survival after grounding, and quote grounding.

What the tests prove (`tests/presence/`, fake client, quotes verbatim from `data/chunks.jsonl`):
runner, cache and resume; every grounding rule; ingest, idempotence and purge; the day heuristic; R1
`violated`, conditional, with both verbatim quotes for Wisteria Lodge (gold c001) through
`find_contradictions`; no finding for the Boscombe McCarthy control (gold c042). What they do not
prove: that any model produces these facts. The c001 test needs `--lenient`: its two sentences ("He
apologised ... nearly one o'clock", "He had been there since one o'clock") name neither the person nor
the place, and the second chunk never mentions Oxshott Common, so strict grounding drops both and the
same input without `--lenient` gives no finding (also tested). With strict grounding c001 needs
discourse context that this pass deliberately does not use.

### 11.4 Curated presence facts for the demo cases (`extract/curated.py`, branch `feat/curated-demo-facts`)

**What "curated" means.** On real runs (2026-10-27) the automatic presence extraction with small models
does not produce the facts the rules need on the demo cases: gold c001 (R1, Garcia "at about one
o'clock on the night he died") needs coreference ("he", "there") that `qwen3:4b-instruct` gets wrong
(it chose Baynes and Wisteria Lodge). For the DEMO cases the team therefore enters a small number of
presence facts by hand, each tied to a verbatim quote, and the system labels them as such everywhere:
the file is `data/curated/presence_demo.jsonl` (tracked in git), the graph nodes carry `curated: true`,
`curated_by` ("team (AI-assisted, to be re-checked by a human)") and a `note` that says why this case
is the way it is, the Explanation facts say `(curated)` in their summary and have `curated: true`, and
the rule-first answer prints a `Curated:` line. "Curated" is NOT a provenance class of its own: a
curated fact is an `extracted`-style input (it has a confidence, an anchor and a quote) whose origin is
a person's decision instead of a model's output; the finding that rests on it is still `derived` or
`conditional` exactly as the rules decide (section 2.2), because curation does not make a fact true. The
AI assisted in writing the file and a human has not yet re-checked it; that is what the label says.

**The automatic pipeline is evaluated separately and honestly.** Nothing here changes
`extract/presence.py`, its grounding, the gold scorer or any reported extraction number. Those numbers
describe what a model finds on its own; the curated facts describe what the rules do when the facts are
right. A result that rests on curated facts is never reported as an extraction result.

**Record format** (`extract/curated_schema.py`, `CuratedFact`, one JSON object per line):
`id`, `story`, `person` and `place` (canonical graph-style names; the same string for the same person),
`time_text` (verbatim from the quote or null), `day_text` (optional, verbatim), `day_key` (shared
story-day key: the same key within a story is one day), `polarity` (`affirm`|`deny`), `source`
(`narrator`|`speech`), `speaker` (speech only), `quote` (verbatim), `curated_by`, `note`, and two optional
fields: `inferred` (the slots among person, place, time that the quote does not state itself) and
`confidence` (`low` forces LOW); and, for a time given RELATIVE to a named event instead of a clock
time, `time_ref` and `time_ref_text` (see "Relative time" below). The loader refuses a fact whose quote is not a verbatim span of
`data/clean/<story>.txt` (checked after whitespace and quotation-mark normalisation), whose
`time_text`/`day_text` are not in the quote, or whose person or place is neither in the quote nor declared
`inferred` (and the reverse); a fact with `inferred` slots needs a note that says how they were resolved.

**Loading** (`python -m detective_board.extract.curated --graph-db data/graph/graph.sqlite [--file
data/curated/presence_demo.jsonl]`; run it after the graph build and `extract.normalise`). Each fact
goes through `GraphStore.ingest_curated`, the same shape as `ingest_presence`: an affirmed fact is an
event (person PARTICIPATED_IN, place OCCURRED_AT, `narrator` from the source, `occurrence` = chunk +
quote span + person); a fact said in speech by a named speaker is also a claim (ASSERTS, ABOUT, with the
proposition fields and a `prop` overlay); a denial is a claim only. Node ids are `e:<chunk>:cur-<id>` and
`c:<chunk>:cur-<id>`, anchored in the real chunk that holds the quote, so the source panel works. The
time is `normalise_time` of `time_text`, written as a `time` overlay with the story day from the
`day_key` (`curated_day`: a stable number in 20000-29999, shared by all facts of a story with that key)
and a `story_day` overlay; overlays with source `curated` win over the normaliser's and survive
`normalise.apply`. Confidence: HIGH for an exact, explicit clock time with nothing inferred; LOW when a
slot is `inferred`, when the fact says `confidence: low`, or when the time is approximate ("nearly one
o'clock", "about three", "since one o'clock" stay LOW exactly as the normaliser decides). The curator's
day key is trusted (day confidence HIGH); that trust is the point of curation and is stated in the note.

**Relative time (`time_ref`).** Some conflicts have no clock time on either side: both witnesses place
the person at "the moment Sir Eustace entered the room" (gold c002; the old schema refused it with
`day_key without time_text`). A curated fact may carry `time_ref` (a kebab-case slug) instead of
`time_text`: the curator asserts that all facts of one story with the same `time_ref` happened at the
same moment. `time_ref_text` is the verbatim words of the quote that name the anchor; if the quote does
not state it, `time_ref_text` is null, `time` must be declared `inferred` and the note must say why.
`time_ref` and `time_text` exclude each other; `day_key` may accompany `time_ref` but has no effect on
it (a moment has no day). Representation, chosen after reading `time.py` and R2: the event's `TimeSpec`
is `rel="at"`, `ref_event_id="moment:<story>:<time_ref>"`, with no day, no `lo`/`hi`, confidence LOW
(the layer's own `rel` and `ref_event_id` fields, no new model field, so the digest of every other fact
base is unchanged). `time.is_moment` recognises it, and: (1) `compare` of two moments with the same
reference is a definite OVERLAP (the explicit same-moment relation; the R1 step reads "same moment:
sir eustace entered (relative time, curated)"); (2) any other comparison involving a moment (another
moment, a clock time) is UNDECIDED, never DISJOINT, so it can neither support nor refute anything;
(3) `abs_bounds` of a moment is None, so `strictly_before` (R2) and every window check ignore it. A
synthetic point in a reserved day range was rejected: it would have to be kept apart from real dates
and curated days by convention only, and R2 would order it against them. Because the fact is always LOW
(the curator's reading that two accounts mean one moment), a finding on it is `conditional`, never
"violated with certainty". Summaries say "at the moment sir eustace entered, relative time" and "(curated)".
Not encoded: c003 (Norwood Builder) and c004 (Reigate), see the note under "What is in the file".

**Survival and idempotence.** Curated nodes and edges carry `"curated":true` in their props and a
generic re-ingest of their chunk (`_purge_chunk`) skips them; curated entity mentions are stored with
`implicit=2`, which that purge also keeps, so the people and places stay findable by name. A presence
re-ingest only purges its own node ids. Re-running the loader is a no-op (hash in `g_meta` key
`curated:<id>`); a changed fact is replaced without leftovers. A fact that cannot be grounded stops the
whole load with every problem listed, before anything is written.

**What is in the file, and what is not.**

| Case | Facts | Result |
|---|---|---|
| c001 Wisteria Lodge, R1 | Eccles (speech): Garcia at Wisteria Lodge, "nearly one o'clock" (place inferred from the narrative: the quote says "my door"). Baynes (speech): Garcia at Oxshott Common, "since one o'clock" (person and place inferred: "He ... there", resolved from Gregson's line before it). Same day key. | R1 `violated`, `OVERLAP_DIFFERENT_PLACES`, conditional (both input events are LOW), both verbatim quotes |
| c002 Abbey Grange, R1 (relative time) | Lady Brackenstall (speech): she, bound to "the oaken chair which stands at the head of the dining-table", "at this instant that my unfortunate husband entered the room". Captain Crocker (speech): he was "standing with her just inside the window ... when he rushed like a madman into the room" (person inferred: "her"). Same `time_ref` `sir-eustace-entered`. | R1 `violated`, `OVERLAP_DIFFERENT_PLACES`, conditional (both inputs LOW), both verbatim quotes; R3 stays `unknown` (`CLAIM_VS_CLAIM`) |
| c042 Boscombe (control) | Holmes (speech): McCarthy senior at Ross "in the morning", and at Hatherley "about three in the afternoon", on June 3rd. James (speech): his father had driven to Ross, "the morning of last Monday, the 3rd" (person, time inferred). | no violation (times are disjoint or the places agree) |
| R3 positives | none | skipped, see below |

R3 positives are NOT in the file. R3 needs a witness's presence claim (person, place, time) against an
established narrator-voice event of the same person at an overlapping time and a different place. The
R3 cases of `eval/golden/contradictions.jsonl` (c008-c026) contradict physical evidence, identity, cause
of death or a legal charge, not a person-place-time statement: the ones that come closest (c011 Randall
gang in New York "this morning" against Kent "last night"; c022 Isa Whitney's day) differ in time, so
the rule would call them disjoint, or in the day only, and travel time is not modelled. Encoding them
would mean inventing a proposition the text does not state. The c042 control is also weaker than its
label: the disputed point (was James *following* his father) is about intent and has no place or clock
time, so what is encoded are the explicit parts and the control shows that those do not clash. The
second sentence of Eccles ("I could swear to it that it was he who addressed me in my bedroom at that
very hour") has only deictic words and is not encoded separately.

c003 and c004 are not in the file. c003 (Norwood Builder): McFarlane's "I spent the night at the Anerley
Arms" has a place and no moment, and the opposing side is an inference (Lestrade reads a thumb-mark as
McFarlane fetching his hat "after the crime"; the housekeeper only says the hat was in the hall): no
quote names McFarlane, the hall and a moment shared with the hotel night. c004 (Reigate): Alec at the
foot of the stairs is a reported account, and Holmes's opposing statement is a deduction about who must
have taken the paper, not a statement that Alec was at the body at a named moment; the gold entry itself
is marked low and borderline. Encoding either would mean inventing the link, so they stay unencoded.

**Adding a case.** (1) Read the passage and decide what the text states; write one line per statement
in `data/curated/presence_demo.jsonl` with a verbatim quote that contains as many slots as possible;
(2) declare every slot the quote does not state in `inferred`, set `confidence: low` if in doubt, and
say in `note` why; (3) give the facts of one day the same `day_key`; (4) run the loader on a copy of the
graph and ask the question; `uv run pytest tests/curated` checks quotes and slots for every line.
A case that cannot be expressed without inventing a statement is skipped and documented here.

### 11.5 Alibi / presence table (`presence_table`, `agent/presence_answer.py`, branch `feat/alibi-table`)

Questions such as "Where was Aloysius Garcia that night according to the testimonies?", "Who says where Lady Brackenstall was?", "Alibi table for James McCarthy" or "Where did Eccles say Garcia was?" ask for every place the text puts one person, not for one time window. `check_alibi` needs a window, so before this section such a question had its rule step skipped and went the text way. The router (`_ALIBI_WHERE`, `_PRESENCE`, `_PRESENCE_WEAK`) now sends it to the tool `presence_table` when ALL of these hold: alibi wording (`alibi`, `where was`, `whereabouts`, `could ... have been at`) or a presence phrase (`alibi table`, `presence table`, `where did ... say`, `who says ... where`; or `according to` / `testimony` / `who says` together with `where was`, `whereabouts` or `alibi`); no clock time (`at one`, `9 p.m.`, `o'clock`, `12:30`, `noon`, `midnight` all keep `check_alibi`, also when the wording is "alibi for nine o'clock"); no contradiction wording and no timeline wording (those win, as before). "At what time ..." questions stay on `check_alibi` (they ask for a time, not a place). The golden sets (64 + 43 questions) change route only for c002 and c004 ("Where was Lady Brackenstall when ..."), whose `check_alibi` step was skipped anyway.

The tool (`mcp/tools.py`, `docs/mcp-contracts.md` 3.5) returns, for one person: a row for each event with a place, a row for each denial claim, and the violated R1 findings of the same person (the call `find_contradictions` makes for R1: `scan_presence_conflicts`). The answer is a template, no model call (`enriched_query.strategy` reads `rule-first (presence): no model call`):

- a head line: how many places the graph holds for the person and how many are shown (at most 12; rows that belong to a conflict are kept first);
- a numbered list, one line per row: `When:` (the time wording of the text, else the stated day and time, else `time not stated`), `Where:` (`not at P` for a denial), `Who says so:` (`the narrator` when the text states it as fact; the named speaker when it reports a statement; `<speaker> denies` for a denial; `speaker not stated` when no claim matches), `Source:` the provenance label (`curated`, or `extracted, high|low confidence`) and a verbatim `[n: "quote"]`. Rows with a stated date come first, the others in order of narration;
- `Verdict (rule R1):` one line `Conflict between row i and row j: R1 verdict violated (<reason>), label derived|conditional` per finding (the finding's own label, the usual "Conditional because ..." / "Derived: ..." lines), or, when there is none, `The rules found no violation among these rows; this does not show that the accounts agree.` The words "no conflict" are avoided on purpose: the honesty guard (`honesty.asserts_consistency`) flags them, and the test checks the whole answer against it;
- notes (events of the person without a place, curated rows, ambiguous name).

How the speaker is found. A reported event (`narrator` false) and the claim written from the same quote have the same anchor and the wording `X at P, T` / `X was at P, T`; the claim's speaker is taken only on that exact match. A denial carries no person id, only the text `X was not at P, T` (ingest, `GraphStore`), so the agent passes the person's name, aliases and the wording of the question as `names` and the tool matches the claim's prefix on them. A person who is not in the graph gets `no person in the graph named ...` and no row; an ambiguous name lists the candidates; a failed or skipped tool goes the text way as for the other rules.

Honest limits. The table lists what the graph holds: the automatic pipeline has few presence facts (curated rows cover the demo cases), so it is often short, and it never says where a person was not unless a denial was extracted. A row's place and time are the extractor's slots, not a reading of the whole story; "the narrator" includes statements that the extraction did not mark as speech. R1 compares only rows with a time on a comparable day, so two rows can both be shown without being compared.

### 11.7 Model-judged candidate pairs (`agent/semantic_r3.py`, branch `feat/r3-semantic`, switch OFF)

Why. R3 needs a structured proposition; 0.7 % of automatic claims have one, so the rule finds nothing
on the automatic graph (dev recall 0/14). This layer is NOT a rule. The graph finds candidate pairs
(no model), a small model judges each pair from the two verbatim quotes only.

- Candidates: claims with a speaker and an anchored quote, plus narrator-voice events, of one story.
  Two statements by different speakers are paired when they share at least 2 content words
  (`agent/window.content_words`); score = sum of ln(1+N/df) over shared words + 1.5 per shared entity
  name; with a linked person at least one side must be by that person or mention the name. Capped at
  `semantic_r3_max_pairs` (12), deterministic order, no LLM.
- Judge: `JUDGE_SYSTEM_PROMPT` (version `JUDGE_VERSION`, one constant), a static prefix identical for
  every pair, then the two quotes with their speakers. Ollama `format` enum {contradicts, consistent,
  unrelated}, temperature 0, seed 42. An unusable answer (invalid, empty, error) counts as no finding.
- Answer: only when the question is a contradiction question and the rules returned the `empty` shape,
  and only with `AgentConfig(semantic_r3=True)` (eval runner: `--set semantic_r3=true`). A separate block
  "Model-judged candidates (hypotheses, not rule findings)" follows the rule line: at most
  `semantic_r3_show` (2) pairs judged `contradicts`, label `hypothesis` / `conditional`, both quotes
  cited, "judged by a small model, not proven". With no such pair the block says that this does not show
  that the accounts are consistent. Switch off: nothing changes. The SSE schema is unchanged.
- Eval: `eval/r3_semantic.py` (dev ids only; test ids are refused), results
  `docs/spike/results/r3-semantic-dev-*.md`. Real runs: `flock /tmp/db-llm.lock uv run python
  eval/r3_semantic.py --mode judge`.

### 11.6 Suspects / alibi-exclusion board for a crime scene (`scene_board`, `agent/scene_answer.py`, `extract/scenes.py`, branch `feat/suspects-board`)

Stage 1 of docs/team/SUSPECTS_DESIGN_RU.md: no new model, no new rule. Questions such as "Who could have been at Oxshott Common at one o'clock?", "Who are the suspects in Wisteria Lodge?", "Who can be excluded by alibi in the Wisteria Lodge case?" or "Who was not at the scene of the Garcia murder?" are answered by running the existing rule tool `check_alibi` (rule R1) for every person of the story that the graph knows, against a SCENE: a place, a time window and a victim. The answer is a board of statuses, each with its quote, and a fixed honesty block. It never names a culprit, never ranks by guilt and never says "guilty", "innocent" or "culprit" about a person.

**Scenes are curated.** The extraction has no "crime scene" concept, so the scene cannot be derived. `data/curated/scenes.jsonl` (tracked in git; loader, schema and validation in `extract/scenes.py`, style of `extract/curated.py`) holds one record per scene: `id`, `story`, `place` (a graph place name, or `place_declared: true`), `day_key` (the curated story-day key of `presence_demo.jsonl`, so the board compares the window with the curated facts of that day: `curated_day(story, day_key)`), `time_text`, `start_min`/`end_min`, `victim`, `victim_aliases`, `titles` (names of the story in a question), ONE verbatim `quote` that states the crime time or place, `curated_by` (always `team (AI-assisted, human re-check pending)`; the answer says "curated by team, AI-assisted, human re-check pending"), `note` and `inferred` (the slots place/victim that the quote does not state itself, with a note that says why). The loader refuses a scene whose quote is not a verbatim span of `data/clean/<story>.txt` (after whitespace and quotation-mark normalisation), whose `time_text` is not in the quote or is not an exact clock time equal to the window, whose place or victim is neither in the quote nor declared `inferred`, or (with `--graph-db`) whose place is neither a graph place nor declared. `python -m detective_board.extract.scenes [--graph-db data/graph/graph.sqlite]` runs the checks; the agent runs them when it starts (`AgentConfig.scenes_path`, set by the API to `data/curated/scenes.jsonl` in real mode when the file exists; `""` or a missing file switch the board off; an invalid file is refused with a warning, never half used). The window is exactly what the quote states (an instant such as "since one o'clock" is 01:00 to 01:00), nothing wider.

**Scenes kept and dropped (2026-10-28, real graph).** Kept: `wisteria-oxshott-one-oclock` (Oxshott Common, 01:00 on the night of the murder, victim Aloysius Garcia, quote "He had been there since one o'clock."). Dropped, not forced: the Boscombe Valley scene (the text gives no time of the crime, only that McCarthy left his house "about three in the afternoon" and walked to the pool; a 15:00 window would be the departure, and the victim's own Hatherley fact at 15:00 would then read as a conflict); the Abbey Grange scene (its only curated facts use a relative moment, which `check_alibi` does not take as a window, and the graph does not say that "the oaken chair" is inside "the dining-room", so Lady Brackenstall would be excluded by a place-graph artefact); and every other story (no story has a person other than the victim with a placed event that has both a story day and a clock time). Board counts on the real graph (persons with a proper name, victim apart): Wisteria 0 excluded / 0 placed / 24 not excluded; Boscombe (not kept) 0 / 0 / 16; Abbey Grange (not kept, dining-room at the half-past ten of the text, as a clock window) 0 / 0 / 13. See "Honest limits".

**Tool** `scene_board` (`mcp/tools.py`, contract in docs/mcp-contracts.md 3.6; also in the MCP server and `InProcessRulesClient`). It composes `check_alibi` per person over one loaded FactBase (the same function body, `_alibi_on`) and maps the three alibi results to board statuses: `contradicted` -> `excluded` (some account places the person elsewhere in the window), `supported` -> `placed`, `unknown` / `insufficient_evidence` -> `not_excluded`. Each decisive entry carries the evidence of `check_alibi` with, per item, `place`, `at_scene`, `narrator`, `speaker_id`, `time_text` and `curated`, the Explanation, and the finding's own label (`derived` / `conditional`). A person with two accounts (one at the scene, one elsewhere) is `excluded` as `check_alibi` decides, with `also_at_scene: true`; the answer shows both. The victim is not part of the board; the tool checks the victim the same way and returns it apart as `victims`. Persons are ranked only for display: decisive first, then those with a placed event first, then by id; the cap is 10 and the counts cover everybody.

**Router** (`_SCENE`, `Router.scenes`). Scene wording (plural "suspects", "who could have been", "who can be excluded / ruled out", "excluded by alibi", "alibi exclusion", "who was (not) at/in/near ...") routes to `["mcp", "vector"]` with the tool `scene_board` only when a scene is known for the story, place or victim the question names (`match_scene`: place, titles, victim, aliases as whole words; a tie between stories is ambiguous, so no route). Contradiction, timeline and presence-table wording win, as before; without a known scene, or without scene wording, the route is the old one. Run over the 64 + 43 golden questions the router changes no route (tested). One question changes on purpose: "Who could have been at Oxshott Common at one o'clock?" matched no pattern before (the alibi pattern wants a name between "could" and "have been") and went to plain retrieval; with the scene it goes to the board.

**Answer** (`agent/scene_answer.py`, no model call, `enriched_query.strategy` reads `rule-first (scene): no model call`): a head line (place, window, the scene quote as `[n: "quote"]`, the curated mark); a counts line ("Of N persons the graph holds for this story, E are excluded by testimony, P are placed at the scene and X are not excluded; K are shown, persons with a placed event first"); one entry per person: `excluded by testimony (label derived|conditional)` with `Elsewhere: <place>, <time>. Who says so: <the narrator|speaker>. Source: curated|extracted, high|low confidence [n: "quote"]` (and `Also, another account places them at the scene: ...`), `placed at the scene (label ...)`, or `not excluded: no placed event at that time (<k placed events, none with a day and clock time to compare | no placed event for this person in the graph>)`; for `conditional` the low-confidence inputs; a note that nobody is excluded or placed when that is the case; the victim line; and the fixed block "Excluded means: some account in the text places this person elsewhere at that time; it is testimony, not proof. Not excluded does not mean suspected. No verdict about guilt is made."; then notes (travel time is not modelled; events without a stated day are not used; curated facts; a different time named in the question; persons not listed). Only graph person nodes with a proper name are on the board ("the woman", "the narrator", "The report" are skipped). The quotes are verbatim and pass the usual self-check; the honesty guard `asserts_consistency` passes on the text (tested).

**Honest limits.** The board is only as good as the placed, timed events of the graph, and the automatic graph has almost none that a rule can use: `check_alibi` compares a window only with events that have a story day AND a clock time, and the rules never assume a day (an assumed day would exclude, for example, Holmes "this afternoon at Ross" from the Boscombe afternoon, days later). Of the 1,700 events of the 20 stories only 18 have a person, a place, a story day and a clock time, and only 3 of those are exact (all three curated: two for Wisteria, one for Boscombe); the window is an exact instant and the rules need an exact time on both sides for a decisive overlap, so the automatic extraction alone excludes or places nobody. On the Wisteria scene nobody but the victim has a usable event, so the board says so and every person is "not excluded", which only means the graph is silent. The one real content is the victim line (Eccles and Baynes place Garcia at two places at 01:00: gold c001). More exclusions need curated presence facts with the same `day_key` (for example Eccles in his bedroom at Wisteria Lodge); with one such scratch fact the board shows "Scott Eccles: excluded by testimony (label conditional)" with his quote (checked on a scratch copy of the graph, not committed). Travel time is not modelled (the rule says so), person nodes are duplicated ("Holmes" and "Sherlock Holmes" are two nodes), and `excluded` is testimony: two accounts can disagree, and the board shows both.
