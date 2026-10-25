# Vendored libraries

## Cytoscape.js 3.34.4 (MIT)

- File: `cytoscape.esm.min.mjs` (copied unchanged from `dist/` of the npm package `cytoscape@3.34.4`), license: `cytoscape.LICENSE` (package `LICENSE`, MIT, Copyright (c) 2016-2026 The Cytoscape Consortium).
- Source: https://registry.npmjs.org/cytoscape/-/cytoscape-3.34.4.tgz
- tarball sha1 (matches the registry `shasum`): `20cbd1b1f8cb2e25699bdf68887564fc3c74b375`
- tarball sha256: `0d02363d99d805ce8d91fdecab7b2a8cb91ee280d67f309ce44c161d117b4679`
- `cytoscape.esm.min.mjs` sha256: `0d7e373a706f0f01d6fb7a6ccf04988c01307cee1c2f9bcc7b068e9f6b431e3f`
- `cytoscape.LICENSE` sha256: `eb319c6e6f233607f71e8e2f450391751883cfc0eeb3ca7ef574c13d1d9c2203`
- Downloaded 2026-10-22. Upgrade: replace the file, update this list.
- Not imported since 2026-10-25: the board is drawn with DOM + SVG (`js/graph.js`), see the request in `docs/backlog.md` (ADR-0005 amendment). The file stays until that decision.

## Fonts (latin subset, woff2, from Google Fonts on 2026-10-25)

Served by the app (`css/fonts.css`); nothing is fetched at run time.

| File | Family | License | sha256 |
|---|---|---|---|
| `fonts/im-fell-english-latin.woff2` | IM Fell English, regular | SIL OFL 1.1, `fonts/IMFellEnglish-OFL.txt` | `248300df1647bec49155a5cada1d65f719ae633ef48564d1f19b135a8a5b7f5f` |
| `fonts/im-fell-english-italic-latin.woff2` | IM Fell English, italic | SIL OFL 1.1 | `8fc678575e83868f82ce5aa6e023f056ea68d480e16dd108b3e14bc375c8fdea` |
| `fonts/eb-garamond-latin.woff2` | EB Garamond, variable 400-800 | SIL OFL 1.1, `fonts/EBGaramond-OFL.txt` | `68fd4b247dde89984ee835d99953d235e4927be2b1b732ad81173b519869cee8` |
| `fonts/eb-garamond-italic-latin.woff2` | EB Garamond, italic | SIL OFL 1.1 | `078bb1c082255b93ded45a05e4009221edb4727f64a77d4f19c9d4715d02e297` |
| `fonts/special-elite-latin.woff2` | Special Elite | Apache 2.0, `fonts/SpecialElite-LICENSE.txt` | `3cf06771841c778db94dfc003a9239338613c07a9e8c8125d0641a1ba6e7977a` |

License texts: `github.com/google/fonts` (`ofl/imfellenglish/OFL.txt`, `ofl/ebgaramond/OFL.txt`, `apache/specialelite/LICENSE.txt`).

`../css/tokens.css` is a copy of `docs/design/tokens.css`; re-copy after token changes.
