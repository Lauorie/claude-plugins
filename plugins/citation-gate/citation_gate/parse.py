"""Extract citation entries from .bib / .md / .tex documents.

Prose entries are NOT fully field-segmented (formats vary wildly). We extract
just enough for a robust reverse lookup: the whole cleaned entry as the search
query, plus best-effort first-author / year / venue for field comparison.
"""
from __future__ import annotations

import logging
import re
from typing import Dict, List, Optional

from .models import Citation
from .normalize import venue_key

logger = logging.getLogger(__name__)

_WS = re.compile(r"\s+")
_YEAR = re.compile(r"\b(19[5-9]\d|20[0-3]\d)\b")
_DOI = re.compile(r"10\.\d{4,}/[^\s,}\]]+")
# 编号条目：[40] ... 直到下一个 [n] 或文末
_NUMBERED = re.compile(r"\[(\d+)\]\s*(.+?)(?=\n\s*\[\d+\]|\Z)", re.DOTALL)
_BIBITEM = re.compile(r"\\bibitem(?:\[[^\]]*\])?\{[^}]*\}\s*(.+?)(?=\\bibitem|\Z)", re.DOTALL)


def _clean(s: str) -> str:
    return _WS.sub(" ", s.replace("\n", " ")).strip().rstrip(".")


def _year_of(s: str) -> Optional[int]:
    m = _YEAR.search(s)
    return int(m.group(0)) if m else None


def _doi_of(s: str) -> Optional[str]:
    m = _DOI.search(s)
    return m.group(0).rstrip(".") if m else None


def _first_author(entry: str) -> str:
    """Leading author chunk = text before first comma (or ' and ')."""
    head = re.split(r",| and ", entry, maxsplit=1)[0]
    return _clean(head)


def _parse_prose(text: str) -> List[Citation]:
    out: List[Citation] = []
    matches = list(_NUMBERED.finditer(text))
    if matches:
        for m in matches:
            idx, body = int(m.group(1)), _clean(m.group(2))
            out.append(Citation(
                raw_text=body, index=idx, title=None,
                authors=(_first_author(body),),
                year=_year_of(body), venue=venue_key(body), pages=None,
                doi=_doi_of(body),
            ))
        return out
    for i, m in enumerate(_BIBITEM.finditer(text), start=1):
        body = _clean(m.group(1))
        out.append(Citation(
            raw_text=body, index=i, title=None,
            authors=(_first_author(body),),
            year=_year_of(body), venue=venue_key(body), pages=None,
            doi=_doi_of(body),
        ))
    return out


def _read_brace_value(text: str, pos: int) -> tuple[str, int]:
    """Read a brace-balanced value starting at pos (which must be '{').

    Returns (raw_value_without_outer_braces, end_pos_after_closing_brace).
    """
    assert text[pos] == "{"
    depth = 0
    start = pos + 1  # skip the opening brace
    i = pos
    while i < len(text):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[start:i], i + 1
        i += 1
    # unterminated — return what we have
    return text[start:], len(text)


def _read_quoted_value(text: str, pos: int) -> tuple[str, int]:
    """Read a double-quoted value starting at pos (which must be '"')."""
    assert text[pos] == '"'
    end = text.index('"', pos + 1)
    return text[pos + 1:end], end + 1


def _scan_bib_fields(body: str) -> Dict[str, str]:
    """Parse the field block after the citekey comma using a character scanner.

    Handles nested braces, one-liner and multi-line formats.
    Returns dict of lowercase_key -> cleaned value string.
    """
    fields: Dict[str, str] = {}
    i = 0
    n = len(body)
    while i < n:
        # Skip whitespace and commas between fields
        while i < n and body[i] in " \t\n\r,":
            i += 1
        if i >= n:
            break
        # Read field key: alphanumeric until '='
        key_start = i
        while i < n and body[i] not in "=}":
            i += 1
        if i >= n or body[i] == "}":
            break
        key = body[key_start:i].strip().lower()
        i += 1  # skip '='
        # Skip whitespace
        while i < n and body[i] in " \t\n\r":
            i += 1
        if i >= n:
            break
        # Read value
        if body[i] == "{":
            raw_val, i = _read_brace_value(body, i)
        elif body[i] == '"':
            raw_val, i = _read_quoted_value(body, i)
        else:
            # Bare token (e.g. year = 2020 without braces)
            val_start = i
            while i < n and body[i] not in ",}\n":
                i += 1
            raw_val = body[val_start:i].strip()
        # Strip inner braces and clean
        cleaned = _clean(raw_val.replace("{", "").replace("}", ""))
        if key:
            fields[key] = cleaned
    return fields


def _scan_bib_entries(text: str) -> List[Dict[str, str]]:
    """Find all @type{...} entries in text using brace-depth counting.

    Handles one-liners, nested braces, and multi-line entries.
    """
    entries = []
    i = 0
    n = len(text)
    while i < n:
        at = text.find("@", i)
        if at == -1:
            break
        # Find the entry type and opening brace
        brace = text.find("{", at)
        if brace == -1:
            break
        # Find the end of the entry by counting brace depth
        depth = 0
        j = brace
        while j < n:
            if text[j] == "{":
                depth += 1
            elif text[j] == "}":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        # Entry body: everything from opening brace+1 to closing brace
        entry_inner = text[brace + 1:j]
        # Split off the citekey (text before the first comma)
        comma = entry_inner.find(",")
        if comma == -1:
            i = j + 1
            continue
        # Field block starts after the citekey comma
        field_block = entry_inner[comma + 1:]
        fields = _scan_bib_fields(field_block)
        if fields:
            entries.append(fields)
        i = j + 1
    return entries


def _parse_bib(text: str) -> List[Citation]:
    out: List[Citation] = []
    for i, fields in enumerate(_scan_bib_entries(text), start=1):
        venue_raw = fields.get("booktitle") or fields.get("journal")
        authors_raw = fields.get("author", "")
        authors = tuple(a.strip() for a in authors_raw.split(" and ") if a.strip())
        year_str = fields.get("year", "")
        year = int(year_str) if year_str.isdigit() else None
        out.append(Citation(
            raw_text=fields.get("title", ""), index=i,
            title=fields.get("title") or None, authors=authors,
            year=year, venue=venue_key(venue_raw) or venue_raw,
            pages=fields.get("pages"), doi=fields.get("doi"),
        ))
    return out


def extract_citations(text: str, filetype: str) -> List[Citation]:
    if filetype == "bib":
        return _parse_bib(text)
    return _parse_prose(text)


__all__ = ["extract_citations"]
