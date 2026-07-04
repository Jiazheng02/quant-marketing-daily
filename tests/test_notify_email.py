from src.notify_email import _find_latest_report, _find_report_for_date


def test_find_latest_report_uses_newest_date_filename(tmp_path, monkeypatch):
    output = tmp_path / "output"
    output.mkdir()
    (output / "2026-07-04.md").write_text("old", encoding="utf-8")
    (output / "2026-07-05.md").write_text("new", encoding="utf-8")
    (output / ".gitkeep").write_text("", encoding="utf-8")

    monkeypatch.chdir(tmp_path)

    assert _find_latest_report() == "output/2026-07-05.md"


def test_find_report_for_date_requires_exact_date(tmp_path, monkeypatch):
    output = tmp_path / "output"
    output.mkdir()
    (output / "2026-07-04.md").write_text("report", encoding="utf-8")

    monkeypatch.chdir(tmp_path)

    assert _find_report_for_date("2026-07-04") == "output/2026-07-04.md"
    assert _find_report_for_date("2026-07-05") is None
