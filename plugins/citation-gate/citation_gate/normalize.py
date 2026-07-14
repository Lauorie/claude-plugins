"""Text normalization, similarity, author/venue matching primitives."""
from __future__ import annotations

import html
import re
from typing import Optional, Set, Tuple

_PUNCT = re.compile(r"[^a-z0-9]+")
_WS = re.compile(r"\s+")
# CrossRef titles carry inline markup (Si<sub>3</sub>N<sub>4</sub>, <i>…</i>)
# and XML entities (&apos;) — strip/unescape them before comparing, or every
# chemical-formula title "mismatches" its own authoritative record.
_TAG = re.compile(r"<[^>]+>")

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
    s = _TAG.sub("", html.unescape(s))
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


# "Surname, I." author tokens (surname may be multi-word: 'Al Nazi, Z.').
_AUTHOR_PAIR = re.compile(
    r"([A-Z][A-Za-zÀ-ɏ'\-]+(?:\s+[A-Z][A-Za-zÀ-ɏ'\-]+)*)"
    r",\s*([A-Za-z])\."
)
# "I. Surname" tokens ('C. Zarfl', 'A.J. Steckl', 'M. A. Fraga', dotless 'K Wasa').
# Anchored to segment start / list separators so a dotless single capital can
# only be an initial, never a word from leaked title text.
_AUTHOR_PAIR_IF = re.compile(
    r"(?:^|[,;&]|\band\b)\s*"
    r"([A-Z](?:[.\s-]+[A-Z])*\.?)\s+"
    r"([A-Z][A-Za-zÀ-ɏ'\-]+(?:\s+[A-Z][A-Za-zÀ-ɏ'\-]+)*)"
)


def parse_author_pairs(segment: str) -> Tuple[Tuple[str, str], ...]:
    """Extract ('Surname', 'I') tuples from an author segment.

    Two comma-list styles exist and are ambiguous to a single regex:
    surname-first 'Zarfl, C., Schmid, P.' and initial-first 'C. Zarfl,
    P. Schmid'. On the WRONG style each pattern still half-matches — the
    surname-first pattern reads initial-first lists as (surname, NEXT author's
    initial), off by one — so parse with both and keep whichever interpretation
    explains more of the segment. Ties go to initial-first: in mixed lists
    ('Yongguo Sun, F. Teng, …') the surname-first reading glues a full name to
    its neighbour's initial, while the initial-first reading is only ever
    incomplete, never wrong."""
    sf = tuple((m.group(1).strip(), m.group(2).upper())
               for m in _AUTHOR_PAIR.finditer(segment))
    if_ = tuple((m.group(2).strip(), re.sub(r"[^A-Za-z]", "", m.group(1))[:1].upper())
                for m in _AUTHOR_PAIR_IF.finditer(segment))
    return if_ if len(if_) >= len(sf) else sf


def _surname_key(name: str) -> str:
    """Last alphabetic token of a name, lowercased, punctuation stripped."""
    toks = [t for t in re.split(r"\s+", name.strip()) if t and not t.isdigit()]
    return _PUNCT.sub("", toks[-1].lower()) if toks else ""


def _given_initial(name: str) -> str:
    """First initial of a 'Given Family' authoritative name ('' if unparseable)."""
    toks = [t for t in re.split(r"\s+", name.strip()) if t and not t.isdigit()]
    if not toks:
        return ""
    letters = re.sub(r"[^a-zA-Z]", "", toks[0])
    return letters[0].upper() if letters else ""


def author_conflict(cited_pairs: Tuple[Tuple[str, str], ...],
                    authoritative: Tuple[str, ...]) -> bool:
    """High-precision co-author fabrication signal.

    Fires when a cited author's surname *matches* an authoritative author's
    surname but the cited first initial *differs* from every authoritative
    author sharing that surname (e.g. cited 'Wang, H.' but the real co-author is
    'Jiahao Wang'). Truncated author lists never trigger it — a cited surname
    absent from the record is ignored — so it only flags positive contradictions.
    """
    if not cited_pairs or not authoritative:
        return False
    fam: dict = {}
    for nm in authoritative:
        key = _surname_key(nm)
        init = _given_initial(nm)
        if key and init:
            fam.setdefault(key, set()).add(init)
    for surname, initial in cited_pairs:
        key = _surname_key(surname)
        if key and key in fam and fam[key] and initial.upper() not in fam[key]:
            return True
    return False


def extra_authors(cited_pairs: Tuple[Tuple[str, str], ...],
                  authoritative: Tuple[str, ...]) -> bool:
    """True when a cited author's surname is absent from the authoritative author
    list — i.e. a fabricated/inserted co-author. Truncation is fine (a real
    author simply omitted never triggers it); use only when a DOI pins the exact
    paper so the authoritative list is known-complete."""
    if not cited_pairs or not authoritative:
        return False
    real = {k for k in (_surname_key(nm) for nm in authoritative) if k}
    if not real:
        return False
    for surname, _ in cited_pairs:
        key = _surname_key(surname)
        if key and key not in real:
            return True
    return False


_PARENS = re.compile(r"\([^)]*\)")
_TITLE_STOP = {
    "a", "an", "the", "of", "for", "and", "with", "on", "in", "to", "from",
    "using", "via", "based", "by", "as", "at", "or",
}


def _title_core(s: str) -> str:
    """Normalized title with parenthetical acronyms (e.g. '(ColBERT-PRF)') dropped."""
    return normalize_title(_PARENS.sub(" ", s or ""))


def title_mismatch(cited: str, authoritative: str) -> bool:
    """True when the cited title contradicts the authoritative (DOI-pinned) title.

    Tolerant of benign differences — case, hyphenation, a trailing '(ACRONYM)',
    or dropping a post-colon subtitle. Fires only on a *substantive* divergence
    (≥2 content-word symmetric difference), e.g. words dropped from / added to the
    middle of the title. Use only when a DOI has pinned the exact paper.
    """
    if not cited or not authoritative:
        return False
    c = _title_core(cited)
    a = _title_core(authoritative)
    if not c or not a or c == a:
        return False
    # Records sometimes space out chemical formulas ('Al 2 O 3' vs 'Al2O3');
    # identical up to whitespace is not a divergence.
    if c.replace(" ", "") == a.replace(" ", ""):
        return False
    # allow dropping a post-colon subtitle: cited == authoritative main title
    a_main = _title_core(authoritative.split(":", 1)[0])
    if c == a_main:
        return False
    cset, aset = set(c.split()), set(a.split())
    extra = {t for t in (cset - aset) if t not in _TITLE_STOP and len(t) > 2}
    missing = {t for t in (aset - cset) if t not in _TITLE_STOP and len(t) > 2}
    # Any content word in the citation that is NOT in the authoritative title is
    # a strong fabrication signal (inserted/changed word) → flag even one. A pure
    # drop (cited is a subset) is tolerated up to one word (abbreviation), flagged
    # only when ≥2 substantive words are missing.
    return len(extra) >= 1 or len(missing) >= 2


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
    "parse_author_pairs", "author_conflict", "extra_authors", "title_mismatch",
    "VENUE_ALIASES",
]
