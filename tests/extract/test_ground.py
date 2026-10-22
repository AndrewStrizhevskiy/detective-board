from detective_board.extract.ground import ground_quote, normalise

from .conftest import CHUNK


def test_exact_and_normalised_rewritten_to_chunk_text():
    c = normalise(CHUNK)
    g = ground_quote("I left the house at nine o'clock", c)
    assert g.grounded == "exact" and g.span == "I left the house at nine o’clock"
    g = ground_quote("The deceased was   found", c)  # whitespace differs
    assert g.grounded == "exact" and g.span == "The\tdeceased was found"
    g = ground_quote('"I never touched the gun,"', c)  # straight vs curly quotes
    assert g.grounded == "exact" and g.span.startswith("“I never")


def test_fuzzy_reanchors_to_chunk_span():
    c = normalise(CHUNK)
    g = ground_quote("I left the house at nine oclock, said James McCarthy", c)
    assert g.grounded == "fuzzy" and g.ratio >= 0.85
    assert g.span in CHUNK and g.span.startswith("I left the house")


def test_fuzzy_small_edit_in_longer_quote():
    c = normalise(CHUNK)
    g = ground_quote("The deceased was founded by the pool at Boscombe", c)
    assert g.grounded == "fuzzy" and g.span == "The\tdeceased was found by the pool at Boscombe"


def test_hallucinated_or_short_quote_is_none():
    c = normalise(CHUNK)
    assert ground_quote("Holmes took out his violin and played", c).grounded == "none"
    assert ground_quote("", c).grounded == "none"
    assert ground_quote("nine o'clok", c).grounded == "none"  # below min fuzzy length
