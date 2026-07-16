"""An arXiv DOI registrant prefix is always 10.48550; 10.48555 / 10.48551 etc.
are malformed and can be flagged offline (no network)."""
from unittest.mock import MagicMock

from citation_gate.cache import Cache
from citation_gate import verify as V


def _run(tmp_path, monkeypatch, body):
    f = tmp_path / "p.md"
    f.write_text(body, encoding="utf-8")
    # No network should be needed; make both fail loudly if called.
    monkeypatch.setattr(V, "search_all", lambda q, s, **kw: ([], True))
    monkeypatch.setattr(V, "resolve_doi",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("net")))
    return V.verify_files([str(f)], session=MagicMock(),
                          cache=Cache(cache_dir=tmp_path))


def test_wrong_arxiv_prefix_48555_is_hard_fail(tmp_path, monkeypatch):
    body = ("[6] Zhou, H. *Multi-Agent Design: Optimizing Agents with Better "
            "Prompts*. arXiv, 2025. (DOI: 10.48555/arXiv.2502.02533)\n")
    report = _run(tmp_path, monkeypatch, body)
    assert len(report.hard_fails) == 1
    assert "10.48550" in report.hard_fails[0].message


def test_wrong_arxiv_prefix_48551_is_hard_fail(tmp_path, monkeypatch):
    body = ("[18] Du, P. *Memory for Autonomous LLM Agents*. arXiv, 2026. "
            "(DOI: 10.48551/arXiv.2603.07670)\n")
    report = _run(tmp_path, monkeypatch, body)
    assert len(report.hard_fails) == 1
    assert "10.48550" in report.hard_fails[0].message


def test_correct_arxiv_prefix_not_flagged_by_prefix_rule(tmp_path, monkeypatch):
    # correct prefix → the offline prefix rule must NOT fire (resolve is stubbed
    # to None so the entry ends up SOFT/PASS, never a prefix HARD_FAIL)
    body = ("[1] Kim, Y. *Towards a Science of Scaling Agent Systems*. arXiv, "
            "2025. (DOI: 10.48550/arXiv.2512.08296)\n")
    f = tmp_path / "p.md"
    f.write_text(body, encoding="utf-8")
    monkeypatch.setattr(V, "search_all", lambda q, s, **kw: ([], True))
    monkeypatch.setattr(V, "resolve_doi", lambda doi, session=None: None)
    report = V.verify_files([str(f)], session=MagicMock(),
                            cache=Cache(cache_dir=tmp_path))
    assert len(report.hard_fails) == 0
