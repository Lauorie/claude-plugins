"""Text normalization, similarity, author/venue matching primitives."""
from __future__ import annotations

import re
from typing import Optional, Set

_PUNCT = re.compile(r"[^a-z0-9]+")
_WS = re.compile(r"\s+")

# venue 归一表：normalized-substring -> canonical key（长模式优先匹配）
VENUE_ALIASES = {
    "international joint conference on artificial intelligence": "IJCAI",
    "ijcai": "IJCAI",
    "association for the advancement of artificial intelligence": "AAAI",
    "aaai": "AAAI",
    "advances in neural information processing systems": "NeurIPS",
    "neurips": "NeurIPS",
    "nips": "NeurIPS",
    "international conference on machine learning": "ICML",
    "icml": "ICML",
    "international conference on learning representations": "ICLR",
    "iclr": "ICLR",
    "empirical methods in natural language processing": "EMNLP",
    "emnlp": "EMNLP",
    "annual meeting of the association for computational linguistics": "ACL",
    "north american chapter of the association for computational linguistics": "NAACL",
    # NAACL 2025 renamed its proceedings to "Nations of the Americas Chapter…".
    "nations of the americas chapter of the association for computational linguistics": "NAACL",
    "naacl": "NAACL",
    "acl": "ACL",
    "computer vision and pattern recognition": "CVPR",
    "cvpr": "CVPR",
    "knowledge discovery and data mining": "KDD",
}


def normalize_title(s: str) -> str:
    s = _PUNCT.sub(" ", s.lower())
    return _WS.sub(" ", s).strip()


def token_set(s: str) -> Set[str]:
    return set(normalize_title(s).split())


def title_overlap(canonical_title: str, cited_query: str) -> float:
    """Fraction of canonical-title tokens present in the cited text. Robust to the
    cited string also containing authors/venue/year noise."""
    ct = token_set(canonical_title)
    if len(ct) < 3:
        return 0.0
    cq = token_set(cited_query)
    return len(ct & cq) / len(ct)


def name_words(name: str) -> Set[str]:
    """Alphabetic name tokens of length>1 (drops initials like 'S', 'M')."""
    out = set()
    for tok in re.split(r"[\s.,]+", name.lower()):
        tok = _PUNCT.sub("", tok)
        if len(tok) > 1 and tok != "al":  # 'et al'
            out.add(tok)
    return out


def first_author_mismatch(cited_first: str, canonical_first: str) -> bool:
    """True only when both names yield non-empty word sets AND they are disjoint."""
    a, b = name_words(cited_first), name_words(canonical_first)
    if not a or not b:
        return False
    return a.isdisjoint(b)


def venue_key(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    norm = normalize_title(s)
    for pattern in sorted(VENUE_ALIASES, key=len, reverse=True):
        if pattern in norm:
            return VENUE_ALIASES[pattern]
    return None


def venue_conflicts(cited: Optional[str], authoritative: Optional[str]) -> bool:
    """Strict, asymmetric venue conflict for exact-identifier (DOI) checks.

    Fires when the *cited* venue maps to a recognized conference/journal key
    (e.g. AAAI, ACL) but the *authoritative* venue neither maps to that same key
    nor literally contains that key as a token. This catches DOI↔venue lies such
    as 'cited AAAI but the DOI is actually an IEEE Access / IET paper', which the
    lossy alias-only comparison (which needs BOTH sides recognized) misses.
    """
    ck = venue_key(cited)
    if not ck:
        return False
    ak = venue_key(authoritative)
    if ak == ck:
        return False
    auth_tokens = token_set(authoritative or "")
    if ck.lower() in auth_tokens:
        return False
    return True


__all__ = [
    "normalize_title", "token_set", "title_overlap",
    "name_words", "first_author_mismatch", "venue_key", "venue_conflicts",
    "VENUE_ALIASES",
]
