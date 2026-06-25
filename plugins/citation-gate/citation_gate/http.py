"""Minimal stdlib HTTP JSON client (no third-party deps)."""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from typing import Dict

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 6
USER_AGENT = "citation-gate/1.0 (+https://github.com/atominfinite/claude-plugins)"


class HttpError(Exception):
    """Any failure fetching or parsing a JSON HTTP response."""


def get_json(url: str, params: Dict[str, object], timeout: int = DEFAULT_TIMEOUT) -> dict:
    qs = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    full = f"{url}?{qs}" if qs else url
    req = urllib.request.Request(
        full, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        return json.loads(raw)
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise HttpError(str(e)) from e


__all__ = ["get_json", "HttpError", "DEFAULT_TIMEOUT"]
