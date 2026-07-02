"""
日期过滤边界测试。
"""

from unittest.mock import patch
from datetime import datetime

from src.config import TZ
from src.dedup import compute_fetch_from, filter_seen_and_date


def test_window_first_7_days():
    """当月前 7 天 → 从上月 1 号开始。"""
    with patch("src.dedup.datetime") as mock_dt:
        mock_dt.now.return_value = datetime(2026, 7, 1, tzinfo=TZ)
        result = compute_fetch_from()
        assert result == "2026-06-01", f"Expected 2026-06-01, got {result}"


def test_window_day_7():
    """第 7 天仍在月初窗口。"""
    with patch("src.dedup.datetime") as mock_dt:
        mock_dt.now.return_value = datetime(2026, 7, 7, tzinfo=TZ)
        result = compute_fetch_from()
        assert result == "2026-06-01", f"Expected 2026-06-01, got {result}"


def test_window_day_8():
    """第 8 天切回 30 天窗口。"""
    with patch("src.dedup.datetime") as mock_dt:
        mock_dt.now.return_value = datetime(2026, 7, 8, tzinfo=TZ)
        from datetime import timedelta

        mock_dt.timedelta = timedelta
        result = compute_fetch_from()
        expected = (datetime(2026, 7, 8) - timedelta(days=30)).strftime("%Y-%m-%d")
        assert result == expected, f"Expected {expected}, got {result}"


def test_window_aug_1():
    """8 月 1 日（月初）→ 7 月 1 号。"""
    with patch("src.dedup.datetime") as mock_dt:
        mock_dt.now.return_value = datetime(2026, 8, 1, tzinfo=TZ)
        result = compute_fetch_from()
        assert result == "2026-07-01", f"Expected 2026-07-01, got {result}"


def test_filter_seen_and_date_ignore_seen(monkeypatch):
    """重建日报时应忽略 seen 注册表，但仍保留日期窗口过滤。"""
    papers = [
        {"id": "doi:seen", "online_date": "2026-07-01"},
        {"id": "doi:old", "online_date": "2026-05-01"},
    ]

    monkeypatch.setattr("src.dedup.load_seen", lambda: {"doi:seen": "2026-07-02"})
    monkeypatch.setattr("src.dedup.compute_fetch_from", lambda: "2026-06-01")

    result = filter_seen_and_date(papers, ignore_seen=True)

    assert [p["id"] for p in result] == ["doi:seen"]


if __name__ == "__main__":
    test_window_first_7_days()
    test_window_day_7()
    test_window_day_8()
    test_window_aug_1()
    print("All date filter boundary tests passed!")
