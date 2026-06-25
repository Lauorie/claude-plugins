"""Pick the best canonical candidate and grade a citation against it.

Precision-first grading: HARD_FAIL only on high-precision signals (first-author
disjoint OR year off by >1). venue-only disagreement -> SOFT_WARN, because venue
normalization is lossy and we must not reject correct citations.
"""
from __future__ import annotations

import logging
from typing import List, Optional, Tuple

from .models import Citation, CanonicalRecord, CitationResult, Verdict
from .normalize import (
    title_overlap, first_author_mismatch, venue_key, author_conflict,
)

logger = logging.getLogger(__name__)

YEAR_TOLERANCE = 1
HARD_CONFIDENCE = 0.85


def best_match(citation: Citation, candidates: List[CanonicalRecord],
               threshold: float = 0.6) -> Optional[CanonicalRecord]:
    best, best_score = None, 0.0
    for cand in candidates:
        score = title_overlap(cand.title, citation.query)
        if score > best_score:
            best, best_score = cand, score
    return best if best_score >= threshold else None


def _mismatches(citation: Citation, canonical: CanonicalRecord) -> Tuple[str, ...]:
    fields = []
    cited_first = citation.authors[0] if citation.authors else ""
    canon_first = canonical.authors[0] if canonical.authors else ""
    if (first_author_mismatch(cited_first, canon_first)
            or author_conflict(citation.author_pairs, canonical.authors)):
        fields.append("authors")
    if (citation.year and canonical.year
            and abs(citation.year - canonical.year) > YEAR_TOLERANCE):
        fields.append("year")
    cv, kv = venue_key(citation.venue), venue_key(canonical.venue)
    if cv and kv and cv != kv:
        fields.append("venue")
    return tuple(fields)


def grade(citation: Citation, canonical: Optional[CanonicalRecord],
          any_backend_ok: bool) -> CitationResult:
    if canonical is None:
        if any_backend_ok:
            return CitationResult(citation, Verdict.SOFT_WARN, None, (),
                                  "未在任何权威源检索到，标记 [unverified] 待人工确认")
        return CitationResult(citation, Verdict.SKIP, None, (),
                              "所有检索源网络异常，已跳过校验")

    confidence = title_overlap(canonical.title, citation.query)
    fields = _mismatches(citation, canonical)
    hard = (("authors" in fields) or ("year" in fields)) and confidence >= HARD_CONFIDENCE
    correct = (
        f"权威记录（{canonical.source}）："
        f"{', '.join(canonical.authors[:3])}"
        f"{' et al.' if len(canonical.authors) > 3 else ''}. "
        f"{canonical.title}. {canonical.venue or ''} {canonical.year or ''}. "
        f"{canonical.pages or ''}"
    ).strip()
    if hard:
        return CitationResult(citation, Verdict.HARD_FAIL, canonical, fields,
                              f"字段疑似编造（{', '.join(fields)}）。{correct}")
    if fields and confidence < HARD_CONFIDENCE:
        return CitationResult(citation, Verdict.SOFT_WARN, canonical, fields,
                              f"未能高置信确认为同一篇（title 置信 {confidence:.2f}），字段存疑，请人工核对。{correct}")
    if fields:  # high confidence, venue-only
        return CitationResult(citation, Verdict.SOFT_WARN, canonical, fields,
                              f"venue 存疑（{', '.join(fields)}），请人工核对。{correct}")
    return CitationResult(citation, Verdict.PASS, canonical, (), "通过")


__all__ = ["best_match", "grade", "YEAR_TOLERANCE", "HARD_CONFIDENCE"]
