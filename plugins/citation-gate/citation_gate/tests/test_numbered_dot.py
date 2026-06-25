"""Markdown ordered-list citations: '1. Authors (YYYY). Title. *Venue*.'

Two production gaps this guards against (found on /home/juli/CAE-QA/literature.md,
a 36-ref review whose bibliography uses '1.'/'2.' numbering, NOT '[1]'/'[2]'):
  (a) the numbered-entry regex only matched '[N]' → a '1.'-style bibliography
      parsed to ZERO citations (a silent false PASS);
  (b) in this format the *italic* span is the VENUE, not the title, so the old
      'italic = title' rule set title='Springer' → query='Springer' → the reverse
      lookup searched for the publisher instead of the paper.
"""
from citation_gate.parse import extract_citations


_DOC = """## 参考文献

1. Awijen, H., et al. (2025). Forecasting oil price in times of crisis: A new evidence from machine learning versus deep learning models.

2. Chen, S.Y., Zhang, Q., et al. (2020). Review on the petroleum market in China: History, challenges and prospects. *Springer*.

3. Estrada, M.A.R., Park, D., Tahir, M., & Khan, A. (2020). Simulations of US-Iran war and its impact on global oil price behavior. *ScienceDirect*.
"""


def test_dot_numbered_entries_all_extracted():
    cites = extract_citations(_DOC, "md")
    assert [c.index for c in cites] == [1, 2, 3]


def test_dot_numbered_year_and_first_author():
    cites = extract_citations(_DOC, "md")
    by_idx = {c.index: c for c in cites}
    assert by_idx[2].year == 2020
    assert "chen" in by_idx[2].authors[0].lower()
    assert by_idx[3].year == 2020


def test_dot_numbered_title_is_the_paper_not_the_venue():
    # The whole point: title must be the real paper title (so the search query is
    # the paper), never the italic venue 'Springer'/'ScienceDirect'.
    cites = extract_citations(_DOC, "md")
    by_idx = {c.index: c for c in cites}
    assert "petroleum market" in (by_idx[2].title or "").lower()
    assert "springer" not in (by_idx[2].title or "").lower()
    # query drives the reverse lookup → must contain the paper title, not the venue
    assert "petroleum market" in by_idx[2].query.lower()
    assert by_idx[2].query.strip().lower() != "springer"


def test_dot_numbered_author_pairs_from_author_segment_only():
    # author_pairs must come from the pre-year author list, not leak title words.
    cites = extract_citations(_DOC, "md")
    by_idx = {c.index: c for c in cites}
    surnames = {s.lower() for s, _ in by_idx[3].author_pairs}
    assert "estrada" in surnames
    assert "park" in surnames


def test_plain_ordered_list_without_year_is_not_a_citation():
    # Guard against over-matching a generic '1./2.' instruction list as citations.
    doc = "## Steps\n\n1. Preheat the oven.\n\n2. Mix the flour and water.\n"
    assert extract_citations(doc, "md") == []


def test_bracket_numbered_format_still_works():
    # Regression: the existing '[N]' arXiv-style format must keep parsing.
    doc = ("[8] Ye, H., He, X. *Meta Context Engineering via Agentic Skill "
           "Evolution*. arXiv, 2026. https://arxiv.org/abs/2601.21557 "
           "(DOI: 10.48550/arXiv.2601.21557)\n")
    cites = extract_citations(doc, "md")
    assert len(cites) == 1
    assert cites[0].index == 8
    assert "meta context" in (cites[0].title or "").lower()
