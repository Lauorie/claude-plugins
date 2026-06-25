"""Prose titles may be *italic* (single asterisk), not just **bold**. The parser
must extract either, and the DOI title-check must never run on the raw entry."""
from unittest.mock import MagicMock

from citation_gate.models import CanonicalRecord
from citation_gate.cache import Cache
from citation_gate.parse import extract_citations
from citation_gate import verify as V


def test_italic_title_is_extracted():
    body = ("[7] Rosser, J., Foerster, J. *AgentBreeder: Mitigating the AI Safety "
            "Risks of Multi-Agent Scaffolds via Self-Improvement*. ArXiv.org, "
            "2026. https://arxiv.org/abs/2502.00757\n")
    c = extract_citations(body, "md")[0]
    assert c.title == ("AgentBreeder: Mitigating the AI Safety Risks of "
                       "Multi-Agent Scaffolds via Self-Improvement")
    assert c.author_pairs == (("Rosser", "J"), ("Foerster", "J"))


def test_bold_title_still_extracted():
    body = "[1] Li, Z. **A Real Title Here**. arXiv, 2024.\n"
    c = extract_citations(body, "md")[0]
    assert c.title == "A Real Title Here"


def test_clean_italic_title_under_doi_does_not_false_fail(tmp_path, monkeypatch):
    # [7]-shaped: title matches the authoritative record → must NOT hard-fail.
    body = ("[7] Rosser, J., Foerster, J. *AgentBreeder: Mitigating the AI Safety "
            "Risks of Multi-Agent Scaffolds via Self-Improvement*. arXiv, 2026. "
            "https://arxiv.org/abs/2502.00757 (DOI: 10.48550/arXiv.2502.00757)\n")
    f = tmp_path / "p.md"
    f.write_text(body, encoding="utf-8")
    real = CanonicalRecord(
        "AgentBreeder: Mitigating the AI Safety Risks of Multi-Agent Scaffolds "
        "via Self-Improvement",
        ("J. Rosser", "Jakob N. Foerster"), 2025, "arXiv", None,
        "10.48550/arXiv.2502.00757", "arxiv-ss")
    monkeypatch.setattr(V, "search_all", lambda q, s: ([], True))
    monkeypatch.setattr(V, "resolve_doi", lambda doi, session=None: real)
    report = V.verify_files([str(f)], session=MagicMock(),
                            cache=Cache(cache_dir=tmp_path))
    assert len(report.hard_fails) == 0


def test_altered_italic_title_under_doi_is_hard_fail(tmp_path, monkeypatch):
    # [20]-shaped: cited 'AgenticCompass' but the real paper is 'AgentCompass'.
    body = ("[20] Kartik, N. *AgenticCompass: Towards Reliable Evaluation of "
            "Agentic Workflows in Production*. arXiv, 2025. "
            "https://arxiv.org/abs/2509.14647 (DOI: 10.48550/arXiv.2509.14647)\n")
    f = tmp_path / "p.md"
    f.write_text(body, encoding="utf-8")
    real = CanonicalRecord(
        "AgentCompass: Towards Reliable Evaluation of Agentic Workflows in "
        "Production",
        ("Nvjk Kartik",), 2025, "arXiv", None,
        "10.48550/arXiv.2509.14647", "arxiv-ss")
    monkeypatch.setattr(V, "search_all", lambda q, s: ([], True))
    monkeypatch.setattr(V, "resolve_doi", lambda doi, session=None: real)
    report = V.verify_files([str(f)], session=MagicMock(),
                            cache=Cache(cache_dir=tmp_path))
    assert len(report.hard_fails) == 1
    assert "title" in report.hard_fails[0].mismatched_fields
