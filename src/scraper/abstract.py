"""
摘要抓取协调器。

按出版商分派到对应 scraper，处理重试、超时。
限速由各 scraper 内部控制（共享 Semantic Scholar 客户端）。
"""

import time

from src.config import SCRAPE_DELAY_SEC, SCRAPE_RETRIES
from src.scraper import sage, informs, springer


def scrape_abstracts(papers: list[dict]) -> list[dict]:
    """对候选论文列表抓取摘要。

    - 在调用前应已完成 seen + date 预过滤，只传入候选论文
    - 失败论文保留在列表中，abstract 为 None，abstract_missing=True
    - 串行请求，限速由共享 S2 客户端控制

    Returns:
        papers（原地修改 + 返回）
    """
    total = len(papers)
    success = 0

    for i, p in enumerate(papers):
        publisher = p.get("publisher", "")
        doi = p.get("doi")

        # SSRN: parser already has its own abstract fetching — skip scraper
        if publisher == "SSRN" and p.get("abstract"):
            success += 1
            continue

        abstract, accepted_by = None, None
        for attempt in range(SCRAPE_RETRIES + 1):
            try:
                abstract, accepted_by = _dispatch(publisher, doi, p.get("url", ""), journal=p.get("journal", ""))
                if abstract:
                    break
            except Exception as e:
                print(f"[SCRAPE] attempt {attempt + 1} failed for {p['title'][:60]}: {e}")
                if attempt < SCRAPE_RETRIES:
                    backoff = SCRAPE_DELAY_SEC * (2 ** attempt)
                    time.sleep(backoff)

        if abstract:
            p["abstract"] = abstract.strip()
            success += 1
        else:
            p["abstract"] = None
            p["abstract_missing"] = True
            print(f"[SCRAPE] abstract missing: {p['title'][:60]}...")

        # INFORMS: accepted_by 已由 _dispatch 返回，直接写入
        if publisher == "INFORMS" and accepted_by:
            p["mngsci_accepted_by"] = accepted_by

    print(f"[SCRAPE] {success}/{total} abstracts scraped successfully")
    return papers


def _dispatch(publisher: str, doi: str | None, url: str, journal: str = "") -> tuple[str | None, str | None]:
    """根据出版商分派到对应 scraper，返回 (abstract, accepted_by)。"""
    if publisher == "Sage":
        if not doi:
            return None, None
        return sage.scrape_abstract(doi), None
    elif publisher == "INFORMS":
        if not doi:
            return None, None
        return informs.scrape_abstract(doi, journal=journal)
    elif publisher == "Springer":
        article_url = url
        if doi and not article_url:
            article_url = f"https://link.springer.com/article/{doi}"
        return springer.scrape_abstract(article_url), None
    elif publisher == "SSRN":
        return None, None  # SSRN abstracts come from its own parser, not from scraper
    else:
        print(f"[SCRAPE] unknown publisher: {publisher}")
        return None
