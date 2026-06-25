"""Orchestrate parse → reverse-lookup (cached) → match → grade."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional

from .cache import Cache
from .match import best_match, grade
from .models import Citation, CitationResult, Verdict
from .parse import extract_citations
from .report import Report
from .backends import search_all

logger = logging.getLogger(__name__)

_FILETYPE = {".bib": "bib", ".tex": "tex", ".md": "md"}
MAX_CITATIONS_PER_RUN = 30


def _verify_one(citation: Citation, session, cache: Cache) -> CitationResult:
    cached = cache.get(citation.query)
    if cached is not None:
        records, any_ok = cached, True
    else:
        records, any_ok = search_all(citation.query, session)
        if any_ok:
            cache.put(citation.query, records)
    canonical = best_match(citation, records) if records else None
    return grade(citation, canonical, any_backend_ok=any_ok)


def verify_files(paths: List[str], session=None,
                 cache: Optional[Cache] = None) -> Report:
    cache = cache or Cache()

    # Gather all citations first so we can apply the per-run cap
    all_citations: List[Citation] = []
    citation_sources: dict = {}  # citation index → nothing (order preserved)
    for path in paths:
        p = Path(path)
        filetype = _FILETYPE.get(p.suffix.lower(), "md")
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError as e:
            logger.warning("cannot read %s: %s", path, e)
            continue
        all_citations.extend(extract_citations(text, filetype))

    total = len(all_citations)
    if total > MAX_CITATIONS_PER_RUN:
        logger.warning(
            "citation-gate: %d citations exceeded cap %d; verified first %d, skipped %d",
            total, MAX_CITATIONS_PER_RUN, MAX_CITATIONS_PER_RUN, total - MAX_CITATIONS_PER_RUN,
        )
        all_citations = all_citations[:MAX_CITATIONS_PER_RUN]

    results: List[CitationResult] = []
    consecutive_skips = 0
    for citation in all_citations:
        if consecutive_skips >= 2:
            results.append(CitationResult(
                citation, Verdict.SKIP, None, (),
                "网络异常连续跳过，已快速跳过剩余引用",
            ))
            continue
        result = _verify_one(citation, session, cache)
        results.append(result)
        if result.verdict is Verdict.SKIP:
            consecutive_skips += 1
        else:
            consecutive_skips = 0
    return Report(results)


__all__ = ["verify_files", "MAX_CITATIONS_PER_RUN"]
