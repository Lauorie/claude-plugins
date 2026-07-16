"""DOI verification: format validation + CrossRef resolution + cross-check."""
from citation_gate.models import CanonicalRecord, Verdict
from citation_gate.cache import Cache
from citation_gate import verify as V
from citation_gate import backends as B
from citation_gate import http


# ---------------------------------------------------------------------------
# Pure helpers (STEP 1)
# ---------------------------------------------------------------------------

def test_normalize_doi_strips_prefixes():
    assert B.normalize_doi("https://doi.org/10.1038/X") == "10.1038/x"
    assert B.normalize_doi("doi:10.1038/X") == "10.1038/x"
    assert B.normalize_doi("  10.1038/X  ") == "10.1038/x"


def test_valid_doi():
    assert B.valid_doi("10.1038/s41598-024-82871-0")
    assert B.valid_doi("https://doi.org/10.48550/arxiv.2305.03653")
    assert not B.valid_doi("20.48550/arxiv.2508.11784")  # wrong registrant prefix
    assert not B.valid_doi("not-a-doi")
    assert not B.valid_doi("")


# ---------------------------------------------------------------------------
# DOI-aware grading (STEP 2)
# ---------------------------------------------------------------------------

def _make_doc(tmp_path, body):
    f = tmp_path / "paper.md"
    f.write_text(body, encoding="utf-8")
    return f


def test_invalid_format_doi_is_hard_fail(tmp_path, monkeypatch):
    body = (
        "[5] Al Nazi, Z. **Ontology-Guided Query Expansion for Biomedical Document "
        "Retrieval using Large Language Models**. arXiv, 2025. "
        "DOI: 20.48550/arxiv.2508.11784\n"
    )
    f = _make_doc(tmp_path, body)
    monkeypatch.setattr(V, "search_all", lambda q, s, **kw: ([], True))
    monkeypatch.setattr(V, "resolve_doi", lambda doi, session=None: None)
    report = V.verify_files([str(f)], session=None, cache=Cache(cache_dir=tmp_path))
    assert len(report.hard_fails) == 1
    assert "格式非法" in report.hard_fails[0].message


def test_doi_resolves_to_different_paper_is_hard_fail(tmp_path, monkeypatch):
    body = (
        "[11] Baek, I. **Crafting the Path: Robust Query Rewriting for Information "
        "Retrieval**. AAAI, 2025. DOI: 10.1109/access.2025.3538665\n"
    )
    f = _make_doc(tmp_path, body)
    other = CanonicalRecord(
        title="A completely different paper about wireless sensor networks",
        authors=("Someone Else",), year=2021, venue="IEEE Access",
        pages=None, doi="10.1109/access.2025.3538665", source="crossref-doi",
    )
    monkeypatch.setattr(V, "search_all", lambda q, s, **kw: ([], True))
    monkeypatch.setattr(V, "resolve_doi", lambda doi, session=None: other)
    report = V.verify_files([str(f)], session=None, cache=Cache(cache_dir=tmp_path))
    assert len(report.hard_fails) == 1
    assert "另一篇论文" in report.hard_fails[0].message


def test_doi_resolves_year_differs_is_hard_fail(tmp_path, monkeypatch):
    body = (
        "[14] Garouani, M. **Improving Neural Retrieval with Attribution Guided Query "
        "Rewriting**. arXiv, 2025. DOI: 10.1234/example.2023.0001\n"
    )
    f = _make_doc(tmp_path, body)
    rec = CanonicalRecord(
        title="Improving Neural Retrieval with Attribution Guided Query Rewriting",
        authors=("Moncef Garouani",), year=2023, venue="arXiv",
        pages=None, doi="10.1234/example.2023.0001", source="crossref-doi",
    )
    monkeypatch.setattr(V, "search_all", lambda q, s, **kw: ([], True))
    monkeypatch.setattr(V, "resolve_doi", lambda doi, session=None: rec)
    report = V.verify_files([str(f)], session=None, cache=Cache(cache_dir=tmp_path))
    assert len(report.hard_fails) == 1
    assert "year" in report.hard_fails[0].message


def test_doi_resolves_venue_conflicts_is_hard_fail(tmp_path, monkeypatch):
    body = (
        "[11] Baek, I. **Crafting the Path: Robust Query Rewriting for Information "
        "Retrieval**. AAAI, 2025. DOI: 10.1109/access.2025.3538665\n"
    )
    f = _make_doc(tmp_path, body)
    rec = CanonicalRecord(
        title="Crafting the Path: Robust Query Rewriting for Information Retrieval",
        authors=("Ingeol Baek", "Jimin Lee", "Joonho Yang"), year=2025,
        venue="IEEE Access", pages=None, doi="10.1109/access.2025.3538665",
        source="crossref-doi",
    )
    monkeypatch.setattr(V, "search_all", lambda q, s, **kw: ([], True))
    monkeypatch.setattr(V, "resolve_doi", lambda doi, session=None: rec)
    report = V.verify_files([str(f)], session=None, cache=Cache(cache_dir=tmp_path))
    assert len(report.hard_fails) == 1
    assert "venue" in report.hard_fails[0].message


def test_doi_resolves_everything_matches_is_pass(tmp_path, monkeypatch):
    body = (
        "[3] Pan, M. **LLM Based Query Expansion for Dense Retrieval**. Electronics, "
        "2025. DOI: 10.3390/electronics14091744\n"
    )
    f = _make_doc(tmp_path, body)
    rec = CanonicalRecord(
        title="LLM Based Query Expansion for Dense Retrieval",
        authors=("Mingyang Pan",), year=2025, venue="Electronics",
        pages=None, doi="10.3390/electronics14091744", source="crossref-doi",
    )
    monkeypatch.setattr(V, "search_all", lambda q, s, **kw: ([rec], True))
    monkeypatch.setattr(V, "resolve_doi", lambda doi, session=None: rec)
    report = V.verify_files([str(f)], session=None, cache=Cache(cache_dir=tmp_path))
    assert len(report.hard_fails) == 0
    assert len(report.passed) == 1


def test_unresolvable_doi_with_different_title_doi_is_hard_fail(tmp_path, monkeypatch):
    body = (
        "[13] Pan, M. **A multi dimensional semantic pseudo relevance feedback "
        "framework for information retrieval**. Scientific Reports, 2024. "
        "DOI: 10.1032/s41598-024-82871-0\n"
    )
    f = _make_doc(tmp_path, body)
    real = CanonicalRecord(
        title="A multi dimensional semantic pseudo relevance feedback framework for information retrieval",
        authors=("Min Pan",), year=2024, venue="Scientific Reports",
        pages=None, doi="10.1038/s41598-024-82871-0", source="crossref",
    )
    monkeypatch.setattr(V, "search_all", lambda q, s, **kw: ([real], True))
    monkeypatch.setattr(V, "resolve_doi", lambda doi, session=None: None)
    report = V.verify_files([str(f)], session=None, cache=Cache(cache_dir=tmp_path))
    assert len(report.hard_fails) == 1
    assert "实际应为" in report.hard_fails[0].message
    assert "10.1038/s41598-024-82871-0" in report.hard_fails[0].message


def test_arxiv_doi_unresolvable_not_hard_failed_on_doi_grounds(tmp_path, monkeypatch):
    body = (
        "[1] Jagerman, R. **Query Expansion by Prompting Large Language Models**. "
        "arXiv, 2023. DOI: 10.48550/arxiv.2305.03653\n"
    )
    f = _make_doc(tmp_path, body)
    real = CanonicalRecord(
        title="Query Expansion by Prompting Large Language Models",
        authors=("Rolf Jagerman",), year=2023, venue="arXiv",
        pages=None, doi="10.48550/arXiv.2305.03653", source="semanticscholar",
    )
    monkeypatch.setattr(V, "search_all", lambda q, s, **kw: ([real], True))
    monkeypatch.setattr(V, "resolve_doi", lambda doi, session=None: None)
    report = V.verify_files([str(f)], session=None, cache=Cache(cache_dir=tmp_path))
    assert len(report.hard_fails) == 0


# ---------------------------------------------------------------------------
# resolve_doi backend (STEP 1) — mocked http.get_json, no network
# ---------------------------------------------------------------------------

def test_resolve_doi_maps_message_object(monkeypatch):
    payload = {"message": {
        "title": ["LLM Based Query Expansion for Dense Retrieval"],
        "author": [{"given": "Mingyang", "family": "Pan"}],
        "issued": {"date-parts": [[2025]]},
        "container-title": ["Electronics"],
        "page": "1744",
        "DOI": "10.3390/electronics14091744",
    }}
    monkeypatch.setattr(B.http, "get_json", lambda url, params, timeout=6: payload)
    rec = B.resolve_doi("10.3390/electronics14091744")
    assert rec is not None
    assert rec.title.startswith("LLM Based Query Expansion")
    assert rec.authors[0] == "Mingyang Pan"
    assert rec.year == 2025
    assert rec.venue == "Electronics"
    assert rec.doi == "10.3390/electronics14091744"


def test_resolve_doi_404_returns_none(monkeypatch):
    def boom(url, params, timeout=6):
        raise http.HttpError("HTTP Error 404: Not Found")
    monkeypatch.setattr(B.http, "get_json", boom)
    assert B.resolve_doi("10.9999/missing") is None


def test_resolve_doi_network_error_returns_none(monkeypatch):
    def boom(url, params, timeout=6):
        raise http.HttpError("boom")
    monkeypatch.setattr(B.http, "get_json", boom)
    assert B.resolve_doi("10.9999/missing") is None
