"""No per-run citation-count cap: coverage is bounded only by the explicit
time budget; anything unchecked must appear in the report as SKIP, never be
silently dropped (the old MAX_CITATIONS_PER_RUN=30 truncation)."""
from unittest.mock import MagicMock

from citation_gate.cache import Cache
from citation_gate import verify as V


def test_verify_files_checks_all_citations(tmp_path, monkeypatch):
    doc = "\n".join(f"[{i}] A. Author. Paper title {i}. ICML. 2020."
                    for i in range(1, 41)) + "\n"
    f = tmp_path / "p.md"
    f.write_text(doc, encoding="utf-8")
    monkeypatch.setattr(V, "search_all", lambda q, s, **kw: ([], True))
    report = V.verify_files([str(f)], session=MagicMock(),
                            cache=Cache(cache_dir=tmp_path), budget_seconds=0)
    assert len(report.results) == 40


def test_count_cap_constant_removed():
    assert not hasattr(V, "MAX_CITATIONS_PER_RUN")
