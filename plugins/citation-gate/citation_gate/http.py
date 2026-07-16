"""Minimal stdlib HTTP JSON client (no third-party deps)."""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 6
USER_AGENT = "citation-gate/1.0 (+https://github.com/atominfinite/claude-plugins)"


class HttpError(Exception):
    """Any failure fetching or parsing a JSON HTTP response.

    Attributes:
        status: HTTP status code when the server answered with an error
            response (e.g. 429); None for network/parse failures.
    """

    def __init__(self, message: str, status: Optional[int] = None):
        super().__init__(message)
        self.status = status


def _fetch(req: urllib.request.Request, timeout: int) -> dict:
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        return json.loads(raw)
    except urllib.error.HTTPError as e:
        raise HttpError(f"HTTP {e.code} {e.reason}", status=e.code) from e
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise HttpError(str(e)) from e


def get_json(url: str, params: Dict[str, object], timeout: int = DEFAULT_TIMEOUT,
             headers: Optional[Dict[str, str]] = None) -> dict:
    qs = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    full = f"{url}?{qs}" if qs else url
    req = urllib.request.Request(
        full, headers={"User-Agent": USER_AGENT, "Accept": "application/json",
                       **(headers or {})})
    return _fetch(req, timeout)


def post_json(url: str, params: Dict[str, object], body: Any,
              timeout: int = DEFAULT_TIMEOUT,
              headers: Optional[Dict[str, str]] = None) -> Any:
    """POST a JSON body and parse the JSON response. Raises HttpError on any
    network/parse failure (including non-2xx), mirroring get_json."""
    qs = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    full = f"{url}?{qs}" if qs else url
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        full, data=data, method="POST",
        headers={"User-Agent": USER_AGENT, "Accept": "application/json",
                 "Content-Type": "application/json", **(headers or {})})
    return _fetch(req, timeout)


__all__ = ["get_json", "post_json", "HttpError", "DEFAULT_TIMEOUT"]
