"""Co-author fabrication detection: author-pair parsing, conflict rule,
arXiv-DOI resolution routing, and DOI-path integration."""
from unittest.mock import MagicMock

from citation_gate.models import CanonicalRecord, Verdict, Citation
from citation_gate.cache import Cache
from citation_gate.parse import extract_citations
from citation_gate.normalize import parse_author_pairs, author_conflict
from citation_gate import verify as V
from citation_gate import backends as B


# ---------------------------------------------------------------------------
# parse_author_pairs
# ---------------------------------------------------------------------------

def test_parse_author_pairs_basic():
    assert parse_author_pairs("Li, Z., Wang, H. ") == (("Li", "Z"), ("Wang", "H"))


def test_parse_author_pairs_full_list_with_ampersand():
    seg = "Ma, X., Gong, Y., He, P., Zhao, H., & Duan, N. "
    assert parse_author_pairs(seg) == (
        ("Ma", "X"), ("Gong", "Y"), ("He", "P"), ("Zhao", "H"), ("Duan", "N"))


def test_parse_author_pairs_multiword_surname():
    seg = "Al Nazi, Z., Hristidis, V., Lawson McLean, A. "
    assert parse_author_pairs(seg) == (
        ("Al Nazi", "Z"), ("Hristidis", "V"), ("Lawson McLean", "A"))


# ---------------------------------------------------------------------------
# author_conflict
# ---------------------------------------------------------------------------

REAL_DMQR = ("Zhicong Li", "Jiahao Wang", "Zhishu Jiang", "Hangyu Mao",
             "Zhongxia Chen", "Jiazhen Du")


def test_author_conflict_fires_on_wrong_coauthor_initial():
    # cited 'Wang, H.' but the real co-author is Jiahao Wang (J)
    assert author_conflict((("Li", "Z"), ("Wang", "H")), REAL_DMQR) is True


def test_author_conflict_clean_when_initials_match():
    assert author_conflict((("Li", "Z"), ("Wang", "J")), REAL_DMQR) is False


def test_author_conflict_ignores_truncation():
    # a cited surname simply absent from the record must NOT flag (subset is fine)
    assert author_conflict((("Li", "Z"),), REAL_DMQR) is False


def test_author_conflict_handles_dblp_disambig_suffix():
    # dblp appends '0001' etc.; the surname is still the last *alphabetic* token
    real = ("Rolf Jagerman", "Honglei Zhuang", "Zhen Qin 0001", "Xuanhui Wang")
    assert author_conflict((("Qin", "Z"), ("Wang", "X")), real) is False
    assert author_conflict((("Wang", "Q"),), real) is True


def test_author_conflict_empty_inputs():
    assert author_conflict((), REAL_DMQR) is False
    assert author_conflict((("Wang", "H"),), ()) is False


# ---------------------------------------------------------------------------
# parser wires author_pairs onto the Citation
# ---------------------------------------------------------------------------

def test_prose_entry_populates_author_pairs():
    body = ("[9] Li, Z., Wang, H. **DMQR-RAG: Diverse Multi-Query Rewriting for "
            "RAG**. arXiv, 2024. DOI: 10.48550/arxiv.2411.13154\n")
    cites = extract_citations(body, "md")
    assert cites[0].author_pairs == (("Li", "Z"), ("Wang", "H"))


def test_bibtex_entry_populates_author_pairs():
    body = ("@article{x, title={T}, author={Li, Zhicong and Wang, Hao}, "
            "year={2024}}\n")
    cites = extract_citations(body, "bib")
    assert cites[0].author_pairs == (("Li", "Z"), ("Wang", "H"))


# ---------------------------------------------------------------------------
# arXiv-DOI resolution routing
# ---------------------------------------------------------------------------

def test_resolve_doi_routes_arxiv_to_ss(monkeypatch):
    seen = {}
    rec = CanonicalRecord("T", ("Zhicong Li",), 2024, "arXiv", None,
                          "10.48550/arXiv.2411.13154", "arxiv-ss")

    def fake_arxiv(aid, session=None):
        seen["aid"] = aid
        return rec

    monkeypatch.setattr(B, "_resolve_arxiv", fake_arxiv)
    out = B.resolve_doi("10.48550/arxiv.2411.13154", MagicMock())
    assert out is rec
    assert seen["aid"] == "2411.13154"


def test_resolve_arxiv_returns_none_on_persistent_failure(monkeypatch):
    def boom(url, params, timeout=6):
        raise B.http.HttpError("429 Too Many Requests")
    monkeypatch.setattr(B.http, "get_json", boom)
    monkeypatch.setattr(B.time, "sleep", lambda *_: None)
    assert B._resolve_arxiv("2411.13154") is None


# ---------------------------------------------------------------------------
# DOI-path integration: co-author lie via a resolvable (arXiv) DOI → HARD_FAIL
# ---------------------------------------------------------------------------

def test_coauthor_lie_via_doi_is_hard_fail(tmp_path, monkeypatch):
    body = ("[9] Li, Z., Wang, H. **DMQR-RAG: Diverse Multi-Query Rewriting for "
            "RAG**. arXiv, 2024. DOI: 10.48550/arxiv.2411.13154\n")
    f = tmp_path / "paper.md"
    f.write_text(body, encoding="utf-8")
    real = CanonicalRecord(
        "DMQR-RAG: Diverse Multi-Query Rewriting for RAG", REAL_DMQR, 2024,
        "arXiv", None, "10.48550/arXiv.2411.13154", "arxiv-ss")
    monkeypatch.setattr(V, "search_all", lambda q, s, **kw: ([], True))
    monkeypatch.setattr(V, "resolve_doi", lambda doi, session=None: real)
    report = V.verify_files([str(f)], session=MagicMock(),
                            cache=Cache(cache_dir=tmp_path))
    assert len(report.hard_fails) == 1
    assert "authors" in report.hard_fails[0].mismatched_fields
    assert report.hard_fails[0].citation.index == 9


def test_clean_coauthors_via_doi_pass(tmp_path, monkeypatch):
    body = ("[9] Li, Z., Wang, J. **DMQR-RAG: Diverse Multi-Query Rewriting for "
            "RAG**. arXiv, 2024. DOI: 10.48550/arxiv.2411.13154\n")
    f = tmp_path / "paper.md"
    f.write_text(body, encoding="utf-8")
    real = CanonicalRecord(
        "DMQR-RAG: Diverse Multi-Query Rewriting for RAG", REAL_DMQR, 2024,
        "arXiv", None, "10.48550/arXiv.2411.13154", "arxiv-ss")
    monkeypatch.setattr(V, "search_all", lambda q, s, **kw: ([], True))
    monkeypatch.setattr(V, "resolve_doi", lambda doi, session=None: real)
    report = V.verify_files([str(f)], session=MagicMock(),
                            cache=Cache(cache_dir=tmp_path))
    assert len(report.hard_fails) == 0
