from src.parsers.rss_journals import (
    _fetch_crossref_journal,
    _crossref_item_to_paper,
    _fmt_crossref_date,
    _merge_papers_by_id,
)


def test_fmt_crossref_date_accepts_year_month_only():
    assert _fmt_crossref_date([2026, 7]) == "2026-07-01"
    assert _fmt_crossref_date([2026]) == "2026-01-01"
    assert _fmt_crossref_date([2026, 7, 8]) == "2026-07-08"


def test_crossref_item_prefers_print_issue_date_for_sage():
    item = {
        "DOI": "10.1177/00222429251396114",
        "title": ["AdGazer: Improving Contextual Advertising with Theory-Informed Machine Learning"],
        "author": [{"given": "Jianping", "family": "Ye"}],
        "published-print": {"date-parts": [[2026, 7]]},
        "published-online": {"date-parts": [[2026, 3, 29]]},
        "volume": "90",
        "issue": "4",
        "page": "122-144",
    }

    paper = _crossref_item_to_paper(item, "JM")

    assert paper is not None
    assert paper["id"] == "doi:10.1177/00222429251396114"
    assert paper["online_date"] == "2026-07-01"
    assert paper["coverdate"] == "2026-07-01"
    assert paper["volume"] == "90"
    assert paper["issue"] == "4"
    assert paper["startpage"] == "122"
    assert paper["endpage"] == "144"


def test_merge_papers_by_id_preserves_primary_metadata():
    primary = [
        {
            "id": "doi:10.test/one",
            "title": "RSS title",
            "source": "rss",
        }
    ]
    supplement = [
        {
            "id": "doi:10.test/one",
            "title": "Crossref title",
            "source": "crossref",
        },
        {
            "id": "doi:10.test/two",
            "title": "New Crossref title",
            "source": "crossref",
        },
    ]

    merged = _merge_papers_by_id(primary, supplement)

    assert [p["id"] for p in merged] == ["doi:10.test/one", "doi:10.test/two"]
    assert merged[0]["title"] == "RSS title"


def test_fetch_crossref_journal_queries_print_and_online_dates(monkeypatch):
    requested_urls = []

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "message": {
                    "items": [
                        {
                            "DOI": "10.1177/00222429251396114",
                            "title": [
                                "AdGazer: Improving Contextual Advertising with Theory-Informed Machine Learning"
                            ],
                            "published-print": {"date-parts": [[2026, 7]]},
                            "published-online": {"date-parts": [[2026, 3, 29]]},
                        }
                    ]
                }
            }

    def fake_get(url, timeout):
        requested_urls.append(url)
        return FakeResponse()

    import requests

    monkeypatch.setattr("src.parsers.rss_journals._crossref_fetch_from", lambda: "2026-06-01")
    monkeypatch.setattr(requests, "get", fake_get)

    papers = _fetch_crossref_journal("JM", max_entries=80)

    assert len(papers) == 1
    assert papers[0]["online_date"] == "2026-07-01"
    assert any("from-print-pub-date:2026-06-01" in url for url in requested_urls)
    assert any("from-online-pub-date:2026-06-01" in url for url in requested_urls)
    assert all("from-pub-date" not in url for url in requested_urls)
