"""Verification report: grouping, text/JSON rendering, exit code."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, List

from .models import CitationResult, Verdict

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Report:
    results: List[CitationResult]

    def _by(self, v: Verdict) -> List[CitationResult]:
        return [r for r in self.results if r.verdict is v]

    @property
    def hard_fails(self) -> List[CitationResult]:
        return self._by(Verdict.HARD_FAIL)

    @property
    def soft_warns(self) -> List[CitationResult]:
        return self._by(Verdict.SOFT_WARN)

    @property
    def skipped(self) -> List[CitationResult]:
        return self._by(Verdict.SKIP)

    @property
    def passed(self) -> List[CitationResult]:
        return self._by(Verdict.PASS)

    def exit_code(self) -> int:
        return 1 if self.hard_fails else 0

    def _row(self, r: CitationResult) -> Dict:
        return {"index": r.citation.index, "verdict": r.verdict.value,
                "raw": r.citation.raw_text[:200],
                "mismatched_fields": list(r.mismatched_fields),
                "message": r.message}

    def to_dict(self) -> Dict:
        return {
            "total": len(self.results),
            "hard_fail": [self._row(r) for r in self.hard_fails],
            "soft_warn": [self._row(r) for r in self.soft_warns],
            "skip": [self._row(r) for r in self.skipped],
            "pass": len(self.passed),
        }

    def render_text(self) -> str:
        lines = ["=" * 60, "CITATION VERIFICATION", "=" * 60,
                 f"total={len(self.results)} pass={len(self.passed)} "
                 f"HARD_FAIL={len(self.hard_fails)} soft_warn={len(self.soft_warns)} "
                 f"skip={len(self.skipped)}"]
        for r in self.hard_fails:
            lines += [f"\n❌ [{r.citation.index}] HARD_FAIL ({', '.join(r.mismatched_fields)})",
                      f"   引用: {r.citation.raw_text[:160]}", f"   {r.message}"]
        for r in self.soft_warns:
            lines += [f"\n⚠️  [{r.citation.index}] {r.message[:160]}"]
        return "\n".join(lines)


__all__ = ["Report"]
