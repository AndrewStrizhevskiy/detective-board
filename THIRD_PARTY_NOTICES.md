# Third-party notices

Detective Board bundles or uses the components below. Each keeps its own licence; this file
lists them and does not replace the licence texts. Checked 2026-10-26. Items marked UNVERIFIED
could not be confirmed from a local or official source.

## Python runtime dependencies

Direct dependencies in `pyproject.toml`: pydantic, sqlite-vec, mcp, starlette, uvicorn. The
table is the runtime closure from `uv.lock` (versions from the lock). Licences were read from
the `METADATA` of the installed packages in `.venv` (License-Expression, License or
Classifier field); nothing was installed to produce it. Dev-only tools (ruff, pyright, pytest,
pytest-cov, playwright) are not shipped and are not listed. The full licence texts are in each
package's `*.dist-info/licenses`.

| Package | Version | Licence |
|---|---|---|
| annotated-types | 0.8.0 | MIT |
| anyio | 4.15.1 | MIT |
| attrs | 26.1.0 | MIT |
| click | 8.5.0 | BSD-3-Clause |
| h11 | 0.16.0 | MIT |
| httpcore2 | 2.16.0 | BSD-3-Clause |
| httpx2 | 2.16.0 | BSD-3-Clause |
| idna | 3.20 | BSD-3-Clause |
| jsonschema | 4.26.0 | MIT |
| jsonschema-specifications | 2025.9.1 | MIT |
| mcp | 2.3.0 | MIT |
| mcp-types | 2.3.0 | MIT |
| opentelemetry-api | 1.45.1 | Apache-2.0 |
| pydantic | 2.14.1 | MIT |
| pydantic-core | 2.50.1 | MIT |
| pyjwt | 2.15.1 | MIT |
| python-multipart | 0.0.32 | Apache-2.0 |
| referencing | 0.37.0 | MIT |
| rpds-py | 2026.9.1 | MIT |
| sqlite-vec | 0.1.9 | MIT and Apache-2.0 (metadata: "MIT License, Apache License, Version 2.0"; dual, no licence file in the dist-info) |
| sse-starlette | 3.5.0 | BSD-3-Clause |
| starlette | 1.9.0 | BSD-3-Clause |
| truststore | 0.10.5 | MIT |
| typing-extensions | 4.16.0 | PSF-2.0 |
| typing-inspection | 0.4.4 | MIT |
| uvicorn | 0.54.0 | BSD-3-Clause |
| httpx2-jsfetch | 1.0 | UNVERIFIED (not installed: only for emscripten, marker in uv.lock) |
| pywin32 | 312 | UNVERIFIED (not installed: only for win32, marker in uv.lock) |

## Vendored web assets (`web/vendor`)

Served locally; nothing is fetched at run time. Hashes are in `web/vendor/README.md`.

| Asset | Licence | Source |
|---|---|---|
| Cytoscape.js 3.34.4 (`cytoscape.esm.min.mjs`), still in the tree but not imported since 2026-10-25 | MIT, Copyright (c) 2016-2026 The Cytoscape Consortium (`web/vendor/cytoscape.LICENSE`) | npm `cytoscape@3.34.4` |
| IM Fell English (regular, italic), latin subset | SIL OFL 1.1, Copyright (c) 2010 Igino Marini (`web/vendor/fonts/IMFellEnglish-OFL.txt`) | Google Fonts |
| EB Garamond (regular, italic), latin subset | SIL OFL 1.1, Copyright 2017 The EB Garamond Project Authors (`web/vendor/fonts/EBGaramond-OFL.txt`) | Google Fonts |
| Special Elite, latin subset | Apache 2.0 (`web/vendor/fonts/SpecialElite-LICENSE.txt`, as recorded in `web/vendor/README.md`) | Google Fonts |

## Models (run locally through Ollama; weights are not part of this repository)

Licences read from the official model pages on 2026-10-26. Tags and digests: `docs/team/models.md`.

| Model | Tag(s) | Licence | Source checked |
|---|---|---|---|
| Qwen3 4B | `qwen3:4b` | Apache-2.0 | huggingface.co/Qwen/Qwen3-4B |
| Qwen3 8B | `qwen3:8b` | Apache-2.0 | huggingface.co/Qwen/Qwen3-8B |
| Qwen3 4B instruct | `qwen3:4b-instruct` | Apache-2.0 per the Ollama library page; the upstream version this tag maps to is UNVERIFIED (the page does not say; Qwen/Qwen3-4B-Instruct-2507 on Hugging Face is also Apache-2.0 but is not confirmed to be the same weights) | ollama.com/library/qwen3:4b-instruct |
| Gemma 3 4B | `gemma3:4b` | Gemma Terms of Use (Google; not an OSI open-source licence; use is subject to its terms and prohibited-use policy). Full text UNVERIFIED here: the page excerpt was truncated | ollama.com/library/gemma3:4b |
| BGE-M3 | `bge-m3:latest` | MIT | huggingface.co/BAAI/bge-m3 |

Ollama tag pages and the Hugging Face cards can differ from the exact weights in a given
Ollama build; the digests in `docs/team/models.md` identify what we used.

## Tools

| Component | Licence | Source checked |
|---|---|---|
| Ollama | MIT, Copyright (c) Ollama | github.com/ollama/ollama LICENSE |

## Offline archive extras (`scripts/pack_offline.sh`)

The offline archive also carries the components below; they are not in this repository.
Checked 2026-10-27 against the GitHub licence API and the installed packages' metadata.

| Component | Licence | Source checked |
|---|---|---|
| uv, uvx (binaries) | MIT OR Apache-2.0 (dual; `LICENSE-MIT`, `LICENSE-APACHE`) | github.com/astral-sh/uv |
| CPython 3.12 (`uv python install`, a python-build-standalone build) | PSF-2.0 for CPython; the build scripts are MPL-2.0. The libraries linked into the build (OpenSSL, SQLite, libffi, zlib, xz, bzip2, Tcl/Tk and others) keep their own licences: UNVERIFIED here, the list ships inside the build | github.com/astral-sh/python-build-standalone |
| Ollama runner libraries (`lib/ollama`, e.g. ggml, CUDA/ROCm runtimes when present) | UNVERIFIED: depends on the Ollama build packed; GPU runtimes carry vendor licences | the Ollama release that is packed |
| uv cache (`uv-cache/`): the runtime packages above, plus the dev tools used only by `verify_offline.sh` (pytest 9.1.1 MIT, pytest-cov 7.1.0 MIT, coverage 7.16.2 Apache-2.0, ruff 0.17.1 MIT, pyright 1.1.414 MIT, iniconfig 2.3.1 MIT, pluggy 1.7.0 MIT, packaging 26.3 Apache-2.0 OR BSD-2-Clause, pygments 2.21.0 BSD-2-Clause, nodeenv 1.11.0 BSD) | as listed; the full dev closure is `uv export --group dev` | installed `METADATA` in `.venv` |
| Build backend for the editable project install, resolved by uv when packing (`pyproject.toml` does not pin it): hatchling (MIT) with editables (MIT), pathspec (MPL-2.0), trove-classifiers (Apache-2.0), tomlkit (MIT), pluggy, packaging | as listed; versions at pack time (hatchling 1.32.4 on 2026-10-27) | PyPI project metadata, 2026-10-27 |
| Model weights `bge-m3`, `qwen3:4b-instruct`, `qwen3:4b` (and `qwen3:8b` with `--with-8b`) | see Models above | `docs/team/models.md` |

## Corpus

Project Gutenberg texts of works by Arthur Conan Doyle (public domain); see `data/LICENSES.md`
and `docs/DISCLOSURE.md`. Not affiliated with or endorsed by Project Gutenberg.

## Not listed

The project's own licence: none file found in the repository (`git ls-files` shows no LICENSE);
UNVERIFIED / TO BE DECIDED by the owners.
