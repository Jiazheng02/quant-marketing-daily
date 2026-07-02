"""
Springer 出版商摘要抓取（QME）。

link.springer.com 在不同网络环境下稳定性不一。
通过 Semantic Scholar API 获取摘要，确保跨环境可靠。
"""

from src.scraper._semantic_scholar import fetch_abstract as _s2_fetch


def scrape_abstract(url: str, session=None) -> str | None:
    """从 Semantic Scholar API 获取 Springer 论文摘要。

    从 RSS <link> URL 中提取 DOI，通过 S2 API 获取摘要。
    session 参数保留以兼容旧接口，实际未使用。
    """
    import re
    # 从 URL 中提取 DOI: https://link.springer.com/article/10.1007/s11129-025-09300-2
    m = re.search(r"(10\.\d{4,}/[^\s\"'?#]+)", url)
    if not m:
        return None
    return _s2_fetch(m.group(1))
