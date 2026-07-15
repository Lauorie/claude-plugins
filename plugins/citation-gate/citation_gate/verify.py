"""Orchestrate parse → reverse-lookup (cached) → match → grade."""
from __future__ import annotations

import logging
import os
import re
import time
from pathlib import Path
from typing import List, Optional

from .cache import Cache
from .match import best_match, grade, _mismatches
from .models import Citation, CanonicalRecord, CitationResult, Verdict
from .parse import extract_citations
from .report import Report
from .backends import (
    search_all, normalize_doi, valid_doi, resolve_doi, resolve_arxiv_batch,
)
from .normalize import title_overlap, venue_conflicts, title_mismatch, extra_authors

logger = logging.getLogger(__name__)

_FILETYPE = {".bib": "bib", ".tex": "tex", ".md": "md"}
MAX_CITATIONS_PER_RUN = 30
# Wall-clock budget: the Stop hook is hard-killed at 300s (hooks.json timeout),
# which loses the whole report; wind down before that with margin to spare.
# Override via CITATION_GATE_BUDGET (seconds); <= 0 disables the limit.
DEFAULT_BUDGET_SECONDS = 270


def _resolve_budget(budget_seconds: Optional[float]) -> Optional[float]:
    """Effective budget in seconds, or None for unlimited."""
    if budget_seconds is None:
        raw = os.environ.get("CITATION_GATE_BUDGET", "")
        try:
            budget_seconds = float(raw) if raw else DEFAULT_BUDGET_SECONDS
        except ValueError:
            logger.warning("invalid CITATION_GATE_BUDGET=%r; using default %ss",
                           raw, DEFAULT_BUDGET_SECONDS)
            budget_seconds = DEFAULT_BUDGET_SECONDS
    return budget_seconds if budget_seconds > 0 else None
DOI_TITLE_OVERLAP = 0.5
_ARXIV_DOI_PREFIX = "10.48550"
# arXiv DOIs are always registrant 10.48550; any other 10.NNNNN/arxiv.* is malformed.
_ARXIV_PREFIX_RE = re.compile(r"^(10\.\d{4,})/arxiv\.", re.IGNORECASE)


def _doi_correct_str(rec: CanonicalRecord) -> str:
    """Compact authoritative-record string for a DOI-resolved record."""
    return (
        f"{', '.join(rec.authors[:3])}"
        f"{' et al.' if len(rec.authors) > 3 else ''}. "
        f"{rec.title}. {rec.venue or ''} {rec.year or ''}".strip()
    )


def _resolve_doi_cached(doi: str, session, cache: Cache) -> Optional[CanonicalRecord]:
    """resolve_doi with a persistent cache of *successful* resolutions only.
    Failures (network/429) are not cached so a later run can retry — this also
    keeps large bibliographies from re-paying arXiv-resolution latency each run."""
    key = "doi-resolve::" + normalize_doi(doi)
    hit = cache.get(key)
    if hit is not None:
        return hit[0] if hit else None
    rec = resolve_doi(doi, session)
    if rec is not None:
        cache.put(key, [rec])
    return rec


def _check_doi(citation: Citation, title_canonical: Optional[CanonicalRecord],
               session, cache: Cache) -> Optional[CitationResult]:
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

    # Rule 1b: an arXiv DOI must be registrant 10.48550 (offline, no network).
    m_ax = _ARXIV_PREFIX_RE.match(normalize_doi(doi))
    if m_ax and m_ax.group(1) != _ARXIV_DOI_PREFIX:
        return CitationResult(
            citation, Verdict.HARD_FAIL, None, ("doi",),
            f"arXiv DOI 前缀应为 10.48550，实际为 {m_ax.group(1)}：{doi}")

    doi_rec = _resolve_doi_cached(doi, session, cache)
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
        # DOI pins the exact paper → the authoritative author list is complete, so
        # a cited author absent from it is a fabricated/inserted co-author.
        if "authors" not in fields and extra_authors(
                citation.author_pairs, doi_rec.authors):
            fields.append("authors")
        # DOI pins the exact paper → the cited title must match the authoritative
        # one (tolerant of acronym suffix / subtitle drop). Catches a real title
        # kept under a correct DOI but with words altered/removed.
        if ("title" not in fields and citation.title
                and title_mismatch(citation.title, doi_rec.title)):
            fields.append("title")
        fields = tuple(fields)
        if fields:
            return CitationResult(
                citation, Verdict.HARD_FAIL, doi_rec, fields,
                f"与 DOI 对应的权威记录字段不符（{', '.join(fields)}）。"
                f"正确：{_doi_correct_str(doi_rec)}")
        # DOI is an exact identifier and every checked field agrees → authoritative
        # PASS; no need to fall through to the noisier title search.
        return CitationResult(citation, Verdict.PASS, doi_rec, (),
                              "通过（DOI 权威记录一致）")

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


def _prefetch_arxiv(citations: List[Citation], session, cache: Cache) -> None:
    """One batched Semantic Scholar call resolves every correct-prefix arXiv DOI
    up front and seeds the resolve cache — so a 23-entry bibliography needs one
    request, not N, and survives per-endpoint rate limiting."""
    pending: dict = {}  # arxiv_id -> [doi-cache-key, ...]
    for c in citations:
        if not c.doi:
            continue
        nd = normalize_doi(c.doi)
        m = _ARXIV_PREFIX_RE.match(nd)
        if not (m and m.group(1) == _ARXIV_DOI_PREFIX):
            continue
        key = "doi-resolve::" + nd
        if cache.get(key) is not None:
            continue
        aid = nd.split("/arxiv.", 1)[1]
        pending.setdefault(aid, []).append(key)
    if not pending:
        return
    try:
        recs = resolve_arxiv_batch(list(pending), session)
    except Exception as e:  # fail open: prefetch is an optimisation, never fatal
        logger.warning("arxiv prefetch failed: %s", e)
        return
    for aid, keys in pending.items():
        rec = recs.get(aid)
        if rec is not None:
            for k in keys:
                cache.put(k, [rec])


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
            doi_result = _check_doi(citation, title_canonical, session, cache)
        except Exception as e:  # fail open: DOI checks never break verification
            logger.warning("DOI check raised for [%s]: %s", citation.index, e)
            doi_result = None
        if doi_result is not None:
            return doi_result

    return grade(citation, title_canonical, any_backend_ok=any_ok)


def verify_files(paths: List[str], session=None,
                 cache: Optional[Cache] = None,
                 budget_seconds: Optional[float] = None) -> Report:
    """Verify citations in `paths`.

    Args:
        paths: Files to scan for citations.
        session: Optional HTTP session passed through to backends.
        cache: Result cache; a fresh default cache when omitted.
        budget_seconds: Wall-clock budget; None reads CITATION_GATE_BUDGET
            (default 270s), <= 0 disables the limit. Citations not reached
            within the budget are reported as SKIP, never verified.

    Returns:
        Report over all extracted citations (capped at MAX_CITATIONS_PER_RUN).
    """
    cache = cache or Cache()
    budget = _resolve_budget(budget_seconds)
    started = time.monotonic()

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

    _prefetch_arxiv(all_citations, session, cache)

    results: List[CitationResult] = []
    consecutive_skips = 0
    budget_exhausted = False
    for citation in all_citations:
        if not budget_exhausted and budget is not None \
                and time.monotonic() - started > budget:
            budget_exhausted = True
            logger.warning("citation-gate: %ss budget exhausted; skipping rest", budget)
        if budget_exhausted:
            results.append(CitationResult(
                citation, Verdict.SKIP, None, (),
                f"时间预算耗尽（{budget:g}s），跳过剩余未核验引用",
            ))
            continue
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


__all__ = ["verify_files", "MAX_CITATIONS_PER_RUN", "DEFAULT_BUDGET_SECONDS"]
