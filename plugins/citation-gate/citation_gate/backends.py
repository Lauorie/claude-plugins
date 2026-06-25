"""Scholarly reverse-lookup backends (registry, priority-ordered)."""
from __future__ import annotations

import logging
import os
import re
import time
import urllib.parse
from typing import List, Optional, Tuple

from . import http
from .models import CanonicalRecord

logger = logging.getLogger(__name__)

MAILTO = os.environ.get("CITATION_GATE_MAILTO", "citation-gate@users.noreply.github.com")
TIMEOUT = 6
POLITE_DELAY = 0.5
_REGISTRY_TMP = []

_DOI_RE = re.compile(r"^10\.\d{4,}/\S+$")


class BackendError(Exception):
    """Raised when a backend cannot complete an HTTP lookup."""


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


def resolve_doi(doi: str, session=None) -> Optional[CanonicalRecord]:
    """Resolve a DOI directly against CrossRef's /works/<doi> endpoint.

    Returns a CanonicalRecord on HTTP 200; returns None on 404 or any
    network/parse error (never raises out — fail open). `session` is accepted
    for call-site compatibility but ignored (the stdlib http client is stateless).
    """
    quoted = urllib.parse.quote(normalize_doi(doi), safe="")
    url = f"https://api.crossref.org/works/{quoted}"
    try:
        payload = http.get_json(url, {"mailto": MAILTO}, timeout=TIMEOUT)
        msg = payload.get("message")
        if not isinstance(msg, dict):
            return None
        return _crossref_message_to_record(msg)
    except (http.HttpError, ValueError, KeyError, TypeError) as e:
        logger.warning("resolve_doi failed for %s: %s", doi, e)
        return None


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
            raise BackendError(str(e)) from e
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
            }, timeout=TIMEOUT)
            data = payload.get("data", []) or []
        except http.HttpError as e:
            raise BackendError(str(e)) from e
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
            raise BackendError(str(e)) from e
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
            raise BackendError(str(e)) from e
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
               polite_delay: float = POLITE_DELAY) -> Tuple[List[CanonicalRecord], bool]:
    """Query backends in priority order until one returns hits.

    Args:
        query: Search string to pass to each backend.
        session: Ignored (kept for call-site compatibility).
        polite_delay: Seconds to sleep between backends that returned no hits.

    Returns:
        Tuple of (records, any_backend_ok) where any_backend_ok is True if at
        least one backend responded with HTTP 200 (even with 0 hits).
    """
    any_ok = False
    for i, backend in enumerate(BACKEND_REGISTRY):
        try:
            recs = backend.search(query)
            any_ok = True
            if recs:
                return recs, True
        except BackendError as e:
            logger.warning("backend %s failed: %s", backend.name, e)
        if i < len(BACKEND_REGISTRY) - 1:
            time.sleep(polite_delay)
    return [], any_ok


__all__ = ["BACKEND_REGISTRY", "register_backend", "search_all", "BackendError",
           "DblpBackend", "SemanticScholarBackend", "CrossrefBackend", "OpenAlexBackend",
           "normalize_doi", "valid_doi", "resolve_doi"]
