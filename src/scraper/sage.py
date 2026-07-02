"""
Sage 出版商摘要抓取（JM / JMR）。

策略：
  1. Crossref JSON API（完整摘要，无 Cloudflare 限制）
  2. Semantic Scholar API 兜底

journals.sagepub.com 有 Cloudflare 防护，直接 HTML 请求返回 403。
"""

from src.scraper._semantic_scholar import fetch_abstract as _s2_fetch
from src.scraper.informs import _crossref_fetch, _clean_s2_abstract


def scrape_abstract(doi: str, session=None) -> str | None:
    """获取 Sage 论文摘要。

    session 参数保留以兼容旧接口，实际未使用。
    """
    # 1. Crossref JSON API（无 Cloudflare，摘要质量高）
    cr = _crossref_fetch(doi)
    if cr and cr.get("abstract"):
        return cr["abstract"]

    # 2. Semantic Scholar 兜底
    abstract = _s2_fetch(doi)
    if abstract:
        abstract = _clean_s2_abstract(abstract)
        if abstract and len(abstract) >= 50:
            return abstract

    return None
