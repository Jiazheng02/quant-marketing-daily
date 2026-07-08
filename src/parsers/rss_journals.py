"""
RSS 解析 — 五大期刊元数据提取（不含摘要）。

双日期模型：
  online_date  — 过滤用（prism/print issue date > online/AiA date > ""）
  coverdate    — 展示用（prism/print issue date）

RSS/Crossref 仅发现论文；摘要从出版商详情页抓取（见 scraper/）。
"""

import hashlib
import os
import re
from datetime import datetime
from typing import Optional

import feedparser

from src.config import JOURNALS, RSS_MAX_ENTRIES

# Crossref ISSN mapping for publisher fallback/supplement.
_CROSSREF_ISSN = {
    "JM": "0022-2429",
    "JMR": "0022-2437",
    "MktSci": "0732-2399",
    "MngSci": "0025-1909",
}

_CROSSREF_MAX_ROWS = {
    "JM": 80,
    "JMR": 80,
    "MktSci": 80,
    "MngSci": 200,
}


# ---------------------------------------------------------------------------
# 非论文过滤
# ---------------------------------------------------------------------------
NON_PAPER_TITLES = {
    "focus on authors", "editorial board", "editorial",
    "call for papers", "special issue", "corrigendum",
    "erratum", "retraction", "acknowledgment",
    "announcement", "table of contents", "front matter",
    "back matter", "introduction to the special issue",
    "reviewers", "thanks to reviewers",
}


def _is_non_paper(title: str) -> bool:
    t = title.strip().lower()
    for kw in NON_PAPER_TITLES:
        if kw in t:
            return True
    if len(t.split()) <= 3:
        return True
    return False


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------
def _clean_html(raw: str) -> str:
    return re.sub(r"<[^>]+>", "", raw).strip()


def _clean_doi(raw: str) -> str:
    return re.sub(r"\?.*$", "", raw).strip()


def doi_to_url(doi: str) -> str:
    doi = doi.strip()
    if doi.startswith("http"):
        return doi
    return f"https://doi.org/{doi}"


# ---------------------------------------------------------------------------
# DOI 提取
# ---------------------------------------------------------------------------
def _extract_doi(entry: dict) -> Optional[str]:
    eid = entry.get("id", "")
    m = re.search(r"(10\.\d{4,}/[^\s\"'?]+)", eid)
    if m:
        return _clean_doi(m.group(1))
    if "dc_identifier" in entry:
        m = re.search(r"(10\.\d{4,}/[^\s\"'?]+)", entry.dc_identifier)
        if m:
            return _clean_doi(m.group(1))
    for link in entry.get("links", []):
        href = link.get("href", "")
        m = re.search(r"(10\.\d{4,}/[^\s\"'?]+)", href)
        if m:
            return _clean_doi(m.group(1))
    return None


# ---------------------------------------------------------------------------
# 作者提取
# ---------------------------------------------------------------------------
def _extract_authors(entry: dict) -> list[str]:
    authors = []
    if "authors" in entry:
        for a in entry.authors:
            name = a.get("name", "").strip()
            if name:
                authors.append(name)
    if not authors and "author" in entry:
        authors.append(entry.author.strip())
    # Springer fallback
    if not authors:
        summary = entry.get("summary", "")
        m = re.search(r"<p>\s*by\s+([^<]+)</p>", summary, re.IGNORECASE)
        if m:
            authors = [a.strip() for a in m.group(1).split(",") if a.strip()]
    # Sage/INFORMS 单标签多作者拆分
    if len(authors) == 1 and authors[0].count(",") >= 2:
        authors = [a.strip() for a in authors[0].split(",") if a.strip()]
    return authors


# ---------------------------------------------------------------------------
# 双日期模型
# ---------------------------------------------------------------------------
def _parse_date_iso(s: str) -> str:
    s = s.strip()
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    raise ValueError(f"cannot parse date: {s}")


def _parse_online_date(entry: dict) -> str:
    """提取 online_date（过滤用）。

    优先级：prism_coverdate（实际出版日）> updated_parsed（AiA 兜底）> published

    - 优先取 prism_coverdate — 这是论文在期刊上的正式出版日期，最可靠。
    - Sage 的 updated_parsed 是原始平台上传日（可能远早于出版），不可作为过滤依据。
    - INFORMS Articles in Advance 无 prism_coverdate，通过 updated_parsed 捕获。
    """
    # 1. prism_coverdate（最可靠的出版日期）
    for field in ("prism_coverdate", "coverdate"):
        val = entry.get(field, "")
        if val:
            try:
                return _parse_date_iso(str(val))
            except (ValueError, TypeError):
                pass

    # 2. updated_parsed（AiA 兜底）
    for field in ("updated_parsed", "updated"):
        if field not in entry:
            continue
        val = entry[field]
        if isinstance(val, str):
            try:
                return _parse_date_iso(val)
            except (ValueError, TypeError):
                continue
        elif hasattr(val, "tm_year"):
            try:
                return datetime(*val[:6]).strftime("%Y-%m-%d")
            except (ValueError, TypeError):
                continue

    # 3. published
    for field in ("published_parsed", "published"):
        if field not in entry:
            continue
        val = entry[field]
        if isinstance(val, str):
            try:
                return _parse_date_iso(val)
            except (ValueError, TypeError):
                continue
        elif hasattr(val, "tm_year"):
            try:
                return datetime(*val[:6]).strftime("%Y-%m-%d")
            except (ValueError, TypeError):
                continue

    # 4. 无可用日期
    return ""


def _parse_coverdate(entry: dict) -> str:
    """提取 coverdate（展示用）。

    优先级：prism_coverdate > updated（AiA 兜底）

    INFORMS Articles in Advance 无 prism_coverdate，updated 字段即
    "Published Online" 日期，作为展示用日期回退。
    """
    # 1. prism_coverdate（正式出版日期）
    for field in ("prism_coverdate", "coverdate"):
        val = entry.get(field, "")
        if val:
            try:
                return _parse_date_iso(val)
            except (ValueError, TypeError):
                pass

    # 2. updated（INFORMS AiA "Published Online" 日期）
    val = entry.get("updated", "")
    if val:
        try:
            return _parse_date_iso(val)
        except (ValueError, TypeError):
            pass
        # 也可能已经是 time.struct_time
        if hasattr(val, "tm_year"):
            try:
                return datetime(*val[:6]).strftime("%Y-%m-%d")
            except (ValueError, TypeError):
                pass

    return ""


# ---------------------------------------------------------------------------
# 结构化元数据（volume/issue/pages）
# ---------------------------------------------------------------------------
def _extract_structured_meta(entry: dict) -> dict:
    meta = {}
    if "prism_volume" in entry:
        meta["volume"] = str(entry.prism_volume).strip()
    if "prism_number" in entry:
        meta["issue"] = str(entry.prism_number).strip()
    if "prism_startingpage" in entry:
        meta["startpage"] = str(entry.prism_startingpage).strip()
    if "prism_endingpage" in entry:
        meta["endpage"] = str(entry.prism_endingpage).strip()
    return meta


# ---------------------------------------------------------------------------
# Paper ID
# ---------------------------------------------------------------------------
def _paper_id(doi: Optional[str], title: str, journal_key: str) -> str:
    if doi:
        return f"doi:{doi}"
    raw = f"{journal_key}:{title}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Crossref 回退/补充（RSS 被拦截或不完整时使用）
# ---------------------------------------------------------------------------

def _crossref_fetch_from() -> str:
    """Use the same moving date window as the main date filter."""
    from src.dedup import compute_fetch_from
    return compute_fetch_from()


def _fmt_crossref_date(parts) -> str:
    """Format Crossref date-parts, allowing YYYY or YYYY-MM dates."""
    if not parts or not parts[0]:
        return ""
    year = parts[0]
    month = parts[1] if len(parts) >= 2 else 1
    day = parts[2] if len(parts) >= 3 else 1
    return f"{year:04d}-{month:02d}-{day:02d}"


def _split_crossref_pages(page: str) -> tuple[str | None, str | None]:
    if not page:
        return None, None
    if "-" in page:
        start, end = page.split("-", 1)
        return start.strip() or None, end.strip() or None
    return page.strip() or None, None


def _crossref_item_to_paper(item: dict, journal_key: str) -> dict | None:
    doi = item.get("DOI", "").strip()
    if not doi:
        return None

    title_list = item.get("title", [])
    title = title_list[0].strip() if title_list else ""
    if not title:
        title = item.get("original-title", [None])[0] or ""

    title = _clean_html(title)
    if not title or _is_non_paper(title):
        return None

    journal = JOURNALS[journal_key]

    authors = []
    for a in item.get("author", []):
        given = a.get("given", "")
        family = a.get("family", "")
        name = f"{given} {family}".strip()
        if name:
            authors.append(name)

    print_parts = item.get("published-print", {}).get("date-parts", [[None]])[0]
    online_parts = item.get("published-online", {}).get("date-parts", [[None]])[0]
    published_parts = item.get("published", {}).get("date-parts", [[None]])[0]
    created_parts = item.get("created", {}).get("date-parts", [[None]])[0]

    # Formal issue date first. Sage/JM/JMR often have old online dates but
    # current print issue dates, and those issue dates should drive inclusion.
    publication_date = (
        _fmt_crossref_date(print_parts)
        or _fmt_crossref_date(online_parts)
        or _fmt_crossref_date(published_parts)
        or _fmt_crossref_date(created_parts)
    )

    page = item.get("page", "") or ""
    startpage, endpage = _split_crossref_pages(page)

    return {
        "id": _paper_id(doi, title, journal_key),
        "title": title,
        "authors": authors,
        "abstract": None,
        "abstract_missing": False,
        "journal": journal_key,
        "journal_full": journal["name"],
        "publisher": journal["publisher"],
        "doi": doi,
        "url": doi_to_url(doi),
        "online_date": publication_date,
        "coverdate": publication_date,
        "volume": str(item.get("volume", "") or "") or None,
        "issue": str(item.get("issue", "") or "") or None,
        "startpage": startpage,
        "endpage": endpage,
        "needs_filter": journal["needs_filter"],
    }


def _fetch_crossref_journal(journal_key: str, max_entries: int | None = None) -> list[dict]:
    """Fetch papers via Crossref when RSS is blocked or incomplete."""
    import requests

    issn = _CROSSREF_ISSN.get(journal_key)
    if not issn:
        print(f"[Crossref] No ISSN mapping for {journal_key}")
        return []

    journal = JOURNALS[journal_key]
    fetch_from = _crossref_fetch_from()
    if max_entries is None:
        max_entries = _CROSSREF_MAX_ROWS.get(journal_key, RSS_MAX_ENTRIES.get(journal_key, 50))

    papers_by_id: dict[str, dict] = {}
    filters = ("from-print-pub-date", "from-online-pub-date")

    for date_filter in filters:
        try:
            url = (
                f"https://api.crossref.org/works"
                f"?filter=issn:{issn},{date_filter}:{fetch_from}"
                f"&rows={max_entries}&sort=published&order=desc"
                f"&mailto=quant-marketing-daily@github.io"
            )
            resp = requests.get(url, timeout=20)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            print(f"[Crossref] API request failed for {journal_key} ({date_filter}): {e}")
            continue

        items = data.get("message", {}).get("items", [])
        if not items:
            print(f"[Crossref] No items returned for {journal_key} ({date_filter})")
            continue

        for item in items:
            paper = _crossref_item_to_paper(item, journal_key)
            if paper and paper["id"] not in papers_by_id:
                papers_by_id[paper["id"]] = paper

    papers = list(papers_by_id.values())
    print(f"[Crossref] {journal['name']} ({journal_key}): {len(papers)} papers from {fetch_from}")
    return papers


def _merge_papers_by_id(primary: list[dict], supplement: list[dict]) -> list[dict]:
    """Merge paper lists by id, preserving primary metadata first."""
    merged: dict[str, dict] = {}
    for paper in primary + supplement:
        pid = paper["id"]
        if pid not in merged:
            merged[pid] = paper
    return list(merged.values())


# ---------------------------------------------------------------------------
# 主解析函数
# ---------------------------------------------------------------------------
def parse_single_rss(journal_key: str, max_entries: int | None = None) -> list[dict]:
    """解析单个期刊 RSS，返回标准化 Paper 列表（不含摘要）。

    Paper dict:
        id, title, authors, journal, journal_full, publisher,
        doi, url, online_date, coverdate, volume, issue, startpage, endpage,
        needs_filter
    """
    if journal_key not in JOURNALS:
        raise ValueError(f"Unknown journal key: {journal_key}")

    journal = JOURNALS[journal_key]
    if max_entries is None:
        max_entries = RSS_MAX_ENTRIES.get(journal_key, 40)

    papers = []

    try:
        import requests

        resp = requests.get(
            journal["rss"],
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/131.0.0.0 Safari/537.36"
                ),
                "Accept": "application/rss+xml, application/xml, text/xml, */*",
                "Accept-Language": "en-US,en;q=0.9",
                "Accept-Encoding": "gzip, deflate, br",
                "Connection": "keep-alive",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
                "Sec-Fetch-User": "?1",
                "Cache-Control": "max-age=0",
            },
            timeout=30,
        )
        resp.raise_for_status()
        feed = feedparser.parse(resp.text)
    except Exception as e:
        print(f"[WARN] RSS fetch failed for {journal_key}: {e}")
        return papers

    for entry in feed.entries[:max_entries]:
        title = _clean_html(entry.get("title", "")).strip()
        if not title or _is_non_paper(title):
            continue

        doi = _extract_doi(entry)
        authors = _extract_authors(entry)
        meta = _extract_structured_meta(entry)
        online_date = _parse_online_date(entry)
        coverdate = _parse_coverdate(entry)

        paper = {
            "id": _paper_id(doi, title, journal_key),
            "title": title,
            "authors": authors,
            "abstract": None,  # 由 scraper/ 从详情页抓取
            "abstract_missing": False,  # 抓取失败标记
            "journal": journal_key,
            "journal_full": journal["name"],
            "publisher": journal["publisher"],
            "doi": doi,
            "url": doi_to_url(doi) if doi else entry.get("link", ""),
            "online_date": online_date,
            "coverdate": coverdate,
            "volume": meta.get("volume"),
            "issue": meta.get("issue"),
            "startpage": meta.get("startpage"),
            "endpage": meta.get("endpage"),
            "needs_filter": journal["needs_filter"],
        }
        papers.append(paper)

    return papers


def fetch_all_rss() -> list[dict]:
    """获取所有期刊 RSS，返回合并后的论文列表（不含摘要）。

    Sage/INFORMS RSS 在 CI 中可能被 Cloudflare/出版商策略拦截，
    此时自动回退到 Crossref API；GitHub Actions 上额外用 Crossref
    补充 RSS，避免 RSS 局部缺失导致整刊/整期漏报。
    """
    all_papers = []
    is_ci = os.environ.get("GITHUB_ACTIONS") == "true" or os.environ.get("CI") == "true"

    for key, cfg in JOURNALS.items():
        if not cfg.get("rss"):
            continue  # SSRN 无 RSS，走独立 fetch

        papers = parse_single_rss(key)
        source = "RSS"

        if not papers and key in _CROSSREF_ISSN:
            papers = _fetch_crossref_journal(key)
            source = "Crossref"
        elif papers and is_ci and key in _CROSSREF_ISSN:
            crossref_papers = _fetch_crossref_journal(key)
            if crossref_papers:
                before = len(papers)
                papers = _merge_papers_by_id(papers, crossref_papers)
                source = f"RSS+Crossref ({before}+{len(crossref_papers)}→{len(papers)})"

        if papers:
            print(f"[{source}] {cfg['name']} ({key}): {len(papers)} papers")
        else:
            print(f"[{source}] {cfg['name']} ({key}): 0 papers")
        all_papers.extend(papers)
    return all_papers
