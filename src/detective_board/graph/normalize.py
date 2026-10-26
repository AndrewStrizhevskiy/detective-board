"""Name normalisation for entity resolution (deterministic, no fuzzy matching)."""

from __future__ import annotations

import re
import unicodedata

TITLES = frozenset(
    "mr mrs miss ms mister mistress messrs dr doctor sir lady lord madam madame master "
    "professor prof colonel captain major inspector sergeant constable rev reverend".split()
)
# A person reference starting with one of these has no proper name ("the deceased", "his son").
DETERMINERS = frozenset(
    "the a an his her their our my your its some this that these those another one".split()
)
PRONOUNS = frozenset("i me we us he him she they them you who".split())
_ARTICLES = ("the ", "a ", "an ")


def _base(s: str) -> str:
    s = unicodedata.normalize("NFKC", s).casefold()
    s = s.replace("’", "'").replace("‘", "'").replace("`", "'")
    s = re.sub(r"'s\b", "", s)  # possessive: McCarthy's -> mccarthy
    s = re.sub(r"(?<=s)'(?!\w)", "", s)  # plural possessive: Holmes' -> holmes
    s = re.sub(r"[^\w\s'-]", " ", s)
    return " ".join(s.split())


def is_unnamed_person(name: str) -> bool:
    toks = _base(name).split()
    if not toks:
        return False
    return toks[0] in DETERMINERS or (len(toks) == 1 and toks[0] in PRONOUNS)


def normalize_name(name: str, kind: str = "person") -> str:
    """Key used for matching: casefolded, possessive/punctuation/titles stripped.

    Unnamed persons keep their full descriptor ("the deceased"); places and items drop a leading
    article.
    """
    s = _base(name)
    if kind == "person":
        if is_unnamed_person(name):
            return s
        toks = s.split()
        while len(toks) > 1 and toks[0] in TITLES:
            toks = toks[1:]
        return " ".join(toks)
    for art in _ARTICLES:
        if s.startswith(art) and len(s) > len(art):
            return s[len(art) :]
    return s


def slugify(key: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", key).strip("-") or "x"


def fold_text(text: str) -> str:
    """Casefolded text with possessives, punctuation and typography stripped (for mentions)."""
    return _base(text)
