"""Shared test fixtures."""
import pytest

from citation_gate import verify as V


@pytest.fixture(autouse=True)
def _stub_arxiv_batch(monkeypatch):
    """Keep tests hermetic/fast: the batched arXiv prefetch must not hit the
    network by default. Tests that exercise the prefetch override this."""
    monkeypatch.setattr(V, "resolve_arxiv_batch", lambda ids, session=None: {})
