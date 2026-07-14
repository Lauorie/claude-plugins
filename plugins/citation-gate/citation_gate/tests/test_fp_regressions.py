"""Regression tests for four false-positive bugs found auditing a real
116-reference survey (2026-07-14). Each bug made the gate flag CORRECT
citations as fabricated:

1. DOI regex truncated old-style Elsevier DOIs at '(' → "DOI 与权威记录不符".
2. parse_author_pairs mis-paired 'I. Surname' comma lists (surname matched with
   the NEXT author's initial) → "authors 疑似编造" on verbatim-correct lists.
3. CrossRef titles carry HTML markup (Si<sub>3</sub>N<sub>4</sub>) that
   normalize_title kept → title_mismatch on chemical formulas.
4. resolve_doi only queried CrossRef; DataCite DOIs (theses/repositories)
   never resolved → fell back to title search → matched a wrong record.
"""
from citation_gate import backends
from citation_gate import http
from citation_gate.normalize import (
    author_conflict,
    normalize_title,
    parse_author_pairs,
    title_mismatch,
)
from citation_gate.parse import extract_citations


# ---------------------------------------------------------------------------
# Bug 1: parenthesised DOIs must be captured whole
# ---------------------------------------------------------------------------

def test_doi_with_parentheses_extracted_whole():
    md = ("[13] Takeshi Nagai, Kazushi Yamamoto. *SiC thin-film thermistor*. "
          "Thin Solid Films, 1982. DOI: 10.1016/0040-6090(85)90244-5")
    (c,) = extract_citations(md, "md")
    assert c.doi == "10.1016/0040-6090(85)90244-5"


def test_doi_with_parentheses_and_trailing_period():
    md = ("[34] Jih-Fen Lei, Herbert A. Will. *Thin-film thermocouples*. "
          "Sensors and Actuators A, 1998. DOI: 10.1016/s0924-4247(97)01683-x.")
    (c,) = extract_citations(md, "md")
    assert c.doi == "10.1016/s0924-4247(97)01683-x"


def test_doi_wrapped_in_parentheses_still_trimmed():
    # A DOI *inside* parentheses must not swallow the closing paren.
    md = "[1] A. Author. *Some Title*. Venue, 2020. (DOI: 10.1038/s41586-020-2649-2)"
    (c,) = extract_citations(md, "md")
    assert c.doi == "10.1038/s41586-020-2649-2"


# ---------------------------------------------------------------------------
# Bug 2: 'I. Surname' author lists must not be mis-paired
# ---------------------------------------------------------------------------

def test_initial_first_authors_not_mispaired():
    # Audit case [95]: cited list is verbatim-identical to the CrossRef record,
    # yet the old parser produced (('Zarfl','P'), ('Schmid','G'), ('Balogh','U')).
    pairs = parse_author_pairs("C. Zarfl, P. Schmid, G. Balogh, U. Schmid. ")
    assert pairs == (("Zarfl", "C"), ("Schmid", "P"), ("Balogh", "G"), ("Schmid", "U"))


def test_initial_first_multi_initials():
    pairs = parse_author_pairs("Lin Cheng, A.J. Steckl, J. Scofield. ")
    assert ("Steckl", "A") in pairs
    assert ("Scofield", "J") in pairs
    assert ("Cheng", "A") not in pairs  # the old off-by-one mispair


def test_dotless_initials_supported():
    # Audit case [10]: 'K Wasa' style (no periods).
    pairs = parse_author_pairs("K Wasa, T Tohda, Y Kasahara, S Hayakawa. ")
    assert pairs == (("Wasa", "K"), ("Tohda", "T"), ("Kasahara", "Y"), ("Hayakawa", "S"))


def test_mixed_full_and_initial_first_names():
    # Audit case [36]: 'Yongguo Sun' is a full name; only 'F. Teng' abbreviates.
    # The old parser produced ('Yongguo Sun', 'F') — Teng's initial glued onto
    # the previous author — which then fired author_conflict against the
    # authoritative 'Yongguo Sun'.
    pairs = parse_author_pairs("Yongguo Sun, F. Teng, Shuai Guo, Jie Chen. ")
    assert ("Teng", "F") in pairs
    assert ("Yongguo Sun", "F") not in pairs


def test_surname_first_style_unchanged():
    seg = "Ma, X., Gong, Y., He, P., Zhao, H., & Duan, N. "
    assert parse_author_pairs(seg) == (
        ("Ma", "X"), ("Gong", "Y"), ("He", "P"), ("Zhao", "H"), ("Duan", "N"))


def test_verbatim_identical_list_no_conflict_end_to_end():
    md = ("[95] C. Zarfl, P. Schmid, G. Balogh, U. Schmid. *Electro-mechanical "
          "properties and oxidation behaviour of TiAlNxOy thin films at high "
          "temperatures*. Sensors and Actuators A Physical, 2015. "
          "DOI: 10.1016/j.sna.2015.02.026")
    (c,) = extract_citations(md, "md")
    canonical = ("C. Zarfl", "P. Schmid", "G. Balogh", "U. Schmid")
    assert author_conflict(c.author_pairs, canonical) is False


# ---------------------------------------------------------------------------
# Bug 3: HTML markup / entities in authoritative titles
# ---------------------------------------------------------------------------

def test_normalize_title_strips_html_tags():
    assert normalize_title("Si<sub>3</sub>N<sub>4</sub>") == "si3n4"


def test_title_mismatch_tolerates_subscript_markup():
    cited = "A Novel High-Temperature Pressure Sensor Based on Graphene Coated by Si3N4"
    auth = ("A Novel High-Temperature Pressure Sensor Based on Graphene Coated by "
            "Si<sub>3</sub>N<sub>4</sub>")
    assert title_mismatch(cited, auth) is False


def test_title_mismatch_tolerates_spaced_formula():
    # Audit case [103]: CrossRef spaces the formula out ('Al 2 O 3').
    cited = ("Effect of Al2O3/Al bilayer protective coatings on the "
             "high-temperature stability of PdCr thin film strain gages")
    auth = ("Effect of Al 2 O 3 /Al bilayer protective coatings on the "
            "high-temperature stability of PdCr thin film strain gages")
    assert title_mismatch(cited, auth) is False


def test_normalize_title_unescapes_entities():
    assert normalize_title("Attention Is All You Need But You Don&apos;t") \
        == "attention is all you need but you don t"


def test_title_mismatch_still_fires_on_real_divergence():
    assert title_mismatch(
        "Robust thin film strain gauges for cryogenic sensing",
        "Robust thin film strain gauges for high temperature sensing applications",
    ) is True


# ---------------------------------------------------------------------------
# Bug 4: DataCite fallback for DOIs CrossRef does not know
# ---------------------------------------------------------------------------

_DATACITE_PAYLOAD = {
    "data": {
        "attributes": {
            "doi": "10.34726/hss.2019.41084",
            "titles": [{"title": "Robust thin film strain gauges for high "
                                 "temperature sensing applications"}],
            "creators": [{"name": "Zarfl, Christof",
                          "givenName": "Christof", "familyName": "Zarfl"}],
            "publicationYear": 2019,
            "publisher": "TU Wien",
            "container": {},
        }
    }
}


def test_resolve_doi_falls_back_to_datacite(monkeypatch):
    def fake_get_json(url, params, timeout=6):
        if "crossref" in url:
            raise http.HttpError("HTTP Error 404: Not Found")
        assert "datacite" in url
        return _DATACITE_PAYLOAD

    monkeypatch.setattr(backends.http, "get_json", fake_get_json)
    rec = backends.resolve_doi("10.34726/hss.2019.41084")
    assert rec is not None
    assert rec.title.startswith("Robust thin film strain gauges")
    assert rec.authors == ("Christof Zarfl",)
    assert rec.year == 2019
    assert rec.source == "datacite"


def test_resolve_doi_fails_open_when_both_sources_down(monkeypatch):
    def fake_get_json(url, params, timeout=6):
        raise http.HttpError("HTTP Error 500")

    monkeypatch.setattr(backends.http, "get_json", fake_get_json)
    assert backends.resolve_doi("10.34726/hss.2019.41084") is None


# ---------------------------------------------------------------------------
# Bug 5: pedagogical numbered lists / fenced diagrams parsed as references
# (2026-07-14, auditing a teaching blog whose core is a fenced 5-step ASCII
# diagram: step "5." swallowed all following prose up to EOF, which contained
# a year and an arXiv link — so the no-year ordered-list guard never fired
# and the gate HARD_FAILed on a phantom "citation").
# ---------------------------------------------------------------------------

_BLOG_LIKE = """# 300 行代码跑通一个 Coding Agent

先把图印在脑子里，后面所有代码都在实现它：

```
  1. 把对话 + 工具发给 LLM
  2. LLM 回一条 assistant 消息
  3. 它没要求调工具？ ──是──▶ 结束，返回最终回复
  4. 逐个执行工具，把结果作为 "tool" 消息追加
  5. ────────────────────────────────────────────┘（回到第 1 步）
```

这个范式出自论文《ReAct: Synergizing Reasoning and Acting in Language Models》
（Yao et al., 2022，[arXiv:2210.03629](https://arxiv.org/abs/2210.03629)）。
"""


def test_fenced_numbered_diagram_is_not_a_reference_list():
    assert extract_citations(_BLOG_LIKE, "md") == []


def test_numbered_entry_body_stops_at_blank_line():
    # Prose AFTER the reference list must not be swallowed into entry [1] —
    # here the following paragraph contains an arXiv URL that would otherwise
    # be mis-attributed to the entry as its DOI.
    md = (
        "[1] Shunyu Yao, Jeffrey Zhao. *Some Made-Up Survey Title*. ICLR, 2023.\n"
        "\n"
        "正文段落：另一篇论文的链接 https://arxiv.org/abs/2210.03629 与上面的条目无关。\n"
    )
    (c,) = extract_citations(md, "md")
    assert c.title == "Some Made-Up Survey Title"
    assert c.doi is None


def test_wrapped_numbered_entry_without_blank_line_stays_whole():
    # Characterization guard: a hard-wrapped entry (no blank line) must still
    # parse as ONE citation with fields drawn from both physical lines.
    md = (
        "[7] Ashish Vaswani, Noam Shazeer. *Attention Is All You Need*.\n"
        "    NeurIPS, 2017. DOI: 10.48550/arXiv.1706.03762\n"
    )
    (c,) = extract_citations(md, "md")
    assert c.title == "Attention Is All You Need"
    assert c.year == 2017
    assert c.doi == "10.48550/arXiv.1706.03762"
