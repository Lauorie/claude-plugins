from citation_gate.normalize import (
    normalize_title, token_set, title_overlap,
    name_words, first_author_mismatch, venue_key, venue_conflicts,
)


def test_normalize_strips_punct_and_case():
    assert normalize_title("Co-Training: Embeddings!") == "co training embeddings"


def test_title_overlap_full_when_canonical_inside_query():
    canonical = "Co-training Embeddings of Knowledge Graphs and Entity Descriptions for Cross-lingual Entity Alignment"
    query = "[40] Pei S M, Yu L. Co-training embeddings of knowledge graphs and entity descriptions for cross-lingual entity alignment. AAAI 2020."
    assert title_overlap(canonical, query) >= 0.9


def test_title_overlap_low_for_unrelated():
    assert title_overlap("Attention Is All You Need", "Deep residual learning for image recognition") < 0.3


def test_name_words_drops_initials():
    assert name_words("Pei S M") == {"pei"}
    assert name_words("Muhao Chen") == {"muhao", "chen"}


def test_first_author_mismatch_true_for_disjoint():
    assert first_author_mismatch("Pei S M", "Muhao Chen") is True


def test_first_author_mismatch_false_for_surname_overlap():
    assert first_author_mismatch("Chen M", "Muhao Chen") is False


def test_venue_key_maps_aliases():
    assert venue_key("In: Proc of the 34th AAAI Conference") == "AAAI"
    assert venue_key("Proceedings of IJCAI") == "IJCAI"
    assert venue_key("some random workshop") is None


def test_venue_conflicts_strict_asymmetric():
    assert venue_conflicts("AAAI", "IEEE Access") is True
    assert venue_conflicts("ACL", "IET Conference Proceedings") is True
    assert venue_conflicts("AAAI", "Proc of the AAAI Conference") is False
    assert venue_conflicts("Electronics", "IEEE Access") is False
    assert venue_conflicts(None, "IEEE Access") is False
    naacl2025 = ("Proceedings of the 2025 Conference of the Nations of the Americas "
                 "Chapter of the Association for Computational Linguistics")
    assert venue_key(naacl2025) == "NAACL"
    assert venue_conflicts("NAACL", naacl2025) is False
