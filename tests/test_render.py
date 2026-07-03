"""
Markdown 渲染格式测试。
"""

from src import render
from src.render import _render_paper, _format_authors, _format_tags, _group_papers, render_markdown, save_report


def test_format_authors_three():
    """3 位以内作者全列。"""
    authors = ["Alice", "Bob", "Charlie"]
    result = _format_authors(authors)
    assert result == "Alice, Bob, Charlie"


def test_format_authors_four():
    """4 位及以上作者显示前 3 + et al.。"""
    authors = ["Alice", "Bob", "Charlie", "David"]
    result = _format_authors(authors)
    assert result == "Alice, Bob, Charlie et al."


def test_format_tags():
    """标签行格式正确。"""
    p = {
        "coverdate": "2026-07-01",
        "volume": "90",
        "issue": "4",
        "doi": "10.1177/00222429251382272",
    }
    result = _format_tags(p)
    assert "`2026-07`" in result
    assert "`Vol.90(4)`" in result
    assert "`doi:10.1177/00222429251382272`" in result
    assert " · " in result


def test_format_tags_no_metadata():
    """无元数据时标签行为空。"""
    p = {}
    assert _format_tags(p) == ""


def test_render_paper_structure():
    """新格式：英文标题 → 中文译名 → 作者 → 标签 → AI总结 + Source → <details>。"""
    p = {
        "title": "Test Paper Title",
        "title_zh": "测试论文标题",
        "authors": ["Alice", "Bob"],
        "coverdate": "2026-07-01",
        "volume": "90",
        "issue": "4",
        "doi": "10.1177/test",
        "abstract": "This is the full English abstract.",
        "one_line_summary": "本研究通过实验方法验证了营销策略的有效性。",
        "abstract_zh": "这是一篇测试论文的完整中文摘要。",
        "url": "https://doi.org/10.1177/test",
        "abstract_missing": False,
    }
    result = _render_paper(p)

    # 英文标题
    assert "- **Test Paper Title**" in result
    # 中文译名
    assert "*测试论文标题*" in result
    # 作者
    assert "*Alice, Bob*" in result
    # 标签
    assert "`2026-07`" in result
    # AI 总结
    assert "**AI 总结：** 本研究通过实验方法验证了营销策略的有效性。" in result
    # Source 链接
    assert "[Source](https://doi.org/10.1177/test)" in result
    # Details 折叠区
    assert "<details>" in result
    assert "<summary><b>展开详情</b></summary>" in result
    assert "**Abstract:** This is the full English abstract." in result
    assert "**中文翻译：** 这是一篇测试论文的完整中文摘要。" in result
    assert "</details>" in result


def test_render_no_title_zh():
    """无中文译名时跳过该行。"""
    p = {
        "title": "Paper Without Chinese Title",
        "authors": ["Alice"],
        "abstract": "Abstract text.",
        "one_line_summary": "",
        "abstract_zh": "",
        "url": "",
        "abstract_missing": False,
    }
    result = _render_paper(p)
    # 标题保持粗体，中文译名不出现
    assert "**Paper Without Chinese Title**" in result
    assert "*Alice*" in result
    # 有中文译名时：`  *译名*  ` → `  *作者*  ` 会紧挨着（两行斜体）
    # 无中文译名时：`  *作者*  ` 单独一行
    # 简单验证：不应出现两个连续的斜体行
    lines = result.split("\n")
    prev_italic = False
    consecutive_italics = 0
    for line in lines:
        stripped = line.strip()
        is_italic = stripped.startswith("*") and stripped.endswith("*") and stripped.count("*") == 2
        if is_italic and prev_italic:
            consecutive_italics += 1
        prev_italic = is_italic
    assert consecutive_italics == 0, "Two consecutive italic lines indicate empty Chinese title"


def test_render_no_ai_summary():
    """无 AI 摘要时跳过 AI 总结行，但有 abstract 时仍有 details。"""
    p = {
        "title": "No AI Paper",
        "authors": ["Alice"],
        "abstract": "English abstract.",
        "one_line_summary": "",
        "abstract_zh": "",
        "url": "https://doi.org/10.1177/test",
        "abstract_missing": False,
    }
    result = _render_paper(p)
    assert "**AI 总结：**" not in result
    assert "[Source](https://doi.org/10.1177/test)" in result
    assert "<details>" in result
    assert "**Abstract:** English abstract." in result


def test_render_empty_daily():
    """空日报渲染。"""
    md = render_markdown([])
    assert "今日无新论文" in md
    assert "Quant Marketing Daily" in md


def test_mngsci_grouping_single_section():
    """MngSci 所有论文合并为一个组。"""
    papers = [
        {
            "title": "Marketing Dept Paper A",
            "authors": ["A"],
            "journal": "MngSci",
            "url": "",
        },
        {
            "title": "Marketing Dept Paper B",
            "authors": ["B"],
            "journal": "MngSci",
            "url": "",
        },
    ]
    grouped = _group_papers(papers)
    assert "MngSci" in grouped
    assert len(grouped["MngSci"]) == 2
    md = render_markdown(papers)
    assert "Marketing (2 篇)" in md


def test_details_block_present():
    """有 abstract 或 abstract_zh 时生成 <details> 块。"""
    p = {
        "title": "Full Paper",
        "authors": ["Alice"],
        "abstract": "Full abstract here.",
        "one_line_summary": "一句话总结。",
        "abstract_zh": "中文摘要。",
        "url": "",
        "abstract_missing": False,
    }
    result = _render_paper(p)
    assert "展开详情" in result
    assert "<details>" in result
    assert "</details>" in result


def test_multiline_translation_stays_inside_details():
    """多行中文翻译的后续行也要缩进，避免跑出论文块。"""
    p = {
        "title": "Multiline Paper",
        "authors": ["Alice"],
        "abstract": "First abstract line.\nSecond abstract line.",
        "one_line_summary": "",
        "abstract_zh": "第一行翻译。\n第二行翻译。",
        "url": "",
        "abstract_missing": False,
    }

    result = _render_paper(p)

    assert "  **Abstract:** First abstract line." in result
    assert "\n  Second abstract line." in result
    assert "  **中文翻译：** 第一行翻译。" in result
    assert "\n  第二行翻译。" in result


def test_no_details_when_empty():
    """无 abstract 且无 abstract_zh 时不生成 details 块。"""
    p = {
        "title": "Minimal Paper",
        "authors": ["Alice"],
        "abstract": "",
        "one_line_summary": "",
        "abstract_zh": "",
        "url": "https://test.com",
        "abstract_missing": False,
    }
    result = _render_paper(p)
    assert "<details>" not in result


def test_save_report_preserves_richer_existing(tmp_path, monkeypatch):
    monkeypatch.setattr(render, "OUTPUT_DIR", str(tmp_path))
    existing = "# Quant Marketing Daily\n\n_2026-06-01 ~ 2026-07-03 · 18 篇新论文 · 4 个来源_\n"
    smaller = "# Quant Marketing Daily\n\n_2026-06-01 ~ 2026-07-03 · 1 篇新论文 · 1 个来源_\n"
    path = tmp_path / "2026-07-03.md"
    path.write_text(existing, encoding="utf-8")

    save_report(smaller, date_str="2026-07-03", preserve_richer_existing=True)

    assert path.read_text(encoding="utf-8") == existing


def test_save_report_overwrites_when_new_report_is_richer(tmp_path, monkeypatch):
    monkeypatch.setattr(render, "OUTPUT_DIR", str(tmp_path))
    existing = "# Quant Marketing Daily\n\n_2026-06-01 ~ 2026-07-03 · 1 篇新论文 · 1 个来源_\n"
    richer = "# Quant Marketing Daily\n\n_2026-06-01 ~ 2026-07-03 · 18 篇新论文 · 4 个来源_\n"
    path = tmp_path / "2026-07-03.md"
    path.write_text(existing, encoding="utf-8")

    save_report(richer, date_str="2026-07-03", preserve_richer_existing=True)

    assert path.read_text(encoding="utf-8") == richer


if __name__ == "__main__":
    test_format_authors_three()
    test_format_authors_four()
    test_format_tags()
    test_format_tags_no_metadata()
    test_render_paper_structure()
    test_render_no_title_zh()
    test_render_no_ai_summary()
    test_render_empty_daily()
    test_mngsci_grouping_single_section()
    test_details_block_present()
    test_multiline_translation_stays_inside_details()
    test_no_details_when_empty()
    print("All render tests passed!")
