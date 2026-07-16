"""Two subtle fabrications a DOI-pinned check must still catch:
  (a) inserted co-authors whose surname is absent from the real author list;
  (b) a single content word inserted into / changed in the title.
Both must NOT fire on a correct (truncated) citation."""
from unittest.mock import MagicMock

from citation_gate.models import CanonicalRecord
from citation_gate.cache import Cache
from citation_gate.normalize import extra_authors, title_mismatch
from citation_gate import verify as V

REAL_MCE = ("Haoran Ye", "Xuning He", "Vincent Arak", "Haonan Dong", "Guojie Song")


# ---- pure: extra_authors -------------------------------------------------

def test_extra_authors_flags_inserted_fakes():
    cited = (("Ye", "H"), ("He", "X"), ("Spies", "C"), ("Mande", "L"),
             ("Hirzel", "K"), ("Arak", "V"), ("Dong", "H"), ("Song", "G"))
    assert extra_authors(cited, REAL_MCE) is True


def test_extra_authors_clean_when_all_present():
    cited = (("Ye", "H"), ("He", "X"), ("Arak", "V"), ("Dong", "H"), ("Song", "G"))
    assert extra_authors(cited, REAL_MCE) is False


def test_extra_authors_allows_truncation():
    assert extra_authors((("Ye", "H"), ("He", "X")), REAL_MCE) is False


# ---- pure: single-word title insertion -----------------------------------

def test_single_inserted_title_word_is_mismatch():
    cited = ("When Agents Fail to Act: A Diagnostic Framework for Tool Call "
             "Invocation Reliability in Multi-Agent LLM Systems")
    real = ("When Agents Fail to Act: A Diagnostic Framework for Tool "
            "Invocation Reliability in Multi-Agent LLM Systems")
    assert title_mismatch(cited, real) is True


def test_identical_title_not_mismatch():
    t = "When Agents Fail to Act: A Diagnostic Framework for Tool Invocation"
    assert title_mismatch(t, t) is False


# ---- integration via DOI -------------------------------------------------

def _doc(tmp_path, monkeypatch, body, real):
    f = tmp_path / "p.md"
    f.write_text(body, encoding="utf-8")
    monkeypatch.setattr(V, "search_all", lambda q, s, **kw: ([], True))
    monkeypatch.setattr(V, "resolve_doi", lambda doi, session=None: real)
    return V.verify_files([str(f)], session=MagicMock(),
                          cache=Cache(cache_dir=tmp_path))


def test_inserted_authors_under_doi_is_hard_fail(tmp_path, monkeypatch):
    body = ("[8] Ye, H., He, X., Spies, C., Mande, L., Hirzel, K., Arak, V., "
            "Dong, H., Song, G. *Meta Context Engineering via Agentic Skill "
            "Evolution*. arXiv, 2026. https://arxiv.org/abs/2601.21557 "
            "(DOI: 10.48550/arXiv.2601.21557)\n")
    real = CanonicalRecord(
        "Meta Context Engineering via Agentic Skill Evolution", REAL_MCE, 2026,
        "arXiv", None, "10.48550/arXiv.2601.21557", "arxiv-ss")
    report = _doc(tmp_path, monkeypatch, body, real)
    assert len(report.hard_fails) == 1
    assert "authors" in report.hard_fails[0].mismatched_fields


def test_inserted_title_word_under_doi_is_hard_fail(tmp_path, monkeypatch):
    body = ("[14] Huang, D., Malwe, G., Wang, Z. *When Agents Fail to Act: A "
            "Diagnostic Framework for Tool Call Invocation Reliability in "
            "Multi-Agent LLM Systems*. arXiv, 2026. "
            "https://arxiv.org/abs/2601.16280 (DOI: 10.48550/arXiv.2601.16280)\n")
    real = CanonicalRecord(
        "When Agents Fail to Act: A Diagnostic Framework for Tool Invocation "
        "Reliability in Multi-Agent LLM Systems",
        ("Donghao Huang", "Gauri Malwe", "Zhaoxia Wang"), 2026, "arXiv", None,
        "10.48550/arXiv.2601.16280", "arxiv-ss")
    report = _doc(tmp_path, monkeypatch, body, real)
    assert len(report.hard_fails) == 1
    assert "title" in report.hard_fails[0].mismatched_fields


def test_correct_entry_not_flagged(tmp_path, monkeypatch):
    # compud.md [8]: correct 5 authors, correct title → must PASS.
    body = ("[8] Ye, H., He, X., Arak, V., Dong, H., Song, G. *Meta Context "
            "Engineering via Agentic Skill Evolution*. arXiv, 2026. "
            "https://arxiv.org/abs/2601.21557 (DOI: 10.48550/arXiv.2601.21557)\n")
    real = CanonicalRecord(
        "Meta Context Engineering via Agentic Skill Evolution", REAL_MCE, 2026,
        "arXiv", None, "10.48550/arXiv.2601.21557", "arxiv-ss")
    report = _doc(tmp_path, monkeypatch, body, real)
    assert len(report.hard_fails) == 0
