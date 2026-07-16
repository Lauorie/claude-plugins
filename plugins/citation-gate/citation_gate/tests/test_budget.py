"""Time budget: verify_files must wind down gracefully before the Stop hook
is hard-killed by the harness (settings.json timeout 600s), instead of losing
the whole report to SIGKILL."""
import itertools
from unittest.mock import MagicMock

from citation_gate.cache import Cache
from citation_gate.models import Verdict
from citation_gate import verify as V

DOC = (
    "[1] A. X. T1. ICML. 2020.\n"
    "[2] B. Y. T2. ICML. 2020.\n"
    "[3] C. Z. T3. ICML. 2020.\n"
)


def _install_fake_clock(monkeypatch, step: float = 100.0) -> None:
    """Each time.monotonic() call advances the clock by `step` seconds."""
    counter = itertools.count(0)
    monkeypatch.setattr(V.time, "monotonic", lambda: next(counter) * step)


def test_budget_exhausted_skips_remaining(tmp_path, monkeypatch):
    f = tmp_path / "p.md"
    f.write_text(DOC, encoding="utf-8")
    monkeypatch.setattr(V, "search_all", lambda q, s, **kw: ([], True))
    # Clock: start=0, then 100/200/300 at each per-citation check.
    _install_fake_clock(monkeypatch)
    report = V.verify_files([str(f)], session=MagicMock(),
                            cache=Cache(cache_dir=tmp_path), budget_seconds=250)
    # Citations 1-2 checked at t=100/200 (within budget) → verified (soft warn,
    # search returned nothing); citation 3 checked at t=300 → budget exhausted.
    assert len(report.soft_warns) == 2
    assert len(report.skipped) == 1
    skipped = report.skipped[0]
    assert skipped.verdict is Verdict.SKIP
    assert "时间预算" in skipped.message
    assert report.exit_code() == 0  # budget exhaustion never blocks by itself


def test_budget_from_env_var(tmp_path, monkeypatch):
    f = tmp_path / "p.md"
    f.write_text(DOC, encoding="utf-8")
    monkeypatch.setattr(V, "search_all", lambda q, s, **kw: ([], True))
    monkeypatch.setenv("CITATION_GATE_BUDGET", "250")
    _install_fake_clock(monkeypatch)
    report = V.verify_files([str(f)], session=MagicMock(),
                            cache=Cache(cache_dir=tmp_path))
    assert len(report.skipped) == 1


def test_budget_zero_disables_limit(tmp_path, monkeypatch):
    f = tmp_path / "p.md"
    f.write_text(DOC, encoding="utf-8")
    monkeypatch.setattr(V, "search_all", lambda q, s, **kw: ([], True))
    _install_fake_clock(monkeypatch, step=1e6)
    report = V.verify_files([str(f)], session=MagicMock(),
                            cache=Cache(cache_dir=tmp_path), budget_seconds=0)
    assert len(report.skipped) == 0
    assert len(report.soft_warns) == 3


def test_default_budget_fits_hook_timeout():
    # settings.json Stop timeout is 600s; the default stays well below it both
    # for margin and to keep default delivery latency reasonable.
    assert 0 < V.DEFAULT_BUDGET_SECONDS < 300
