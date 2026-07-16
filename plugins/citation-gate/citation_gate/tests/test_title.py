"""Title verification: when a DOI pins the exact paper, the cited title must
match the authoritative title (modulo acronym suffix / subtitle drop)."""
from unittest.mock import MagicMock

from citation_gate.models import CanonicalRecord, Verdict
from citation_gate.cache import Cache
from citation_gate.normalize import title_mismatch
from citation_gate import verify as V


# ---------------------------------------------------------------------------
# pure title_mismatch
# ---------------------------------------------------------------------------

def test_dropped_middle_method_phrase_is_mismatch():
    # the qr.md [3] corruption: real title drops "with Gaussian Kernel ..."
    cited = "LLM-Based Query Expansion for Dense Retrieval"
    real = ("LLM-Based Query Expansion with Gaussian Kernel Semantic "
            "Enhancement for Dense Retrieval")
    assert title_mismatch(cited, real) is True


def test_subtitle_drop_is_not_mismatch():
    cited = "BERT"
    real = ("BERT: Pre-training of Deep Bidirectional Transformers for "
            "Language Understanding")
    assert title_mismatch(cited, real) is False


def test_acronym_suffix_is_not_mismatch():
    cited = ("Pseudo-Relevance Feedback for Multiple Representation Dense "
             "Retrieval (ColBERT-PRF)")
    real = "Pseudo-Relevance Feedback for Multiple Representation Dense Retrieval"
    assert title_mismatch(cited, real) is False


def test_case_hyphen_paren_variants_are_not_mismatch():
    cited = ("Knowledge-aware query expansion with large language models for "
             "textual and relational retrieval (KAR)")
    real = ("Knowledge-Aware Query Expansion with Large Language Models for "
            "Textual and Relational Retrieval")
    assert title_mismatch(cited, real) is False


def test_trivial_one_word_diff_is_not_mismatch():
    assert title_mismatch("A and B Methods", "A & B Methods") is False


def test_empty_inputs_are_not_mismatch():
    assert title_mismatch("", "Something") is False
    assert title_mismatch("Something", "") is False


# ---------------------------------------------------------------------------
# DOI-path integration: altered title under a correct DOI → HARD_FAIL
# ---------------------------------------------------------------------------

def test_altered_title_under_correct_doi_is_hard_fail(tmp_path, monkeypatch):
    body = ("[3] Pan, M., Xiong, W. **LLM-Based Query Expansion for Dense "
            "Retrieval**. Electronics, 2025. DOI: 10.3390/electronics14091744\n")
    f = tmp_path / "paper.md"
    f.write_text(body, encoding="utf-8")
    real = CanonicalRecord(
        "LLM-Based Query Expansion with Gaussian Kernel Semantic Enhancement "
        "for Dense Retrieval",
        ("Min Pan", "Wenrui Xiong"), 2025, "Electronics", None,
        "10.3390/electronics14091744", "crossref-doi")
    monkeypatch.setattr(V, "search_all", lambda q, s, **kw: ([], True))
    monkeypatch.setattr(V, "resolve_doi", lambda doi, session=None: real)
    report = V.verify_files([str(f)], session=MagicMock(),
                            cache=Cache(cache_dir=tmp_path))
    assert len(report.hard_fails) == 1
    assert "title" in report.hard_fails[0].mismatched_fields


def test_correct_title_under_correct_doi_passes(tmp_path, monkeypatch):
    body = ("[3] Pan, M., Xiong, W. **LLM-Based Query Expansion with Gaussian "
            "Kernel Semantic Enhancement for Dense Retrieval**. Electronics, "
            "2025. DOI: 10.3390/electronics14091744\n")
    f = tmp_path / "paper.md"
    f.write_text(body, encoding="utf-8")
    real = CanonicalRecord(
        "LLM-Based Query Expansion with Gaussian Kernel Semantic Enhancement "
        "for Dense Retrieval",
        ("Min Pan", "Wenrui Xiong"), 2025, "Electronics", None,
        "10.3390/electronics14091744", "crossref-doi")
    monkeypatch.setattr(V, "search_all", lambda q, s, **kw: ([], True))
    monkeypatch.setattr(V, "resolve_doi", lambda doi, session=None: real)
    report = V.verify_files([str(f)], session=MagicMock(),
                            cache=Cache(cache_dir=tmp_path))
    assert len(report.hard_fails) == 0
