"""
Semantic Scholar API 共享客户端。

Rate limit: 100 requests / 5 min → 3.5s 间隔。
所有出版商 scraper 共用此客户端，确保全局限速。
"""

import re
import time
import sys
import requests

S2_BASE = "https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}"
S2_FIELDS = "title,abstract"
S2_DELAY_SEC = 3.5

# 模块级最后请求时间，供所有调用者共享
_last_request_at = 0.0


def _throttle():
    """确保距上次请求 ≥ S2_DELAY_SEC 秒。"""
    global _last_request_at
    elapsed = time.monotonic() - _last_request_at
    if elapsed < S2_DELAY_SEC:
        time.sleep(S2_DELAY_SEC - elapsed)
    _last_request_at = time.monotonic()


def fetch_abstract(doi: str) -> str | None:
    """从 Semantic Scholar 获取论文摘要。

    Args:
        doi: 论文 DOI

    Returns:
        纯文本摘要，失败返回 None
    """
    _throttle()

    url = S2_BASE.format(doi=doi)
    try:
        resp = requests.get(url, params={"fields": S2_FIELDS}, timeout=15)
    except requests.RequestException as e:
        print(f"[S2] HTTP error for {doi}: {e}", file=sys.stderr)
        return None

    if resp.status_code == 429:
        print(f"[S2] rate limited, backing off 15s", file=sys.stderr)
        time.sleep(15)
        return fetch_abstract(doi)

    if resp.status_code == 404:
        print(f"[S2] not indexed: {doi}", file=sys.stderr)
        return None

    if resp.status_code != 200:
        print(f"[S2] HTTP {resp.status_code} for {doi}", file=sys.stderr)
        return None

    try:
        data = resp.json()
    except ValueError:
        print(f"[S2] invalid JSON for {doi}", file=sys.stderr)
        return None

    abstract = data.get("abstract")
    if abstract:
        # 归一化空白字符：合并连续空格/换行/制表符为单空格
        abstract = re.sub(r"\s+", " ", abstract).strip()
        if len(abstract) >= 50:
            return abstract

    print(f"[S2] no/trivial abstract for {doi}", file=sys.stderr)
    return None
