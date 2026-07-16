import pytest

from citation_gate import backends, http
from citation_gate.backends import search_all, BackendError, DblpBackend

DBLP_PAYLOAD = {
    "result": {"hits": {"hit": [
        {"info": {
            "title": "Co-training Embeddings of Knowledge Graphs and Entity Descriptions for Cross-lingual Entity Alignment",
            "authors": {"author": [
                {"text": "Muhao Chen"}, {"text": "Yingtao Tian"}, {"text": "Kai-Wei Chang"},
            ]},
            "venue": "IJCAI", "year": "2018", "pages": "3998-4004",
            "doi": "10.24963/ijcai.2018/556",
        }},
    ]}}
}

SINGLE_AUTHOR_PAYLOAD = {"result": {"hits": {"hit": [
    {"info": {"title": "Solo paper here about graphs", "authors": {"author": {"text": "Jane Roe"}},
              "venue": "ICML", "year": "2020"}},
]}}}


def test_dblp_maps_payload_to_record(monkeypatch):
    monkeypatch.setattr(backends.http, "get_json", lambda url, params, timeout=6: DBLP_PAYLOAD)
    recs = DblpBackend().search("co-training embeddings")
    assert recs[0].title.startswith("Co-training Embeddings")
    assert recs[0].authors[0] == "Muhao Chen"
    assert recs[0].year == 2018
    assert recs[0].venue == "IJCAI"
    assert recs[0].source == "dblp"


def test_dblp_single_author_dict_normalized(monkeypatch):
    monkeypatch.setattr(backends.http, "get_json", lambda url, params, timeout=6: SINGLE_AUTHOR_PAYLOAD)
    recs = DblpBackend().search("solo paper")
    assert recs[0].authors == ("Jane Roe",)


def test_search_all_stops_at_first_hit(monkeypatch):
    calls = {"n": 0}

    def fake(url, params, timeout=6, headers=None):
        calls["n"] += 1
        return DBLP_PAYLOAD

    monkeypatch.setattr(backends.http, "get_json", fake)
    recs, ok = search_all("co-training embeddings of knowledge graphs")
    assert ok is True and recs and recs[0].source == "dblp"
    assert calls["n"] == 1  # DBLP hit -> stops, no further sources


def test_search_all_skip_flag_when_all_down(monkeypatch):
    calls = {"n": 0}

    def fake(url, params, timeout=6, headers=None):
        calls["n"] += 1
        raise http.HttpError("down")

    monkeypatch.setattr(backends.http, "get_json", fake)
    recs, ok = search_all("anything")
    assert recs == []
    assert ok is False
    assert calls["n"] == 4


def test_registry_priority_order():
    from citation_gate.backends import BACKEND_REGISTRY
    assert [b.name for b in BACKEND_REGISTRY] == ["dblp", "semanticscholar", "crossref", "openalex"]
