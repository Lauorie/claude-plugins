"""An arXiv abs URL is an identifier too: when an entry has no explicit DOI,
derive 10.48550/arxiv.<id> from the URL so the DOI machinery can verify it."""
from unittest.mock import MagicMock

from citation_gate.models import CanonicalRecord
from citation_gate.cache import Cache
from citation_gate.parse import extract_citations
from citation_gate import verify as V


def test_arxiv_url_without_doi_becomes_doi():
    body = ("[2] Liu, M. **More Is Not Always Better: Cross-Component Interference "
            "in LLM Agent Scaffolding**. arXiv, 2025. "
            "https://arxiv.org/abs/2505.05716 （检索结果未提供 DOI）\n")
    cites = extract_citations(body, "md")
    assert cites[0].doi == "10.48550/arxiv.2505.05716"


def test_explicit_doi_takes_precedence_over_url():
    body = ("[1] Kim, Y. **Towards a Science of Scaling Agent Systems**. arXiv, "
            "2025. https://arxiv.org/abs/2512.08296 (DOI: 10.48550/arXiv.2512.08296)\n")
    cites = extract_citations(body, "md")
    assert cites[0].doi.lower() == "10.48550/arxiv.2512.08296"


def test_arxiv_url_pointing_to_different_paper_is_hard_fail(tmp_path, monkeypatch):
    # [2] corruption: cited arXiv id 2505.05716 actually resolves to an unrelated
    # turbulence-models paper; the real CCI paper is 2605.05716.
    body = ("[2] Liu, M. **More Is Not Always Better: Cross-Component Interference "
            "in LLM Agent Scaffolding**. arXiv, 2025. "
            "https://arxiv.org/abs/2505.05716\n")
    f = tmp_path / "paper.md"
    f.write_text(body, encoding="utf-8")
    wrong = CanonicalRecord(
        "A framework for learning symbolic turbulence models from indirect "
        "observation data",
        ("Chutian Wu", "Xin-lei Zhang"), 2025, "arXiv", None,
        "10.48550/arXiv.2505.05716", "arxiv-ss")
    monkeypatch.setattr(V, "search_all", lambda q, s: ([], True))
    monkeypatch.setattr(V, "resolve_doi", lambda doi, session=None: wrong)
    report = V.verify_files([str(f)], session=MagicMock(),
                            cache=Cache(cache_dir=tmp_path))
    assert len(report.hard_fails) == 1
    assert "另一篇" in report.hard_fails[0].message
