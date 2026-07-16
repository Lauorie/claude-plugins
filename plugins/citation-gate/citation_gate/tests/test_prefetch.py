"""Batched arXiv prefetch seeds the resolve cache so per-entry verification needs
no further network — and still catches a fabricated first author."""
from unittest.mock import MagicMock

from citation_gate.models import CanonicalRecord
from citation_gate.cache import Cache
from citation_gate import verify as V
from citation_gate import backends as B


def test_resolve_arxiv_batch_maps_response(monkeypatch):
    def fake_post(url, params, body, timeout=6, headers=None):
        return [
            {"title": "TapeAgents: a Holistic Framework",
             "authors": [{"name": "Dzmitry Bahdanau"}], "year": 2024,
             "externalIds": {"DOI": "10.48550/arXiv.2412.08445"}},
            None,
        ]
    monkeypatch.setattr(B.http, "post_json", fake_post)
    out = B.resolve_arxiv_batch(["2412.08445", "9999.99999"])
    assert set(out) == {"2412.08445"}
    assert out["2412.08445"].authors == ("Dzmitry Bahdanau",)


def test_prefetch_seeds_cache_and_catches_author_lie(tmp_path, monkeypatch):
    body = ("[10] Ceng, K., Bahdanau, D. *TapeAgents: a Holistic Framework for "
            "Agent Development and Optimization*. arXiv, 2024. "
            "https://arxiv.org/abs/2412.08445\n")
    f = tmp_path / "p.md"
    f.write_text(body, encoding="utf-8")
    real = CanonicalRecord(
        "TapeAgents: a Holistic Framework for Agent Development and Optimization",
        ("Dzmitry Bahdanau", "Nicolas Gontier", "Gabriel Huang"), 2024, "arXiv",
        None, "10.48550/arXiv.2412.08445", "arxiv-ss")
    monkeypatch.setattr(V, "resolve_arxiv_batch",
                        lambda ids, session=None: {"2412.08445": real})
    monkeypatch.setattr(V, "search_all", lambda q, s, **kw: ([], True))
    monkeypatch.setattr(V, "resolve_doi",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("cache")))
    report = V.verify_files([str(f)], session=MagicMock(),
                            cache=Cache(cache_dir=tmp_path))
    assert len(report.hard_fails) == 1
    assert "authors" in report.hard_fails[0].mismatched_fields
