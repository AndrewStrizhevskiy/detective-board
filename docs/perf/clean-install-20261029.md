# Offline archive rc4: build and check (2026-10-29, one machine)

Built: `scripts/pack_offline.sh --tag rc4 --out ~/dist` on the demo laptop (ThinkPad X1 Carbon 7th gen, Linux x86_64). Result
`detective-board-offline-rc4.tar`, 6.2 GB, sha256 `16854b3d5fe2a8e80ba925bfdda8fcb0fb7a43bb379ae699bf92da694e5e2ca3` (checked with `sha256sum -c`).
Contents: the repo at tag rc4 (commit 76f45ad), index, sentence index and graph, uv, Python 3.12.15, uv cache, Ollama 0.35.0, models bge-m3, qwen3:4b-instruct, qwen3:4b.

Checked: the tar was unpacked into a NEW empty folder and `./verify_offline.sh --require-offline` was run inside `unshare -rn` (a network namespace with
no connection to the internet) in 341 s:

| step | result |
|---|---|
| checksums | PASS: 11291 files match SHA256SUMS |
| network | PASS: no internet |
| uv sync offline | PASS with Python 3.12.15 |
| tests | PASS: 976 passed, 2 skipped, 41.5 s |
| Ollama from the archive | PASS: 3 models match MANIFEST |
| preflight | PASS |
| API questions | g001 answered in 148.3 s, c001 R1 violated in 4.6 s, g047 refused in 1.5 s, g056 refused in 95.8 s |

Caveats, read before quoting:
- This is ONE machine (the author's laptop) and the model files were already on its disk; the 'clean machine' test of issue 8 asks for two DIFFERENT laptops, one not the author's, from the archive on a USB stick. Not done.
- The slow answers (148 s, 96 s) are NOT a speed measurement: another experiment was running on the same CPU and the first question includes a cold model load. Normal answers take 30-43 s (docs/perf/laptop-20261028.md).
- The 'under 15 minutes' claim of CLEAN_INSTALL.md is not measured for a real install.
- The archive is built from tag rc4; code after rc4 is not in it.
