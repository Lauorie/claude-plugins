"""HTTP 429 (rate limit) handling: status propagation from http → backends,
a per-run circuit breaker that stops hammering a rate-limited backend, and
Semantic Scholar API-key support (CITATION_GATE_S2_API_KEY)."""
import urllib.error
from unittest.mock import MagicMock

import pytest

from citation_gate import backends as B
from citation_gate import http as H
from citation_gate import verify as V
from citation_gate.cache import Cache
from citation_gate.models import CanonicalRecord

REC = CanonicalRecord(
    title="Co-training embeddings of knowledge graphs and entity descriptions",
    authors=("Zhichun Wang",), year=2020, venue="AAAI", pages=None,
    doi=None, source="hits")


def test_get_json_carries_http_status(monkeypatch):
    def _raise(req, timeout=None):
        raise urllib.error.HTTPError("https://x.test/api", 429,
                                     "Too Many Requests", None, None)
    monkeypatch.setattr(H.urllib.request, "urlopen", _raise)
    with pytest.raises(H.HttpError) as ei:
        H.get_json("https://x.test/api", {})
    assert ei.value.status == 429


def test_backend_error_carries_status(monkeypatch):
    def _boom(*a, **kw):
        raise H.HttpError("HTTP 429 Too Many Requests", status=429)
    monkeypatch.setattr(B.http, "get_json", _boom)
    with pytest.raises(B.BackendError) as ei:
        B.DblpBackend().search("q")
    assert ei.value.status == 429


def test_breaker_trips_after_consecutive_429s():
    br = B.BackendBreaker(threshold=3)
    br.record_rate_limited("s2")
    br.record_rate_limited("s2")
    assert not br.tripped("s2")
    br.record_rate_limited("s2")
    assert br.tripped("s2")


def test_breaker_success_resets_consecutive_count():
    br = B.BackendBreaker(threshold=2)
    br.record_rate_limited("s2")
    br.record_ok("s2")
    br.record_rate_limited("s2")
    assert not br.tripped("s2")


class _RateLimited:
    name = "limited"

    def __init__(self):
        self.calls = 0

    def search(self, query, session=None):
        self.calls += 1
        raise B.BackendError("HTTP 429 Too Many Requests", status=429)


class _Hits:
    name = "hits"

    def __init__(self):
        self.calls = 0

    def search(self, query, session=None):
        self.calls += 1
        return [REC]


def test_search_all_disables_tripped_backend(monkeypatch):
    limited, hits = _RateLimited(), _Hits()
    monkeypatch.setattr(B, "BACKEND_REGISTRY", [limited, hits])
    br = B.BackendBreaker(threshold=3)
    for _ in range(5):
        recs, ok = B.search_all("q", polite_delay=0, breaker=br)
        assert ok and recs == [REC]
    assert limited.calls == 3   # 3 consecutive 429s → disabled for the run
    assert hits.calls == 5


def test_verify_files_shares_breaker_across_citations(tmp_path, monkeypatch):
    doc = "\n".join(f"[{i}] A. Author. Paper title {i}. ICML. 2020."
                    for i in range(1, 7)) + "\n"
    f = tmp_path / "p.md"
    f.write_text(doc, encoding="utf-8")
    limited, hits = _RateLimited(), _Hits()
    monkeypatch.setattr(B, "BACKEND_REGISTRY", [limited, hits])
    monkeypatch.setattr(B.time, "sleep", lambda s: None)
    report = V.verify_files([str(f)], session=MagicMock(),
                            cache=Cache(cache_dir=tmp_path), budget_seconds=0)
    assert len(report.results) == 6
    assert limited.calls == 3   # breaker is per-run, not per-citation
    assert hits.calls == 6


def test_semanticscholar_sends_api_key(monkeypatch):
    seen = {}

    def fake_get_json(url, params, timeout=None, headers=None):
        seen["headers"] = headers
        return {"data": []}

    monkeypatch.setattr(B.http, "get_json", fake_get_json)
    monkeypatch.setenv("CITATION_GATE_S2_API_KEY", "k-123")
    B.SemanticScholarBackend().search("q")
    assert (seen["headers"] or {}).get("x-api-key") == "k-123"
