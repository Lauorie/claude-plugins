"""Frozen data models for citation verification."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Tuple


class Verdict(str, Enum):
    PASS = "PASS"
    HARD_FAIL = "HARD_FAIL"
    SOFT_WARN = "SOFT_WARN"
    SKIP = "SKIP"


@dataclass(frozen=True)
class Citation:
    raw_text: str
    index: int
    title: Optional[str] = None
    authors: Tuple[str, ...] = ()
    author_pairs: Tuple[Tuple[str, str], ...] = ()
    year: Optional[int] = None
    venue: Optional[str] = None
    pages: Optional[str] = None
    doi: Optional[str] = None

    @property
    def query(self) -> str:
        """Search string for reverse lookup: title if structured, else raw entry."""
        return self.title if self.title else self.raw_text


@dataclass(frozen=True)
class CanonicalRecord:
    title: str
    authors: Tuple[str, ...]
    year: Optional[int]
    venue: Optional[str]
    pages: Optional[str]
    doi: Optional[str]
    source: str


@dataclass(frozen=True)
class CitationResult:
    citation: Citation
    verdict: Verdict
    canonical: Optional[CanonicalRecord]
    mismatched_fields: Tuple[str, ...]
    message: str


__all__ = ["Verdict", "Citation", "CanonicalRecord", "CitationResult"]
