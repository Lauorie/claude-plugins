"""Orchestrate parse → reverse-lookup (cached) → match → grade."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional

from .cache import Cache
from .match import best_match, grade, _mismatches
from .models import Citation, CanonicalRecord, CitationResult, Verdict
from .parse import extract_citations
from .report import Report
from .backends import search_all, normalize_doi, valid_doi, resolve_doi
from .normalize import title_overlap, venue_conflicts

logger = logging.getLogger(__name__)

_FILETYPE = {".bib": "bib", ".tex": "tex", ".md": "md"}
MAX_CITATIONS_PER_RUN = 30
DOI_TITLE_OVERLAP = 0.5
_ARXIV_DOI_PREFIX = "10.48550"


def _doi_correct_str(rec: CanonicalRecord) -> str:
    """Compact authoritative-record string for a DOI-resolved record."""
    return (
        f"{', '.join(rec.authors[:3])}"
        f"{' et al.' if len(rec.authors) > 3 else ''}. "
        f"{rec.title}. {rec.venue or ''} {rec.year or ''}".strip()
    )


def _check_doi(citation: Citation, title_canonical: Optional[CanonicalRecord],
               session) -> Optional[CitationResult]:
    """DOI-aware grading. Returns a HARD_FAIL CitationResult when a DOI rule fires,
    else None (caller falls through to the title-search grade). Fail open: any
    network failure inside resolve_doi yields None and never raises."""
    doi = citation.doi
    if not doi:
        return None

    # Rule 1: malformed DOI (e.g. wrong registrant prefix 20.48550/...).
    if not valid_doi(doi):
        return CitationResult(
            citation, Verdict.HARD_FAIL, None, ("doi",),
            f"DOI 格式非法（必须以 10. 开头）：{doi}")

    doi_rec = resolve_doi(doi, session)
    if doi_rec is not None:
        # Rule 2a: the DOI points at a different paper.
        if title_overlap(doi_rec.title, citation.query) < DOI_TITLE_OVERLAP:
            return CitationResult(
                citation, Verdict.HARD_FAIL, doi_rec, ("doi",),
                f"DOI 指向的是另一篇论文：'{doi_rec.title}'，与所引标题不符")
        # Rule 2b: DOI is an exact identifier → no title-confidence gate needed.
        # A DOI is precise, so use a strict asymmetric venue conflict on top of
        # the lossy alias comparison (catches 'cited AAAI but DOI is IEEE Access').
        fields = list(_mismatches(citation, doi_rec))
        if "venue" not in fields and venue_conflicts(citation.venue, doi_rec.venue):
            fields.append("venue")
        fields = tuple(fields)
        if fields:
            return CitationResult(
                citation, Verdict.HARD_FAIL, doi_rec, fields,
                f"与 DOI 对应的权威记录字段不符（{', '.join(fields)}）。"
                f"正确：{_doi_correct_str(doi_rec)}")
        return None

    # doi_rec is None: cited DOI did not resolve via CrossRef.
    norm = normalize_doi(doi)
    if (not norm.startswith(_ARXIV_DOI_PREFIX)
            and title_canonical is not None and title_canonical.doi
            and normalize_doi(title_canonical.doi) != norm):
        return CitationResult(
            citation, Verdict.HARD_FAIL, title_canonical, ("doi",),
            f"DOI 与权威记录不符：所引 {doi}，实际应为 {title_canonical.doi}")
    # Otherwise never HARD_FAIL merely because CrossRef lacked the DOI.
    return None


def _verify_one(citation: Citation, session, cache: Cache) -> CitationResult:
    cached = cache.get(citation.query)
    if cached is not None:
        records, any_ok = cached, True
    else:
        records, any_ok = search_all(citation.query, session)
        if any_ok:
            cache.put(citation.query, records)
    title_canonical = best_match(citation, records) if records else None

    if citation.doi:
        try:
            doi_result = _check_doi(citation, title_canonical, session)
        except Exception as e:  # fail open: DOI checks never break verification
            logger.warning("DOI check raised for [%s]: %s", citation.index, e)
            doi_result = None
        if doi_result is not None:
            return doi_result

    return grade(citation, title_canonical, any_backend_ok=any_ok)


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
