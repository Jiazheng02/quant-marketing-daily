from src.notify_email import (
    _find_latest_report,
    _find_report_for_date,
    _render_email_html,
)


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


def test_email_abstract_and_translation_are_separate_paragraphs():
    html = _render_email_html(
        "\n".join(
            [
                "- **Paper Title**  ",
                "  *Author One*  ",
                "",
                "  **原文链接：** [Source](https://doi.org/10.test/example)",
                "",
                "  <details>",
                "  <summary><b>展开详情</b></summary>",
                "",
                "  **Abstract:** English abstract.",
                "  **中文翻译：** 中文摘要。",
                "",
                "  </details>",
            ]
        )
    )

    assert "<p><strong>Abstract:</strong> English abstract.</p>" in html
    assert "<p><strong>中文翻译：</strong> 中文摘要。</p>" in html
    assert "English abstract.</p>\n<p><strong>中文翻译" in html


def test_compact_email_abstract_mode_adds_preview_style(monkeypatch):
    monkeypatch.setenv("EMAIL_ABSTRACT_MODE", "compact")

    html = _render_email_html(
        "\n".join(
            [
                "- **Paper Title**  ",
                "  **Abstract:** English abstract.",
            ]
        )
    )

    assert 'class="paper-abstract paper-abstract-compact"' in html
    assert "邮件中显示为摘要预览" in html
