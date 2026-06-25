from citation_gate.models import CanonicalRecord
from citation_gate.cache import Cache

REC = CanonicalRecord("T", ("A",), 2018, "IJCAI", "1-2", "10.x/y", "dblp")


def test_put_then_get_roundtrip(tmp_path):
    c = Cache(cache_dir=tmp_path)
    assert c.get("some query") is None
    c.put("some query", [REC])
    got = c.get("some query")
    assert got is not None and got[0].title == "T" and got[0].source == "dblp"


def test_query_normalized_for_key(tmp_path):
    c = Cache(cache_dir=tmp_path)
    c.put("Co-Training Embeddings!", [REC])
    assert c.get("co training embeddings") is not None  # 归一后同键


def test_empty_result_is_cached(tmp_path):
    c = Cache(cache_dir=tmp_path)
    c.put("missing paper", [])
    assert c.get("missing paper") == []  # 区别于 None（未缓存）


def test_corrupt_cache_returns_none(tmp_path):
    c = Cache(cache_dir=tmp_path)
    c._path("bad query").write_text("not json", encoding="utf-8")
    assert c.get("bad query") is None
