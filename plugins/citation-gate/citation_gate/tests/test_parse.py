from citation_gate.parse import extract_citations


def test_parse_numbered_prose_entry():
    text = (
        "References\n"
        "[40] Pei S M, Yu L, Yu G, et al Co-training embeddings of knowledge graphs "
        "and entity descriptions for cross-lingual entity alignment. In: Proc of the "
        "34th AAAI Conference on Artificial Intelligence. New York, 2020. 3025-3032.\n"
    )
    cits = extract_citations(text, "md")
    assert len(cits) == 1
    c = cits[0]
    assert c.index == 40
    assert c.authors[0].startswith("Pei")
    assert c.year == 2020
    assert c.venue == "AAAI"
    assert "co-training embeddings" in c.query.lower()


def test_parse_two_numbered_entries():
    text = (
        "[1] Vaswani A, et al. Attention is all you need. NeurIPS, 2017.\n"
        "[2] Devlin J, et al. BERT. NAACL, 2019.\n"
    )
    cits = extract_citations(text, "md")
    assert [c.index for c in cits] == [1, 2]
    assert cits[0].year == 2017
    assert cits[1].year == 2019


def test_parse_bibtex_entry():
    text = (
        "@inproceedings{chen2018cotrain,\n"
        "  title = {Co-training Embeddings of Knowledge Graphs and Entity Descriptions},\n"
        "  author = {Muhao Chen and Yingtao Tian and Kai-Wei Chang},\n"
        "  booktitle = {Proceedings of IJCAI},\n"
        "  year = {2018},\n"
        "  pages = {3998--4004},\n"
        "  doi = {10.24963/ijcai.2018/556}\n"
        "}\n"
    )
    cits = extract_citations(text, "bib")
    assert len(cits) == 1
    c = cits[0]
    assert c.title.startswith("Co-training Embeddings")
    assert c.authors[0] == "Muhao Chen"
    assert c.year == 2018
    assert c.venue == "IJCAI"
    assert c.doi == "10.24963/ijcai.2018/556"


def test_parse_bibitem():
    text = r"\bibitem{x} J. Doe and A. Smith. A great paper. In ICML, 2021."
    cits = extract_citations(text, "tex")
    assert len(cits) == 1
    assert cits[0].year == 2021
    assert cits[0].venue == "ICML"


def test_parse_no_citations_returns_empty():
    assert extract_citations("just prose, nothing to cite here.", "md") == []


def test_parse_bib_one_liner_entry():
    text = '@article{x, title={Foo Bar Baz Qux}, author={Jane Roe}, year={2020}, journal={Nature}}'
    cits = extract_citations(text, "bib")
    assert len(cits) == 1
    assert cits[0].title == "Foo Bar Baz Qux"
    assert cits[0].authors[0] == "Jane Roe"
    assert cits[0].year == 2020


def test_parse_bib_nested_braces_in_title():
    text = ('@inproceedings{y,\n'
            '  title = {{BERT}: Pre-training of Deep Bidirectional Transformers},\n'
            '  author = {Jacob Devlin and Ming-Wei Chang},\n'
            '  booktitle = {NAACL},\n'
            '  year = {2019}\n'
            '}')
    cits = extract_citations(text, "bib")
    assert len(cits) == 1
    assert "BERT" in cits[0].title and "Pre-training" in cits[0].title
    assert cits[0].authors[0] == "Jacob Devlin"
    assert cits[0].venue == "NAACL"
    assert cits[0].year == 2019


def test_parse_bib_multi_field_one_line():
    text = '@inproceedings{z, title={Some Title Here}, year={2018}, booktitle={IJCAI}}'
    cits = extract_citations(text, "bib")
    assert cits[0].title == "Some Title Here"
    assert cits[0].year == 2018
    assert cits[0].venue == "IJCAI"
