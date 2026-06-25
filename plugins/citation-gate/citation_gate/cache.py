"""Local JSON cache keyed by normalized query hash."""
from __future__ import annotations

import dataclasses
import hashlib
import json
import logging
from pathlib import Path
from typing import List, Optional

from .models import CanonicalRecord
from .normalize import normalize_title

logger = logging.getLogger(__name__)

DEFAULT_DIR = Path.home() / ".claude" / ".cache" / "citation_gate"


class Cache:
    def __init__(self, cache_dir: Optional[Path] = None) -> None:
        self.dir = Path(cache_dir) if cache_dir else DEFAULT_DIR
        self.dir.mkdir(parents=True, exist_ok=True)

    def _path(self, query: str) -> Path:
        key = hashlib.sha1(normalize_title(query).encode("utf-8")).hexdigest()[:16]
        return self.dir / f"{key}.json"

    def get(self, query: str) -> Optional[List[CanonicalRecord]]:
        p = self._path(query)
        if not p.exists():
            return None
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
            return [CanonicalRecord(**{**r, "authors": tuple(r["authors"])}) for r in raw]
        except (OSError, ValueError, KeyError, TypeError) as e:
            logger.warning("cache read failed for %s: %s", p, e)
            return None

    def put(self, query: str, records: List[CanonicalRecord]) -> None:
        try:
            data = [dataclasses.asdict(r) for r in records]
            self._path(query).write_text(
                json.dumps(data, ensure_ascii=False), encoding="utf-8")
        except OSError as e:
            logger.warning("cache write failed: %s", e)


__all__ = ["Cache", "DEFAULT_DIR"]
