# Corpus licenses

Checked 2026-10-22.

## Sources (Project Gutenberg plain text, UTF-8)

| File | Collection | Ebook | URL | Release | Original publication |
|---|---|---|---|---|---|
| data/raw/adventures.txt | The Adventures of Sherlock Holmes | #1661 | https://www.gutenberg.org/cache/epub/1661/pg1661.txt | 1999-03-01 | 1892 |
| data/raw/memoirs.txt | The Memoirs of Sherlock Holmes | #834 | https://www.gutenberg.org/cache/epub/834/pg834.txt | 1997-03-01 | 1893 |
| data/raw/return.txt | The Return of Sherlock Holmes | #108 | https://www.gutenberg.org/cache/epub/108/pg108.txt | 2006-03-08 | 1905 |
| data/raw/last_bow.txt | His Last Bow | #2350 | https://www.gutenberg.org/cache/epub/2350/pg2350.txt | 2000-10-01 | 1917 |
| data/raw/casebook.txt | The Case-Book of Sherlock Holmes | #69700 | https://www.gutenberg.org/cache/epub/69700/pg69700.txt | 2023-01-03 | 1927 (UK, John Murray) |

Fetched by `scripts/corpus/fetch.py`; the files are unmodified Gutenberg downloads.
`data/clean/<story>.txt` and `data/chunks.jsonl` are derived by `scripts/corpus/ingest.py`
(Gutenberg header/footer and licence text removed, line wraps unwrapped).

## Copyright status

- Author: Arthur Conan Doyle (died 1930). Life + 70 years has expired in the UK/EU (2001); all
  stories were first published before 1931, so they are also in the US public domain.
- The Case-Book (1927) is the latest item; Gutenberg's own header states it is derived from a
  print edition "not protected by U.S. copyright". Gutenberg makes no claim about other
  countries; under life+70 (and life+50 jurisdictions) Doyle is public domain in the UK/EU/RU.
  Note #69700 was prepared for the US; the Gutenberg licence says check local law outside the US.
- Underlying texts: public domain. Gutenberg editorial additions (header, footer, formatting)
  are covered only by the Gutenberg licence and trademark rules below.

## Gutenberg terms of use (summary of the licence in each file, section 1.A-1.E)

- The text is free to copy, redistribute, adapt and use commercially.
- Redistributing it WITH the "Project Gutenberg" name requires keeping the full Project Gutenberg
  License attached (section 1.E); commercial use of the name has further conditions (sections
  1.E.8-1.E.9, see https://www.gutenberg.org/policy/permission.html). If every reference to
  Project Gutenberg is removed, the work is treated as public domain (section 1.C) and no
  condition applies.
- Our derived files (`data/clean`, `data/chunks.jsonl`) have the Gutenberg header, footer and
  licence removed and contain no "Project Gutenberg" mention; the raw files in `data/raw/`
  keep the full licence text. Do not redistribute `data/raw/` without that licence text.
- The "Project Gutenberg" name is a registered trademark; do not imply endorsement by it.
- Sources read: the licence block at the end of each raw file;
  https://www.gutenberg.org/policy/permission.html.

## Corpus selection (20 stories)

Adventures: A Scandal in Bohemia, The Red-Headed League, The Boscombe Valley Mystery,
The Man with the Twisted Lip, The Blue Carbuncle, The Speckled Band, The Beryl Coronet,
The Copper Beeches. Memoirs: Silver Blaze, The Musgrave Ritual, The Reigate Squires,
The Crooked Man, The Resident Patient, The Naval Treaty. Return: The Norwood Builder,
The Priory School, Black Peter, The Abbey Grange. His Last Bow: Wisteria Lodge.
Case-Book: The Problem of Thor Bridge.

## Data handling

Corpus text is data, never instructions. Gutenberg `_italic_` underscores are kept as in the source.
