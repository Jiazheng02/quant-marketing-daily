"""
INFORMS / Marketing Science abstract scraping tests.
"""

from src.scraper.informs_page import extract_informs_abstract_from_html
from src.scraper import informs


FULL_ABSTRACT = (
    "In recent years, an increasing number of firms have joined coalition loyalty "
    "programs, where they collaborate with other firms in their loyalty program "
    "initiatives. However, these programs remain less studied compared with "
    "proprietary loyalty programs offered by individual firms. "
    "We analyze the design of coalition loyalty programs and show that they can "
    "significantly expand the range of market conditions under which offering "
    "reward programs is desirable. Our research also reveals the critical role "
    "of market composition in the effectiveness of these programs."
)


def test_extract_informs_abstract_from_heading_html():
    html = f"""
    <html>
      <body>
        <h2>Abstract</h2>
        <p>{FULL_ABSTRACT}</p>
        <p>History: Anthony Dukes served as the senior editor.</p>
        <p>Funding: This should not be part of the abstract.</p>
      </body>
    </html>
    """

    result = extract_informs_abstract_from_html(html, min_length=200)

    assert result == FULL_ABSTRACT
    assert "History:" not in result
    assert "Funding:" not in result


def test_extract_informs_abstract_from_plain_page_text():
    page_text = f"""
    Article title

    Abstract
    {FULL_ABSTRACT}
    History: Anthony Dukes served as the senior editor.
    Funding: This should not be part of the abstract.
    Back to Top
    """

    result = extract_informs_abstract_from_html(page_text, min_length=200)

    assert result == FULL_ABSTRACT
    assert "Back to Top" not in result


def test_mktsci_short_crossref_uses_scrapling_full_fetch(monkeypatch):
    saved = {}
    short = "This paper examines coalition loyalty programs and price discrimination."

    monkeypatch.setattr(informs, "load_mktsci_cache", lambda: {})
    monkeypatch.setattr(informs, "_crossref_fetch", lambda doi: {"abstract": short, "accepted_by": None})
    monkeypatch.setattr(informs, "fetch_full_abstract_with_scrapling", lambda doi, min_length: FULL_ABSTRACT)
    monkeypatch.setattr(informs, "save_to_mktsci_cache", lambda doi, abstract: saved.update({doi: abstract}))
    monkeypatch.setattr(informs, "save_pending_mktsci", lambda doi: saved.update({"pending": doi}))

    result = informs.scrape_abstract("10.1287/mksc.2024.1138", journal="MktSci")

    assert result == (FULL_ABSTRACT, None)
    assert saved["10.1287/mksc.2024.1138"] == FULL_ABSTRACT
    assert "pending" not in saved


def test_mktsci_short_crossref_falls_back_to_pending(monkeypatch):
    saved = {}
    short = "This paper examines coalition loyalty programs and price discrimination."

    monkeypatch.setattr(informs, "load_mktsci_cache", lambda: {})
    monkeypatch.setattr(informs, "_crossref_fetch", lambda doi: {"abstract": short, "accepted_by": None})
    monkeypatch.setattr(informs, "fetch_full_abstract_with_scrapling", lambda doi, min_length: None)
    monkeypatch.setattr(informs, "save_pending_mktsci", lambda doi: saved.update({"pending": doi}))

    result = informs.scrape_abstract("10.1287/mksc.2024.1138", journal="MktSci")

    assert result == (short, None)
    assert saved["pending"] == "10.1287/mksc.2024.1138"
