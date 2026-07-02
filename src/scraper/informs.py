"""
INFORMS 出版商摘要抓取（MktSci / MngSci）。

策略：
  - MktSci: 优先读取本地完整摘要缓存；缓存缺失时用 Crossref
    快速判断，若只拿到短摘要则尝试 Scrapling 原文页补全，再用
    Semantic Scholar 兜底
  - MngSci: Crossref JSON API 获取摘要 + "accepted by" 元数据
  - pubsonline.informs.org 有 Cloudflare/Turnstile 防护，Scrapling 补抓必须
    是 best-effort，失败后保留短摘要并写入待处理队列
"""

import re
import json
import os
import urllib.request
import urllib.error

from src.scraper.informs_page import (
    MIN_FULL_ABSTRACT_LENGTH,
    fetch_full_abstract_with_scrapling,
)

# ---------------------------------------------------------------------------
# MktSci 完整摘要缓存
# ---------------------------------------------------------------------------
# 缓存文件：data/mktsci_abstracts.json  →  {"doi": "full abstract text", ...}
# 待抓取文件：data/pending_mktsci.json  →  ["doi1", "doi2", ...]
# Scrapling 自动补抓失败时，DOI 会进入 pending；可人工或云端抓取完整摘要后
# 通过 enrich_mktsci.py 写入缓存。

_DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data",
)
_MKTSCI_CACHE_FILE = os.path.join(_DATA_DIR, "mktsci_abstracts.json")
_PENDING_FILE = os.path.join(_DATA_DIR, "pending_mktsci.json")
_SHORT_ABSTRACT_THRESHOLD = MIN_FULL_ABSTRACT_LENGTH  # 小于此字符数视为 MktSci 不完整摘要


def _ensure_data_dir() -> None:
    os.makedirs(_DATA_DIR, exist_ok=True)


def load_mktsci_cache() -> dict[str, str]:
    """读取 MktSci 完整摘要缓存。"""
    _ensure_data_dir()
    if not os.path.exists(_MKTSCI_CACHE_FILE):
        return {}
    try:
        with open(_MKTSCI_CACHE_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def save_to_mktsci_cache(doi: str, abstract: str) -> None:
    """将一篇论文的完整摘要写入缓存。"""
    _ensure_data_dir()
    cache = load_mktsci_cache()
    cache[doi] = abstract.strip()
    with open(_MKTSCI_CACHE_FILE, "w") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)
    print(f"[MktSci-cache] saved full abstract for {doi}")


def save_pending_mktsci(doi: str) -> None:
    """将需要云端抓取的 DOI 写入待处理文件（去重追加）。"""
    _ensure_data_dir()
    pending: list[str] = []
    if os.path.exists(_PENDING_FILE):
        try:
            with open(_PENDING_FILE, "r") as f:
                pending = json.load(f)
        except (json.JSONDecodeError, OSError):
            pending = []
    if doi not in pending:
        pending.append(doi)
        with open(_PENDING_FILE, "w") as f:
            json.dump(pending, f, ensure_ascii=False, indent=2)


def get_pending_mktsci() -> list[str]:
    """读取待抓取 DOI 列表。"""
    if not os.path.exists(_PENDING_FILE):
        return []
    try:
        with open(_PENDING_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


def clear_pending_mktsci() -> None:
    """清空待抓取列表（所有待处理 DOI 已写入缓存后调用）。"""
    if os.path.exists(_PENDING_FILE):
        os.remove(_PENDING_FILE)


# ---------------------------------------------------------------------------
# Crossref 客户端
# ---------------------------------------------------------------------------
_CROSSREF_CACHE: dict[str, dict | None] = {}  # doi → parsed data or None


def _crossref_fetch(doi: str) -> dict | None:
    """从 Crossref JSON API 获取论文元数据。

    Returns:
        {"abstract": str|None, "accepted_by": str|None} 或 None（HTTP error）
    """
    if doi in _CROSSREF_CACHE:
        return _CROSSREF_CACHE[doi]

    url = f"https://api.crossref.org/works/{doi}"
    req = urllib.request.Request(url, headers={"User-Agent": "quant-marketing-daily/1.0 (mailto:dev@example.com)"})

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
    except (urllib.error.HTTPError, urllib.error.URLError, json.JSONDecodeError):
        _CROSSREF_CACHE[doi] = None
        return None

    msg = data.get("message", {})
    raw_abstract = msg.get("abstract", "") or ""

    # ---- 提取 accepted-by 元数据 ----
    accepted_by = None
    # 匹配: <jats:p>This paper (was|has been) accepted by XXX, department.</jats:p>
    m = re.search(
        r"<jats:p>\s*(This paper (?:was|has been) accepted by\s[^<]+)</jats:p>",
        raw_abstract,
        re.IGNORECASE,
    )
    if m:
        accepted_by = re.sub(r"<[^>]+>", "", m.group(1)).strip()
        # 去掉尾部句号但保留内容
        accepted_by = accepted_by.rstrip(".")

    # ---- 清洗摘要 ----
    clean_abstract = _clean_jats(raw_abstract) if raw_abstract else None

    result = {"abstract": clean_abstract, "accepted_by": accepted_by}
    _CROSSREF_CACHE[doi] = result
    return result


def _clean_jats(raw: str) -> str | None:
    """JATS XML → 纯文本，剥离 accepted-by / funding 等元数据行。"""
    # 先移除 accepted-by 段（已单独提取）
    raw = re.sub(
        r"<jats:p>\s*This paper (?:was|has been) accepted by[^<]*</jats:p>",
        "",
        raw,
        flags=re.IGNORECASE,
    )
    # 移除 Funding 段
    raw = re.sub(r"<jats:p>\s*Funding:[^<]*</jats:p>", "", raw, flags=re.IGNORECASE)
    # 移除 Supplemental Material 段
    raw = re.sub(
        r"<jats:p>\s*Supplemental Material:[^<]*</jats:p>",
        "",
        raw,
        flags=re.IGNORECASE,
    )
    raw = re.sub(
        r"<jats:p>\s*The (?:online appendix|data files|online appendix and data files) (?:is|are) available at[^<]*</jats:p>",
        "",
        raw,
        flags=re.IGNORECASE,
    )

    # 剥离所有标签
    text = re.sub(r"<[^>]+>", " ", raw)
    text = re.sub(r"\s+", " ", text).strip()

    if len(text) < 50:
        return None
    return text


# ---------------------------------------------------------------------------
# Semantic Scholar 兜底
# ---------------------------------------------------------------------------
from src.scraper._semantic_scholar import fetch_abstract as _s2_fetch


def scrape_abstract(doi: str, session=None, journal: str = "") -> tuple[str | None, str | None]:
    """获取 INFORMS 论文摘要 + accepted_by。

    MktSci 策略（best-effort 获取完整摘要）：
    1. 优先读本地完整摘要缓存 data/mktsci_abstracts.json
    2. 缓存未命中 → Crossref JSON API（通常只有 ~150 字符短摘要）
    3. Crossref 为短摘要时 → Scrapling 原文页补抓，成功则写入缓存
    4. 兜底 Semantic Scholar API
    5. 若摘要 < SHORT_ABSTRACT_THRESHOLD 字符，标记为待人工/云端补抓

    MngSci 策略（Crossref 已有完整摘要）：
    1. Crossref JSON API → Semantic Scholar 兜底

    Returns:
        (abstract, accepted_by)
    """
    is_mktsci = (journal == "MktSci")
    accepted_by = None

    # --- MktSci: 先查本地完整摘要缓存 ---
    if is_mktsci:
        cache = load_mktsci_cache()
        if doi in cache and cache[doi] and len(cache[doi]) >= _SHORT_ABSTRACT_THRESHOLD:
            return cache[doi], None

    # --- Crossref JSON API ---
    cr = _crossref_fetch(doi)
    if cr:
        accepted_by = cr.get("accepted_by")
        abstract = cr.get("abstract")

        # MktSci 短摘要检测 → Playwright 持久化 profile 绕过 Cloudflare，
        # 失败再 Scrapling 原文页补抓，仍失败则标记 pending
        if abstract and is_mktsci and len(abstract) < _SHORT_ABSTRACT_THRESHOLD:
            from src.scraper.informs_page import fetch_mktsci_with_playwright
            full_abstract = fetch_mktsci_with_playwright(doi, min_length=_SHORT_ABSTRACT_THRESHOLD)
            if full_abstract:
                save_to_mktsci_cache(doi, full_abstract)
                return full_abstract, None

            full_abstract = fetch_full_abstract_with_scrapling(doi, min_length=_SHORT_ABSTRACT_THRESHOLD)
            if full_abstract:
                save_to_mktsci_cache(doi, full_abstract)
                return full_abstract, None

            print(f"[MktSci] short abstract ({len(abstract)} chars) for {doi} — queued for manual/cloud fetch")
            save_pending_mktsci(doi)
            return abstract, accepted_by

        if abstract:
            return abstract, accepted_by

    if is_mktsci:
        from src.scraper.informs_page import fetch_mktsci_with_playwright
        full_abstract = fetch_mktsci_with_playwright(doi, min_length=_SHORT_ABSTRACT_THRESHOLD)
        if full_abstract:
            save_to_mktsci_cache(doi, full_abstract)
            return full_abstract, None

        full_abstract = fetch_full_abstract_with_scrapling(doi, min_length=_SHORT_ABSTRACT_THRESHOLD)
        if full_abstract:
            save_to_mktsci_cache(doi, full_abstract)
            return full_abstract, None

    # --- Semantic Scholar 兜底 ---
    abstract = _s2_fetch(doi)
    if abstract:
        abstract = _clean_s2_abstract(abstract)
        if abstract and len(abstract) >= 50:
            # MktSci: 同样检测短摘要
            if is_mktsci and len(abstract) < _SHORT_ABSTRACT_THRESHOLD:
                print(f"[MktSci] short S2 abstract ({len(abstract)} chars) for {doi} — queued for cloud fetch")
                save_pending_mktsci(doi)
            return abstract, accepted_by

    return None, None


# ---------------------------------------------------------------------------
# S2 摘要的元数据剥离（兼容旧逻辑）
# ---------------------------------------------------------------------------
_S2_JUNK_PATTERNS = [
    re.compile(r"^\s*This paper (?:has been|was) accepted by\b.*$", re.MULTILINE),
    re.compile(r"^\s*Funding:\s.*$", re.MULTILINE),
    re.compile(r"^\s*Supplemental Material:\s.*$", re.MULTILINE),
    re.compile(
        r"^\s*The (?:online appendix|data files|online appendix and data files) (?:is|are) available at\b.*$",
        re.MULTILINE,
    ),
]


def _clean_s2_abstract(text: str) -> str:
    for pat in _S2_JUNK_PATTERNS:
        text = pat.sub("", text)
    # 归一化空白字符：合并换行/连续空格为单空格
    text = re.sub(r"\s+", " ", text).strip()
    return text
