# Extraction prompt A/B: v2.0 vs v2.1 (2026-10-23)

Model qwen3:4b (think off), production pipeline (`python -m detective_board.extract.run`), 4 gold chunks
(boscombe-valley-mystery-0007, silver-blaze-0004, reigate-squires-0004, crooked-man-0014), CPU-only laptop.
v2.1 differs from v2.0 only in the instructions: quotes under 20 words, caps 5 entities / 3 events /
4 claims / 4 relations (was 8/5/5/6), "skip minor background".

| | v2.0 | v2.1 |
|---|---|---|
| seconds per chunk (live, mean) | 252.0 | 189.9 |
| items kept | 82 | 59 |
| items dropped (quote not grounded) | 1 | 0 |
| quotes grounded exact / fuzzy / none | 78 / 4 / 1 | 55 / 4 / 0 |
| valid JSON | 100% | 100% |
| truncated / repaired | 0 / 0 | 0 / 0 |

Reading: v2.1 is about 25% faster and keeps about 28% fewer items, so recall per chunk drops roughly in
proportion; grounding is cleaner. Quality of the kept items was NOT scored (the scorer reads schema v1 and
only the 12 spike gold chunks have labels). v2.1 is the default prompt from commit "handoff".
Wave-1 extraction (v2.1, qwen3:4b) ran from 11:27 on the laptop: 26 of 31 chunks of
boscombe-valley-mystery finished at 180-430 s per chunk (the cache is in data/extraction/).
