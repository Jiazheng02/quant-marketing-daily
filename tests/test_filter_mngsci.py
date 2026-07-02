"""
MngSci 关键词过滤测试。
"""

from src.filter_mngsci import filter_mngsci, _keyword_score


def test_marketing_paper_kept():
    """营销论文应被保留。"""
    papers = [
        {
            "id": "test:1",
            "journal": "MngSci",
            "title": "The Effect of Digital Advertising on Consumer Purchase Behavior",
            "abstract": "We use a field experiment to measure the causal effect of targeted digital advertising on consumer purchase decisions across multiple retail channels.",
            "needs_filter": True,
        }
    ]
    result = filter_mngsci(papers)
    assert len(result) == 1, f"Expected 1, got {len(result)}"


def test_finance_paper_dropped():
    """金融论文应被丢弃。"""
    papers = [
        {
            "id": "test:2",
            "journal": "MngSci",
            "title": "Portfolio Optimization Under Stochastic Volatility",
            "abstract": "We develop a new approach to portfolio optimization when asset returns exhibit stochastic volatility and fat tails.",
            "needs_filter": True,
        }
    ]
    result = filter_mngsci(papers)
    assert len(result) == 0, f"Expected 0, got {len(result)}"


def test_ambiguous_dropped_without_accepted_by():
    """无 accepted-by 数据且关键词分 < 2 → 丢弃。"""
    papers = [
        {
            "id": "test:3",
            "journal": "MngSci",
            "title": "Platform Design and Supply Chain Coordination",
            "abstract": "We study how platform design choices affect coordination in supply chains.",
            "needs_filter": True,
        }
    ]
    result = filter_mngsci(papers)
    assert len(result) == 0, f"Expected 0, got {len(result)}"


def test_accepted_by_marketing_kept():
    """accepted-by 含 'marketing' → 直接保留。"""
    papers = [
        {
            "id": "test:6",
            "journal": "MngSci",
            "title": "Information Design of Online Platforms",
            "abstract": "We study information design.",
            "mngsci_accepted_by": "This paper was accepted by Greg Shaffer, marketing.",
            "needs_filter": True,
        }
    ]
    result = filter_mngsci(papers)
    assert len(result) == 1, f"Expected 1, got {len(result)}"


def test_accepted_by_finance_dropped():
    """accepted-by 含 'finance' → 直接丢弃。"""
    papers = [
        {
            "id": "test:7",
            "journal": "MngSci",
            "title": "Hedge Fund Strategies",
            "abstract": "We study hedge funds.",
            "mngsci_accepted_by": "This paper was accepted by John Smith, finance.",
            "needs_filter": True,
        }
    ]
    result = filter_mngsci(papers)
    assert len(result) == 0, f"Expected 0, got {len(result)}"


if __name__ == "__main__":
    test_marketing_paper_kept()
    test_finance_paper_dropped()
    test_ambiguous_dropped_without_accepted_by()
    test_accepted_by_marketing_kept()
    test_accepted_by_finance_dropped()
    print("All MngSci filter tests passed!")
