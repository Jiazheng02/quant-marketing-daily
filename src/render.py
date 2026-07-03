"""
Markdown 日报渲染。

格式（每篇论文）：
  - **English Title**
    *中文译名*
    *Authors*
    `YYYY-MM` · `Vol.XX(I)` · `doi:10.xxxx/...`

    **AI 总结：** one-liner
    **原文链接：** [Source](url)

    <details>
    <summary>展开详情</summary>

    **Abstract:** English abstract...
    **中文翻译：** 完整中文翻译...
    </details>

    （空一行，隔篇）
"""

import os
import re
from datetime import datetime
from collections import defaultdict

from src.config import JOURNALS, JOURNAL_ORDER, OUTPUT_DIR, TZ
from src.dedup import compute_fetch_from


# ---------------------------------------------------------------------------
# 论文单行渲染
# ---------------------------------------------------------------------------
def _format_authors(authors: list[str]) -> str:
    """格式化作者列表：前 3 位 + et al.（≥4 位）。"""
    if not authors:
        return "Unknown"
    if len(authors) <= 3:
        return ", ".join(authors)
    return ", ".join(authors[:3]) + " et al."


def _format_tags(p: dict) -> str:
    """构建元数据标签行：`YYYY-MM` · `Vol.XX(I)` · `doi:10.xxxx/...`"""
    parts = []

    # coverdate → YYYY-MM
    cd = p.get("coverdate", "")
    if cd and len(cd) >= 7:
        parts.append(f"`{cd[:7]}`")

    # volume(issue)
    vol = p.get("volume", "")
    issue = p.get("issue", "")
    if vol:
        tag = f"Vol.{vol}"
        if issue:
            tag += f"({issue})"
        parts.append(f"`{tag}`")

    # DOI
    doi = p.get("doi")
    if doi:
        parts.append(f"`doi:{doi}`")

    return " · ".join(parts) if parts else ""


def _append_labeled_multiline(lines: list[str], label: str, text: str) -> None:
    """Append a labeled possibly-multiline field inside a paper block."""
    field_lines = text.splitlines() or [text]
    first = field_lines[0].strip()
    lines.append(f"  **{label}** {first}" if first else f"  **{label}**")

    for raw in field_lines[1:]:
        if raw.strip():
            lines.append(f"  {raw.strip()}")
        else:
            lines.append("")


def _render_paper(p: dict) -> str:
    """渲染单篇论文 Markdown。

    格式：
      - **English Title**
        *中文译名*
        *Authors*
        `YYYY-MM` · `Vol.XX(I)` · `doi:10.xxxx/...`

        **AI 总结：** one-liner
        **原文链接：** [Source](url)

        <details>
        <summary>展开详情</summary>

        **Abstract:** English abstract...
        **中文翻译：** 完整中文翻译...
        </details>
    """
    title = p["title"].strip()
    title_zh = p.get("title_zh", "").strip()
    authors = _format_authors(p.get("authors", []))
    tags = _format_tags(p)
    abstract = (p.get("abstract") or "").strip()
    one_liner = (p.get("one_line_summary") or "").strip()
    abstract_zh = (p.get("abstract_zh") or "").strip()
    doi = p.get("doi")
    url = p.get("url", "") or (f"https://doi.org/{doi}" if doi else "")

    lines = []

    # 行 1: 粗体英文标题
    lines.append(f"- **{title}**  ")

    # 行 2: 斜体中文译名
    if title_zh:
        lines.append(f"  *{title_zh}*  ")

    # 行 3: 斜体作者
    lines.append(f"  *{authors}*  ")

    # 行 4: 元数据标签
    if tags:
        lines.append(f"  {tags}")

    # 空行
    lines.append("")

    # AI 总结（独立一行，末尾俩空格 → Markdown 硬换行）
    if one_liner:
        lines.append(f"  **AI 总结：** {one_liner}  ")

    # 原文链接（独立一行）
    if url:
        lines.append(f"  **原文链接：** [Source]({url})")

    # Details 折叠区
    has_details = bool(abstract or abstract_zh or p.get("abstract_missing"))
    if has_details:
        lines.append("")
        lines.append("  <details>")
        lines.append("  <summary><b>展开详情</b></summary>")
        lines.append("")

        if abstract:
            _append_labeled_multiline(lines, "Abstract:", abstract)
            if abstract_zh:
                lines.append("")

        if p.get("abstract_missing") and not abstract:
            lines.append("  **Abstract:** [摘要缺失]")

        if abstract_zh:
            _append_labeled_multiline(lines, "中文翻译：", abstract_zh)

        lines.append("")
        lines.append("  </details>")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 分组渲染
# ---------------------------------------------------------------------------
def _group_papers(papers: list[dict]) -> dict[str, list[dict]]:
    """按期刊分组，保持 display order。"""
    groups = defaultdict(list)
    for p in papers:
        groups[p["journal"]].append(p)

    ordered = {}
    for key in JOURNAL_ORDER:
        if key in groups:
            ordered[key] = groups[key]
    return ordered


def _get_section_title(journal_key: str, papers: list[dict]) -> str:
    """生成期刊板块标题。"""
    journal = JOURNALS.get(journal_key, {})
    name = journal.get("name", journal_key)

    if journal_key == "MngSci":
        return f"## {name} — Marketing ({len(papers)} 篇)"

    return f"## {name} ({len(papers)} 篇)"


# ---------------------------------------------------------------------------
# TOC / 辅助
# ---------------------------------------------------------------------------
def _toc_anchor(heading: str) -> str:
    """从 `## Journal Name (N 篇)` 生成 GFM 兼容的锚点 ID。"""
    slug = heading.lstrip("#").strip().lower()
    # 去掉标点符号，保留字母、数字、空格、连字符、中文
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"\s+", "-", slug)
    slug = re.sub(r"-+", "-", slug)
    return slug


def _build_toc(grouped: dict[str, list[dict]]) -> list[str]:
    """生成目录列表（Markdown 无序列表 + 锚点链接）。"""
    lines = ["## 目录", ""]
    for journal_key, papers in grouped.items():
        heading = _get_section_title(journal_key, papers)
        anchor = _toc_anchor(heading)
        label = _get_section_title(journal_key, papers).lstrip("#").strip()
        lines.append(f"- [{label}](#{anchor})")
    return lines


# ---------------------------------------------------------------------------
# 日报渲染
# ---------------------------------------------------------------------------
def render_markdown(papers: list[dict]) -> str:
    """渲染完整 Markdown 日报。"""
    now = datetime.now(TZ)
    today = now.strftime("%Y-%m-%d")
    weekday_map = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    weekday = weekday_map[now.weekday()]

    has_ai = any(p.get("one_line_summary") for p in papers)
    sources = len(set(p["journal"] for p in papers)) if papers else 0
    fetch_from = compute_fetch_from()

    lines = [
        f"# Quant Marketing Daily — {today} ({weekday})",
        "",
        f"_{fetch_from} ~ {today} · {len(papers)} 篇新论文 · {sources} 个来源_",
    ]

    # 降级模式提示
    if papers and not has_ai:
        lines.append("")
        lines.append(
            "> :information_source: 未检测到可用 LLM（配置 `DEEPSEEK_API_KEY` 或启动 Ollama "
            "后自动生成中文标题翻译、一句话总结与完整中文翻译）。"
        )

    lines += ["", "---", ""]

    if not papers:
        lines.append("今日无新论文。")
    else:
        grouped = _group_papers(papers)

        # 目录
        lines += _build_toc(grouped)
        lines += ["", "---", ""]

        for journal_key, group in grouped.items():
            lines.append(_get_section_title(journal_key, group))
            lines.append("")
            for p in group:
                lines.append(_render_paper(p))
                lines.append("")
            lines.append("---")
            lines.append("")

    footer = (
        f"\n> Generated at {now.strftime('%Y-%m-%d %H:%M CST')} "
        f"by quant-marketing-daily"
    )
    lines.append(footer)

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 保存
# ---------------------------------------------------------------------------
def _extract_report_count(markdown: str) -> int | None:
    """从日报副标题中提取论文数量。"""
    match = re.search(r"·\s*(\d+)\s*篇新论文\s*·", markdown)
    if not match:
        return None
    return int(match.group(1))


def save_report(
    markdown: str,
    date_str: str | None = None,
    preserve_richer_existing: bool = False,
) -> str:
    """保存 Markdown 到 output/ 目录。返回文件路径。

    正常增量模式可能在同一天生成比手动 rebuild 更小的报告。启用
    preserve_richer_existing 时，如果已有同日报告论文数更多，则保留旧文件。
    """
    if date_str is None:
        date_str = datetime.now(TZ).strftime("%Y-%m-%d")

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    path = os.path.join(OUTPUT_DIR, f"{date_str}.md")

    if preserve_richer_existing and os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            existing = f.read()
        existing_count = _extract_report_count(existing)
        new_count = _extract_report_count(markdown)
        if (
            existing_count is not None
            and new_count is not None
            and existing_count > new_count
        ):
            print(
                f"[RENDER] kept existing richer report → {path} "
                f"({existing_count} > {new_count})"
            )
            return path

    with open(path, "w", encoding="utf-8") as f:
        f.write(markdown)

    print(f"[RENDER] saved → {path}")
    return path
