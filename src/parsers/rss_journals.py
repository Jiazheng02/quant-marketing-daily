"""
RSS 解析 — 五大期刊元数据提取（不含摘要）。

双日期模型：
  online_date  — 过滤用（updated > published > prism_coverdate > ""）
  coverdate    — 展示用（prism_coverdate）

RSS 仅发现论文；摘要从出版商详情页抓取（见 scraper/）。
"""

import hashlib
import re
from datetime import datetime
from typing import Optional

import feedparser

from src.config import JOURNALS, RSS_MAX_ENTRIES, today_str

# INFORMS journals ISSN mapping (Crossref fallback when RSS blocked by Cloudflare)
_INFORMS_ISSN = {
    "MktSci": "0732-2399",
    "MngSci": "0025-1909",
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
# Crossref 回退（INFORMS RSS 被 Cloudflare 403 时使用）
# ---------------------------------------------------------------------------

def _fetch_informs_crossref(journal_key: str, max_entries: int = 50) -> list[dict]:
    """Fetch INFORMS papers via Crossref API when RSS is blocked by Cloudflare."""
    import requests

    issn = _INFORMS_ISSN.get(journal_key)
    if not issn:
        print(f"[Crossref] No ISSN mapping for {journal_key}")
        return []

    journal = JOURNALS[journal_key]
    today = today_str()

    try:
        url = (
            f"https://api.crossref.org/works"
            f"?filter=issn:{issn},from-pub-date:2026-06-01"
            f"&rows={max_entries}&sort=published&order=desc"
            f"&mailto=quant-marketing-daily@github.io"
        )
        resp = requests.get(url, timeout=20)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"[Crossref] API request failed for {journal_key}: {e}")
        return []

    items = data.get("message", {}).get("items", [])
    if not items:
        print(f"[Crossref] No items returned for {journal_key}")
        return []

    papers = []
    for item in items:
        doi = item.get("DOI", "").strip()
        if not doi:
            continue

        title_list = item.get("title", [])
        title = title_list[0].strip() if title_list else ""
        if not title:
            title = item.get("original-title", [None])[0] or ""

        if not title or not doi:
            continue

        # Authors
        authors = []
        for a in item.get("author", []):
            given = a.get("given", "")
            family = a.get("family", "")
            name = f"{given} {family}".strip()
            if name:
                authors.append(name)

        # Dates
        pub_date = item.get("published-print", {}).get("date-parts", [[None]])[0]
        online_date_parts = item.get("published-online", {}).get("date-parts", [[None]])[0]
        created_date = item.get("created", {}).get("date-parts", [[None]])[0]

        def _fmt_date(parts):
            if parts and parts[0]:
                return f"{parts[0]:04d}-{parts[1]:02d}-{parts[2]:02d}" if len(parts) >= 3 else ""
            return ""

        coverdate = _fmt_date(pub_date or online_date_parts or created_date)
        online_date = _fmt_date(online_date_parts or pub_date or created_date)

        # Volume / issue / pages
        volume = str(item.get("volume", "") or "")
        issue = str(item.get("issue", "") or "")
        page = item.get("page", "")

        paper = {
            "id": _paper_id(doi, title, journal_key),
            "title": _clean_html(title),
            "authors": authors,
            "abstract": None,
            "abstract_missing": False,
            "journal": journal_key,
            "journal_full": journal["name"],
            "publisher": journal["publisher"],
            "doi": doi,
            "url": doi_to_url(doi),
            "online_date": online_date,
            "coverdate": coverdate,
            "volume": volume or None,
            "issue": issue or None,
            "startpage": None,
            "endpage": None,
            "needs_filter": journal["needs_filter"],
        }
        papers.append(paper)

    print(f"[Crossref] {journal['name']} ({journal_key}): {len(papers)} papers")
    return papers


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

    INFORMS 期刊的 RSS 在 CI 中可能被 Cloudflare 403 拦截，
    此时自动回退到 Crossref API。
    """
    all_papers = []
    for key, cfg in JOURNALS.items():
        if not cfg.get("rss"):
            continue  # SSRN 无 RSS，走独立 fetch

        papers = parse_single_rss(key)
        source = "RSS"

        # INFORMS RSS blocked by Cloudflare → fallback to Crossref
        if not papers and cfg["publisher"] == "INFORMS":
            papers = _fetch_informs_crossref(key)
            source = "Crossref"

        if papers:
            print(f"[{source}] {cfg['name']} ({key}): {len(papers)} papers")
        else:
            print(f"[{source}] {cfg['name']} ({key}): 0 papers")
        all_papers.extend(papers)
    return all_papers
