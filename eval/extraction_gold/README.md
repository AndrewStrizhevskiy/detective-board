# Extraction gold set (Phase 0)

12 chunks from `data/chunks.jsonl`, hand-labelled for the schema in
`src/detective_board/extract/schema.py` (entities, events, claims, relations; each item has a
verbatim `quote` that is a substring of the chunk, checked by `tests/test_score_extraction.py`).

**Provenance: these labels were produced by a Claude agent reading the chunk text, NOT by a
human.** They have not been reviewed. A human spot-check is required before the numbers are
trusted (suggested: all claims and relations of at least 4 chunks). Labels are not exhaustive:
minor entities and implicit relations may be missing, so recall is the more reliable metric
than precision.

Each file: `{chunk_id, story, labeled_by, text, gold}`; `gold` is an `Extraction`.

| chunk | kind |
|---|---|
| boscombe-valley-mystery-0007 | witness testimony (James McCarthy), movements |
| silver-blaze-0004 | testimony with time statements (nine o'clock, maid) |
| reigate-squires-0004 | police account of witnesses, time (quarter to twelve) |
| crooked-man-0014 | embedded testimony, time (quarter to nine) |
| naval-treaty-0007 | first-person account with time statements |
| reigate-squires-0009 | dialogue, alibi-like (who was where, lamps lit) |
| norwood-builder-0014 | dialogue, interview with a witness |
| silver-blaze-0018 | dialogue-heavy, tracks |
| blue-carbuncle-0004 | deduction from an object (hat) |
| red-headed-league-0003 | deduction + advertisement text |
| boscombe-valley-mystery-0006 | deduction about behaviour |
| speckled-band-0020 | descriptive, physical evidence/room |

Conventions: names are the fullest form in the chunk (unnamed people get a descriptive name such as
"the deceased", "the narrator"); other surface forms go in `aliases`; relation predicates are
short free-text verb phrases (not a closed set).
