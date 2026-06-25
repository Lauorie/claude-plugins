from citation_gate.models import Citation, CanonicalRecord, Verdict
from citation_gate.match import best_match, grade

REAL = CanonicalRecord(
    title="Co-training Embeddings of Knowledge Graphs and Entity Descriptions for Cross-lingual Entity Alignment",
    authors=("Muhao Chen", "Yingtao Tian", "Kai-Wei Chang"),
    year=2018, venue="IJCAI", pages="3998-4004",
    doi="10.24963/ijcai.2018/556", source="dblp",
)


def _fake_cited():
    return Citation(
        raw_text="Pei S M, Yu L, Yu G, et al Co-training embeddings of knowledge graphs "
                 "and entity descriptions for cross-lingual entity alignment. AAAI. 2020. 3025-3032.",
        index=40, title=None, authors=("Pei S M",), year=2020, venue="AAAI",
    )


def test_best_match_picks_real_paper():
    assert best_match(_fake_cited(), [REAL]) is REAL


def test_best_match_none_when_below_threshold():
    unrelated = CanonicalRecord("Deep Residual Learning for Image Recognition",
                                ("Kaiming He",), 2016, "CVPR", None, None, "dblp")
    assert best_match(_fake_cited(), [unrelated]) is None


def test_grade_hard_fail_on_fabricated_metadata():
    res = grade(_fake_cited(), REAL, any_backend_ok=True)
    assert res.verdict is Verdict.HARD_FAIL
    assert "authors" in res.mismatched_fields
    assert "year" in res.mismatched_fields


def test_grade_pass_on_correct_citation():
    good = Citation(raw_text="Muhao Chen, et al. Co-training embeddings of knowledge graphs "
                    "and entity descriptions for cross-lingual entity alignment. IJCAI. 2018.",
                    index=6, title=None, authors=("Muhao Chen",), year=2018, venue="IJCAI")
    res = grade(good, REAL, any_backend_ok=True)
    assert res.verdict is Verdict.PASS


def test_grade_soft_warn_when_not_found():
    res = grade(_fake_cited(), None, any_backend_ok=True)
    assert res.verdict is Verdict.SOFT_WARN


def test_grade_skip_when_all_backends_down():
    res = grade(_fake_cited(), None, any_backend_ok=False)
    assert res.verdict is Verdict.SKIP


def test_grade_venue_only_mismatch_is_soft_warn():
    cited = Citation(raw_text="Muhao Chen. Co-training embeddings of knowledge graphs and "
                     "entity descriptions for cross-lingual entity alignment. AAAI. 2018.",
                     index=6, title=None, authors=("Muhao Chen",), year=2018, venue="AAAI")
    res = grade(cited, REAL, any_backend_ok=True)
    assert res.verdict is Verdict.SOFT_WARN
    assert "venue" in res.mismatched_fields


def test_grade_high_confidence_fabrication_stays_hard_fail():
    res = grade(_fake_cited(), REAL, any_backend_ok=True)
    assert res.verdict is Verdict.HARD_FAIL


def test_grade_low_confidence_mismatch_is_soft_warn():
    weak = Citation(
        raw_text="Smith J. Co-training embeddings of graphs for a totally different unrelated survey. NeurIPS. 2031.",
        index=7, title=None, authors=("Smith J",), year=2031, venue="NeurIPS",
    )
    res = grade(weak, REAL, any_backend_ok=True)
    assert res.verdict is Verdict.SOFT_WARN


def test_best_match_empty_candidates_returns_none():
    assert best_match(_fake_cited(), []) is None


def test_grade_no_authors_no_false_hard_fail():
    # citation with NO parsed authors must not HARD_FAIL on author grounds
    c = Citation(raw_text=_fake_cited().raw_text, index=1, title=None, authors=(), year=2018, venue="IJCAI")
    res = grade(c, REAL, any_backend_ok=True)
    assert res.verdict in (Verdict.PASS, Verdict.SOFT_WARN)  # never HARD_FAIL from empty authors
