import json
from unittest.mock import MagicMock

from citation_gate.models import CanonicalRecord, Verdict
from citation_gate.cache import Cache
from citation_gate import verify as V

REAL = CanonicalRecord(
    title="Co-training Embeddings of Knowledge Graphs and Entity Descriptions for Cross-lingual Entity Alignment",
    authors=("Muhao Chen", "Yingtao Tian", "Kai-Wei Chang", "Steven Skiena", "Carlo Zaniolo"),
    year=2018, venue="IJCAI", pages="3998-4004", doi="10.24963/ijcai.2018/556", source="dblp",
)

BAD_DOC = (
    "## References\n"
    "[40] Pei S M, Yu L, Yu G, et al Co-training embeddings of knowledge graphs and "
    "entity descriptions for cross-lingual entity alignment. In: Proc of the 34th AAAI "
    "Conference on Artificial Intelligence. New York, 2020. 3025-3032.\n"
)


def test_golden_fabricated_citation_is_hard_fail(tmp_path, monkeypatch):
    f = tmp_path / "paper.md"
    f.write_text(BAD_DOC, encoding="utf-8")
    # 打桩反查：返回真实论文记录，离线
    monkeypatch.setattr(V, "search_all", lambda q, s, **kw: ([REAL], True))
    report = V.verify_files([str(f)], session=MagicMock(), cache=Cache(cache_dir=tmp_path))

    assert report.exit_code() == 1
    assert len(report.hard_fails) == 1
    res = report.hard_fails[0]
    assert res.verdict is Verdict.HARD_FAIL
    assert set(res.mismatched_fields) >= {"authors", "year"}
    assert "Muhao Chen" in res.message and "IJCAI" in res.message  # 给出正确版本


def test_not_found_is_soft_warn_not_blocking(tmp_path, monkeypatch):
    f = tmp_path / "paper.md"
    f.write_text("[1] Some Obscure Author. A truly unknown private memo. 2099.\n", encoding="utf-8")
    monkeypatch.setattr(V, "search_all", lambda q, s, **kw: ([], True))
    report = V.verify_files([str(f)], session=MagicMock(), cache=Cache(cache_dir=tmp_path))
    assert report.exit_code() == 0
    assert len(report.soft_warns) == 1


def test_all_backends_down_is_skip(tmp_path, monkeypatch):
    f = tmp_path / "paper.md"
    f.write_text(BAD_DOC, encoding="utf-8")
    monkeypatch.setattr(V, "search_all", lambda q, s, **kw: ([], False))
    report = V.verify_files([str(f)], session=MagicMock(), cache=Cache(cache_dir=tmp_path))
    assert report.exit_code() == 0
    assert len(report.skipped) == 1


def test_offline_fast_skip_after_two_downs(tmp_path, monkeypatch):
    f = tmp_path / "p.md"
    f.write_text("[1] A. X. T1. ICML. 2020.\n[2] B. Y. T2. ICML. 2020.\n[3] C. Z. T3. ICML. 2020.\n[4] D. W. T4. ICML. 2020.\n", encoding="utf-8")
    calls = {"n": 0}
    def fake(q, s, **kw):
        calls["n"] += 1
        return ([], False)
    monkeypatch.setattr(V, "search_all", fake)
    report = V.verify_files([str(f)], session=MagicMock(), cache=Cache(cache_dir=tmp_path))
    assert len(report.skipped) == 4
    assert calls["n"] <= 2


def test_to_dict_shape(tmp_path, monkeypatch):
    f = tmp_path / "paper.md"
    f.write_text(BAD_DOC, encoding="utf-8")
    monkeypatch.setattr(V, "search_all", lambda q, s, **kw: ([REAL], True))
    report = V.verify_files([str(f)], session=MagicMock(), cache=Cache(cache_dir=tmp_path))
    d = report.to_dict()
    assert d["hard_fail"] and d["hard_fail"][0]["index"] == 40
    assert "message" in d["hard_fail"][0]
