"""Scholarly reverse-lookup backends (registry, priority-ordered)."""
from __future__ import annotations

import logging
import os
import re
import time
import urllib.parse
from typing import Dict, List, Optional, Tuple

from . import http
from .models import CanonicalRecord

logger = logging.getLogger(__name__)

MAILTO = os.environ.get("CITATION_GATE_MAILTO", "citation-gate@users.noreply.github.com")
TIMEOUT = 6
POLITE_DELAY = 0.5
# Consecutive HTTP 429s from one backend before it is disabled for the run.
RATE_LIMIT_TRIP = 3
_REGISTRY_TMP = []

_DOI_RE = re.compile(r"^10\.\d{4,}/\S+$")
_ARXIV_DOI_RE = re.compile(r"^10\.48550/arxiv\.(.+)$", re.IGNORECASE)
_SS_PAPER_URL = "https://api.semanticscholar.org/graph/v1/paper/arXiv:{}"
ARXIV_RESOLVE_RETRIES = 2


class BackendError(Exception):
    """Raised when a backend cannot complete an HTTP lookup.

    Attributes:
        status: HTTP status code when the failure was an HTTP error response
            (e.g. 429), else None.
    """

    def __init__(self, message: str, status: Optional[int] = None):
        super().__init__(message)
        self.status = status


class BackendBreaker:
    """Per-run circuit breaker for rate-limited backends.

    A backend that answers HTTP 429 `threshold` times in a row (Semantic
    Scholar's anonymous pool does this for minutes at a time) is disabled for
    the rest of the run instead of being re-queried — and re-429ing — once per
    citation. Any successful response resets that backend's count.
    """

    def __init__(self, threshold: int = RATE_LIMIT_TRIP):
        self.threshold = threshold
        self._consecutive_429s: Dict[str, int] = {}

    def record_rate_limited(self, name: str) -> None:
        self._consecutive_429s[name] = self._consecutive_429s.get(name, 0) + 1

    def record_ok(self, name: str) -> None:
        self._consecutive_429s[name] = 0

    def tripped(self, name: str) -> bool:
        return self._consecutive_429s.get(name, 0) >= self.threshold


def _s2_headers() -> Optional[Dict[str, str]]:
    """Semantic Scholar auth header from CITATION_GATE_S2_API_KEY (if set).

    A key moves requests off the shared anonymous pool, which 429s under load.
    """
    key = os.environ.get("CITATION_GATE_S2_API_KEY", "").strip()
    return {"x-api-key": key} if key else None


def register_backend(cls: type) -> type:
    _REGISTRY_TMP.append(cls)
    return cls


def _to_int(v: object) -> Optional[int]:
    try:
        return int(str(v)[:4])
    except (TypeError, ValueError):
        return None


def normalize_doi(s: str) -> str:
    """Lowercase, strip leading https://doi.org/ or doi: prefix and whitespace."""
    out = (s or "").strip().lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi.org/", "doi:"):
        if out.startswith(prefix):
            out = out[len(prefix):]
            break
    return out.strip()


def valid_doi(doi: str) -> bool:
    """True iff doi matches the registrant-prefix DOI grammar (10.NNNN/suffix)."""
    return bool(_DOI_RE.match(normalize_doi(doi)))


def _crossref_message_to_record(msg: dict) -> CanonicalRecord:
    """Map a single CrossRef `message` object to a CanonicalRecord.

    Same field mapping as CrossrefBackend, but `message` is one object (not a list).
    """
    authors = tuple(
        f"{a.get('given', '')} {a.get('family', '')}".strip()
        for a in (msg.get("author") or [])
    )
    year = None
    dp = (msg.get("issued") or {}).get("date-parts", [[None]])
    if dp and dp[0] and dp[0][0]:
        year = _to_int(dp[0][0])
    return CanonicalRecord(
        title=(msg.get("title") or [""])[0].rstrip("."), authors=authors,
        year=year, venue=(msg.get("container-title") or [None])[0],
        pages=msg.get("page"), doi=msg.get("DOI"), source="crossref-doi",
    )


def _resolve_arxiv(arxiv_id: str, session=None) -> Optional[CanonicalRecord]:
    """Resolve an arXiv id to a CanonicalRecord via Semantic Scholar's paper
    endpoint (CrossRef does not index 10.48550/arxiv.* DOIs). Retries a few times
    on transient HTTP failure (e.g. 429) with light backoff; returns None on
    persistent failure (fail open)."""
    url = _SS_PAPER_URL.format(arxiv_id.strip())
    for attempt in range(ARXIV_RESOLVE_RETRIES):
        try:
            p = http.get_json(url, {"fields": "title,authors,year,venue,externalIds"},
                              timeout=TIMEOUT, headers=_s2_headers())
            authors = tuple(a.get("name", "") for a in (p.get("authors") or []))
            ext = p.get("externalIds") or {}
            title = (p.get("title") or "").rstrip(".")
            if not title:
                return None
            return CanonicalRecord(
                title=title, authors=authors, year=_to_int(p.get("year")),
                venue=p.get("venue"), pages=None,
                doi=ext.get("DOI") or f"10.48550/arXiv.{arxiv_id}", source="arxiv-ss",
            )
        except (http.HttpError, ValueError, KeyError, TypeError) as e:
            logger.warning("_resolve_arxiv failed for %s: %s", arxiv_id, e)
            time.sleep(POLITE_DELAY * (attempt + 1))
    return None


def resolve_arxiv_batch(arxiv_ids, session=None) -> dict:
    """Resolve many arXiv ids in ONE Semantic Scholar /paper/batch call → {id: rec}.

    Rate-limit-friendly for large bibliographies (one request instead of N).
    Returns the records it could resolve; missing/failed ids are simply absent
    (fail open). Retries the whole batch on transient HTTP error with backoff."""
    ids = [i for i in dict.fromkeys(arxiv_ids) if i]
    if not ids:
        return {}
    out: dict = {}
    for attempt in range(ARXIV_RESOLVE_RETRIES + 1):
        try:
            data = http.post_json(
                "https://api.semanticscholar.org/graph/v1/paper/batch",
                {"fields": "title,authors,year,venue,externalIds"},
                {"ids": [f"ARXIV:{i}" for i in ids]}, timeout=TIMEOUT * 3,
                headers=_s2_headers()) or []
            for i, p in zip(ids, data):
                if not p:
                    continue
                title = (p.get("title") or "").rstrip(".")
                if not title:
                    continue
                authors = tuple(a.get("name", "") for a in (p.get("authors") or []))
                ext = p.get("externalIds") or {}
                out[i] = CanonicalRecord(
                    title=title, authors=authors, year=_to_int(p.get("year")),
                    venue=p.get("venue"), pages=None,
                    doi=ext.get("DOI") or f"10.48550/arXiv.{i}", source="arxiv-ss")
            return out
        except http.HttpError as e:
            logger.warning("resolve_arxiv_batch network error: %s", e)
            time.sleep(POLITE_DELAY * (attempt + 1))
        except (ValueError, KeyError, TypeError) as e:
            logger.warning("resolve_arxiv_batch parse error: %s", e)
            return out
    return out


def _datacite_attrs_to_record(norm_doi: str, attrs: dict) -> Optional[CanonicalRecord]:
    """Map a DataCite /dois attributes object to a CanonicalRecord."""
    titles = attrs.get("titles") or []
    title = (titles[0] or {}).get("title") if titles else None
    if not title:
        return None
    authors = []
    for creator in attrs.get("creators") or []:
        given, family = creator.get("givenName"), creator.get("familyName")
        if given and family:
            authors.append(f"{given} {family}")
        elif creator.get("name"):
            name = creator["name"]
            if "," in name:  # DataCite 'name' is 'Family, Given'
                fam, _, giv = name.partition(",")
                name = f"{giv.strip()} {fam.strip()}".strip()
            authors.append(name)
    year = attrs.get("publicationYear")
    container = attrs.get("container") or {}
    return CanonicalRecord(
        title=title, authors=tuple(authors),
        year=year if isinstance(year, int) else None,
        venue=container.get("title") or attrs.get("publisher"),
        pages=None, doi=norm_doi, source="datacite",
    )


def _resolve_datacite(norm_doi: str) -> Optional[CanonicalRecord]:
    """DataCite fallback for DOIs CrossRef does not register (theses,
    institutional repositories, datasets). Fail open."""
    url = f"https://api.datacite.org/dois/{urllib.parse.quote(norm_doi, safe='')}"
    try:
        payload = http.get_json(url, {}, timeout=TIMEOUT)
        attrs = (payload.get("data") or {}).get("attributes")
        if not isinstance(attrs, dict):
            return None
        return _datacite_attrs_to_record(norm_doi, attrs)
    except (http.HttpError, ValueError, KeyError, TypeError) as e:
        logger.warning("datacite resolve failed for %s: %s", norm_doi, e)
        return None


def resolve_doi(doi: str, session=None) -> Optional[CanonicalRecord]:
    """Resolve a DOI to a CanonicalRecord.

    arXiv DOIs (10.48550/arxiv.*) go to Semantic Scholar; everything else goes to
    CrossRef's /works/<doi> endpoint, then falls back to DataCite (theses and
    institutional-repository DOIs are registered there, not with CrossRef).
    Returns None on 404 or any network/parse error (never raises out — fail
    open). `session` is accepted for call-site compatibility but ignored (the
    stdlib http client is stateless).
    """
    norm = normalize_doi(doi)
    m = _ARXIV_DOI_RE.match(norm)
    if m:
        rec = _resolve_arxiv(m.group(1), session)
        if rec is not None:
            return rec
        # fall through to CrossRef (usually 404) so behaviour is unchanged
    quoted = urllib.parse.quote(norm, safe="")
    url = f"https://api.crossref.org/works/{quoted}"
    try:
        payload = http.get_json(url, {"mailto": MAILTO}, timeout=TIMEOUT)
        msg = payload.get("message")
        if isinstance(msg, dict):
            return _crossref_message_to_record(msg)
    except (http.HttpError, ValueError, KeyError, TypeError) as e:
        logger.warning("resolve_doi failed for %s: %s", doi, e)
    return _resolve_datacite(norm)


@register_backend
class DblpBackend:
    name = "dblp"
    url = "https://dblp.org/search/publ/api"

    def search(self, query: str, session=None) -> List[CanonicalRecord]:
        try:
            payload = http.get_json(self.url, {"q": query, "format": "json", "h": 5},
                                    timeout=TIMEOUT)
            hits = payload.get("result", {}).get("hits", {}).get("hit", [])
        except http.HttpError as e:
            raise BackendError(str(e), status=e.status) from e
        out = []
        for h in hits:
            info = h.get("info", {})
            au = info.get("authors", {}).get("author", [])
            au = au if isinstance(au, list) else [au]
            authors = tuple(a.get("text", "") for a in au if a.get("text"))
            out.append(CanonicalRecord(
                title=info.get("title", "").rstrip("."), authors=authors,
                year=_to_int(info.get("year")), venue=info.get("venue"),
                pages=info.get("pages"), doi=info.get("doi"), source=self.name,
            ))
        return out


@register_backend
class SemanticScholarBackend:
    name = "semanticscholar"
    url = "https://api.semanticscholar.org/graph/v1/paper/search"

    def search(self, query: str, session=None) -> List[CanonicalRecord]:
        try:
            payload = http.get_json(self.url, {
                "query": query, "limit": 5,
                "fields": "title,authors,year,venue,externalIds",
            }, timeout=TIMEOUT, headers=_s2_headers())
            data = payload.get("data", []) or []
        except http.HttpError as e:
            raise BackendError(str(e), status=e.status) from e
        out = []
        for p in data:
            authors = tuple(a.get("name", "") for a in (p.get("authors") or []))
            ext = p.get("externalIds") or {}
            out.append(CanonicalRecord(
                title=(p.get("title") or "").rstrip("."), authors=authors,
                year=_to_int(p.get("year")), venue=p.get("venue"),
                pages=None, doi=ext.get("DOI"), source=self.name,
            ))
        return out


@register_backend
class CrossrefBackend:
    name = "crossref"
    url = "https://api.crossref.org/works"

    def search(self, query: str, session=None) -> List[CanonicalRecord]:
        try:
            payload = http.get_json(self.url, {
                "query.bibliographic": query, "rows": 5, "mailto": MAILTO,
            }, timeout=TIMEOUT)
            items = payload.get("message", {}).get("items", []) or []
        except http.HttpError as e:
            raise BackendError(str(e), status=e.status) from e
        out = []
        for it in items:
            authors = tuple(
                f"{a.get('given', '')} {a.get('family', '')}".strip()
                for a in (it.get("author") or [])
            )
            year = None
            dp = it.get("issued", {}).get("date-parts", [[None]])
            if dp and dp[0] and dp[0][0]:
                year = _to_int(dp[0][0])
            out.append(CanonicalRecord(
                title=(it.get("title") or [""])[0].rstrip("."), authors=authors,
                year=year, venue=(it.get("container-title") or [None])[0],
                pages=it.get("page"), doi=it.get("DOI"), source=self.name,
            ))
        return out


@register_backend
class OpenAlexBackend:
    name = "openalex"
    url = "https://api.openalex.org/works"

    def search(self, query: str, session=None) -> List[CanonicalRecord]:
        try:
            payload = http.get_json(self.url, {"search": query, "per-page": 5,
                                               "mailto": MAILTO}, timeout=TIMEOUT)
            results = payload.get("results", []) or []
        except http.HttpError as e:
            raise BackendError(str(e), status=e.status) from e
        out = []
        for w in results:
            authors = tuple(
                (a.get("author") or {}).get("display_name", "")
                for a in (w.get("authorships") or [])
            )
            loc = (w.get("primary_location") or {}).get("source") or {}
            out.append(CanonicalRecord(
                title=(w.get("display_name") or "").rstrip("."), authors=authors,
                year=_to_int(w.get("publication_year")),
                venue=loc.get("display_name"), pages=None,
                doi=(w.get("doi") or "").replace("https://doi.org/", "") or None,
                source=self.name,
            ))
        return out


# Instantiate in declaration order to fix priority
BACKEND_REGISTRY = [cls() for cls in _REGISTRY_TMP]


def search_all(query: str, session=None,
               polite_delay: float = POLITE_DELAY,
               breaker: Optional[BackendBreaker] = None,
               ) -> Tuple[List[CanonicalRecord], bool]:
    """Query backends in priority order until one returns hits.

    Args:
        query: Search string to pass to each backend.
        session: Ignored (kept for call-site compatibility).
        polite_delay: Seconds to sleep between backends that returned no hits.
        breaker: Optional per-run circuit breaker; backends it has tripped
            (persistent HTTP 429) are skipped without an HTTP attempt.

    Returns:
        Tuple of (records, any_backend_ok) where any_backend_ok is True if at
        least one backend responded with HTTP 200 (even with 0 hits).
    """
    any_ok = False
    queried = False
    for backend in BACKEND_REGISTRY:
        if breaker is not None and breaker.tripped(backend.name):
            continue
        if queried:
            time.sleep(polite_delay)
        queried = True
        try:
            recs = backend.search(query)
            any_ok = True
            if breaker is not None:
                breaker.record_ok(backend.name)
            if recs:
                return recs, True
        except BackendError as e:
            if breaker is not None and e.status == 429:
                breaker.record_rate_limited(backend.name)
                if breaker.tripped(backend.name):
                    logger.warning(
                        "backend %s rate-limited (HTTP 429) %d times in a row; "
                        "disabled for the rest of this run",
                        backend.name, breaker.threshold)
                    continue
            logger.warning("backend %s failed: %s", backend.name, e)
    return [], any_ok


__all__ = ["BACKEND_REGISTRY", "register_backend", "search_all", "BackendError",
           "BackendBreaker", "RATE_LIMIT_TRIP",
           "DblpBackend", "SemanticScholarBackend", "CrossrefBackend", "OpenAlexBackend",
           "normalize_doi", "valid_doi", "resolve_doi"]
