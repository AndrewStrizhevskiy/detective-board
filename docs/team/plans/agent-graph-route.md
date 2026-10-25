# Plan: `feat/agent-graph-route` (issue #3; backlog R-07, R-08, R-11, R-12, R-14, R-16b)

Goal: a contradiction/alibi question goes agent -> graph -> FactBase (`SqliteFactSource`) -> rules,
with the rule `Explanation` on the trace and `derived`/`conditional` labels in the answer.
No LLM, no Ollama, no full-corpus data needed; everything is tested on hand-built graphs and `--fake`.

## Changes

1. **Normaliser** (new `extract/normalise.py`, pure, deterministic, no LLM; R-07, R-08, R-11)
   - `normalise_time(text, ref=None) -> TimeSpec`: reuses `graph.timenorm.derive_time_norm` for
     clock times and day parts; adds approximation words (about, nearly, shortly) -> `low`,
     "since X" as a start bound, relative day cues (next morning, following day, that night, the
     day before) -> `rel` + `ref_event_id`, `day = ref.day + k` only when the reference day is known.
   - `resolve_days(events)`: story calendar from explicit dates ("June 3rd", high) and weekdays
     ("Monday", low); a relative cue is resolved against the nearest preceding event with a known
     day (the reference is chosen by narration order, so the result is always `low`). No cue: the
     day stays unknown, never assumed.
   - `claim_prop(claim, resolve) -> (Prop | None, confidence, reason)`: schema-v2 `about_person`,
     `about_place`, `about_time_text`, `polarity` -> `PresenceProp`. `deny`, missing place/time,
     unresolved or ambiguous names -> `None` plus a reason (R3 then says `UNSTRUCTURED_CLAIM`).
     No new proposition kinds: `symbolic/` is not touched.
   - `apply(store, story)`: writes through `set_event_day` / `set_claim_prop` and a new overlay key
     `time` (full `TimeSpec`) that `SqliteFactSource` prefers. `g_overlay` is key/value, so no
     migration.
2. **Graph** (R-11): `GraphStore.ingest` keeps the v2 fields when it gets a v2 `Extraction` (claim
   `about_*`/`polarity`, event `in_speech`/`transit`); `in_speech` -> not narrator.
   `extract/ingest.py` stops projecting to v1. `GRAPH_BUILD_VERSION` bump (input hashes change).
3. **Entity linking** (R-12, new `agent/linking.py`): names in the question -> node ids through
   `GraphStore.resolve` (exact normalised name or alias, titles stripped, no fuzzy match); story
   from the candidates, cross-checked with the retrieval hits. Result: `ok | ambiguous | not_found`
   with candidates. Ambiguity is shown in the trace and the answer, never guessed. Replaces
   "story of hit 1 + first person node".
4. **Router / agent**: contradiction and alibi questions get the `graph` + `mcp` routes with a
   `reason` that names the rule step; the graph step seeds on the linked person (R-16b), so the
   board gets `graph_results` from the backend. New `agent/rules_client.py`:
   `InProcessRulesClient(store)` calls the same `mcp.tools` functions over `SqliteFactSource`
   (one source of truth, no stdio). It is used in the `--fake` demo flavour and when no MCP facts
   file is configured; the stdio MCP server stays as it is when `facts_path` is set.
   **No event schema change**: `tool_result.explanation` and `final.provenance[].explanation`
   already carry the object.
5. **Fake fixture** (demo flavour only; the lean flavour and its tests stay as they are): the canned
   R3 finding is replaced by real rules over the fixture graph; Wisteria Lodge (gold c001) is
   added: Eccles says Garcia spoke to him at Wisteria Lodge at nearly one o'clock, the police say
   Garcia lay dead on Oxshott Common since one o'clock (verbatim quotes, real offsets) ->
   R1 `violated`, `conditional` (approximate times, curated day).

## Tests (written first)

Normaliser: bare hour, about/nearly, since, half past, next morning with known and unknown
reference, weekday vs date, deny, missing place, ambiguous name. Linking: exact name, alias, title,
two McCarthys -> ambiguous, unknown name, wrong story. Agent: route + trace order with
`InProcessRulesClient` on a hand-built graph; `Explanation` reaches `tool_result` and `final`.
Regressions with real quotes and offsets from `data/clean`: Boscombe "following my father" vs the
game-keeper -> no `violated` finding (gold c042 is a consistent control); Wisteria c001 -> R1
`violated`, conditional. Determinism: two runs give byte-identical JSON. All existing tests green.

## Decisions for the maintainer

- **Demo step 2 (James McCarthy vs the game-keeper).** With real rules the answer becomes "no rule
  violation; the two accounts differ on intent". That matches gold c042 and the fallback already in
  `docs/design/demo-script.md`, but it differs from today's canned R3 finding. OK to change?
- A curated day overlay (low confidence) for the Wisteria fixture events: this is curation, not
  inference, and is labelled as such.
- Day resolution is a heuristic: a reference chosen by narration order is always `low`, so the
  findings that rest on it are `conditional`.
- No public interface or event schema change is planned. `GraphBackend` gains `resolve` (already
  on `GraphStore`). `api/` changes are wiring only (`services.py`, the fake fixture).
