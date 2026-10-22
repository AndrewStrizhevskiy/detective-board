"""Download Gutenberg plain-text collections of Sherlock Holmes into data/raw/ (stdlib only)."""

from __future__ import annotations

import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COLLECTIONS = {
    "adventures": 1661,
    "memoirs": 834,
    "return": 108,
    "last_bow": 2350,
    "casebook": 69700,
}


def main() -> None:
    raw = ROOT / "data" / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    for name, ebook in COLLECTIONS.items():
        url = f"https://www.gutenberg.org/cache/epub/{ebook}/pg{ebook}.txt"
        with urllib.request.urlopen(url, timeout=60) as resp:
            (raw / f"{name}.txt").write_bytes(resp.read())
        print(name, url)


if __name__ == "__main__":
    main()
