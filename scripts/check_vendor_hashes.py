#!/usr/bin/env python3
"""Check the vendored web assets against the sha256 sums recorded in web/vendor/README.md.

Usage: python3 scripts/check_vendor_hashes.py [VENDOR_DIR]   (stdlib only; exit 0 ok, 1 mismatch)
Every line of the README that names a file in backticks and carries a 64-hex sha256 is checked
against that file. Every script, stylesheet or font in the folder must have such a line, so a
new or swapped asset cannot slip in unrecorded.
"""

from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

VENDOR = Path(__file__).resolve().parents[1] / "web" / "vendor"
MUST_BE_LISTED = {".mjs", ".js", ".css", ".woff2", ".woff", ".ttf", ".otf"}
_SHA = re.compile(r"\b[0-9a-f]{64}\b")
_PATH = re.compile(r"`([A-Za-z0-9_./-]+\.[A-Za-z0-9]+)`")


def recorded(readme: str, vendor: Path) -> dict[str, str]:
    """{relative path: sha256} for each README line with one sum: the sum belongs to the first
    existing vendored file the line names (a fonts table row also names its licence file)."""
    out: dict[str, str] = {}
    for line in readme.splitlines():
        sums = _SHA.findall(line)
        if len(sums) != 1:
            continue
        names = [n for n in _PATH.findall(line) if (vendor / n).is_file()]
        if names:
            out[names[0]] = sums[0]
    return out


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check(vendor: Path = VENDOR) -> list[str]:
    """Problems found; empty when every asset matches and every script or font is recorded."""
    sums = recorded((vendor / "README.md").read_text(encoding="utf-8"), vendor)
    problems = [
        f"{name}: sha256 {sha256(vendor / name)} != recorded {want}"
        for name, want in sorted(sums.items())
        if sha256(vendor / name) != want
    ]
    for path in sorted(vendor.rglob("*")):
        rel = path.relative_to(vendor).as_posix()
        if path.is_file() and path.suffix in MUST_BE_LISTED and rel not in sums:
            problems.append(f"{rel}: no sha256 recorded in web/vendor/README.md")
    return problems


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    vendor = Path(args[0]) if args else VENDOR
    problems = check(vendor)
    for p in problems:
        print(f"FAIL {p}")
    if not problems:
        n = len(recorded((vendor / "README.md").read_text(encoding="utf-8"), vendor))
        print(f"ok: {n} vendored files match web/vendor/README.md")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
