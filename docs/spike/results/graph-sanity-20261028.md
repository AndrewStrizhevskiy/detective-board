# Full-corpus graph: sanity numbers (2026-10-28)

Source: department GPU server run of 2026-10-27 (RTX 4070, Ollama 0.40.11, qwen3:4b, prompt extract-2.1, schema v2,
temperature 0, seed 42), copied back as `server-out.tar.gz` (sha256 `438f9b9e83415e1ec529ab357f9e6c493cd73bf384746b6f98f61b26b08f733d`).
Raw server report: `server-report-20261027.md`; normaliser log: `server-normalise-20261027.log`. The binary files
(`extract-cache.sqlite`, `graph.sqlite`) are not committed.

## Extraction

- 596 of 596 chunks extracted (status ok, 0 failures), 20 of 20 stories, about 3.2 s per chunk with 4 streams on the GPU
  (laptop: 180-250 s per chunk). The 231 laptop chunks were NOT used as a seed; everything was extracted again on the server.
- Items kept 8663, dropped 125 (duplicate 14, quote not grounded 111).
- Graph: 2157 claims, 1698 events, 743 persons, 631 places, 49 items (5278 nodes before the curated facts, all provenance `extracted`).
- Events with a time text 19.3 %, with a normalised time 52.5 %, with a story day 4.5 % (of 1693 events at normalisation time).
- Claims with a presence proposition: 0.7 % (of 2152).
- Determinism against the laptop: 3 chunks compared, 0 byte-identical (different Ollama version and GPU kernels). By count of
  entities/events/claims/relations: 1 chunk equal, 1 chunk with fewer items on the server (3/2/2/0 vs 4/3/4/4), 1 chunk with more entities (7 vs 5).
  The laptop cache and the server cache are therefore NOT mixed; the demo graph comes from the server run only.

## What the rules find on the automatic graph

`find_contradictions` over all 20 stories (rule layer only, no LLM): 0 findings in 19 stories. The only finding is the
curated Wisteria Lodge R1 (Garcia: Wisteria Lodge vs Oxshott Common, about one o'clock; conditional, curated), loaded with
`python -m detective_board.extract.curated`. The reason is visible in the normaliser log: most event pairs cannot be compared
(`PERSON_MISSING`, `NO_PLACE`, `DENIAL_NOT_MODELLED`), and almost no claim carries a structured presence proposition.
The presence pass (`scripts/server_presence.sh --verify --samples 3`) was NOT run: the server became unreachable from
the network on 2026-10-27 about 18:45 server time (VPN and direct), and the evening was spent on access.

## Real stack on this graph (laptop, 2026-10-28)

Index 596 chunks / 11018 sentences, graph with the curated facts, stdio MCP. Answered with verbatim quotes: the snake
question (swamp adder, 35 s), the Garcia R1 question (curated, conditional, two quotes). Boscombe McCarthy/Crowder: the rule
engine found no violation and says that this does not show consistency (honesty guard), 38 s. Out-of-corpus question
(Baskervilles) refused, 29 s.

Not measured here: precision and recall of the rules on `eval/golden/contradictions.jsonl` (needs the eval runner, issue 6).
