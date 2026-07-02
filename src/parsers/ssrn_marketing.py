"""
Scrape SSRN Marketing eJOURNAL for newly posted working papers.

SSRN's Marketing eJOURNAL aggregates working papers in quantitative
marketing, consumer behavior, and marketing strategy.  We scrape the
abstract page listing and follow links to extract metadata.

Strategy:
  1. Fetch the journal's recent-papers listing page.
  2. Extract each paper's abstract page link.
  3. For each link, scrape title / authors / abstract / date.
  4. Return standardised Paper dicts.
"""

import hashlib
import re
import time
from datetime import datetime
from typing import Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from src.config import SSRN_URL

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
}

TIMEOUT = 30


def _get_soup(url: str) -> Optional[BeautifulSoup]:
    """Fetch a URL and return a BeautifulSoup object."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"[SSRN] request failed for {url}: {e}")
        return None
    return BeautifulSoup(resp.text, "html.parser")


def _abs_url_to_id(url: str) -> str:
    """Extract SSRN paper id from abstract URL."""
    m = re.search(r"abstract_id[=:](\d+)", url)
    if m:
        return f"ssrn:{m.group(1)}"
    m = re.search(r"/sol3/papers\.cfm\?abstract_id=(\d+)", url)
    if m:
        return f"ssrn:{m.group(1)}"
    m = re.search(r"abstract[=:](\d+)", url)
    if m:
        return f"ssrn:{m.group(1)}"
    return hashlib.sha256(url.encode()).hexdigest()[:16]


def _parse_ssrn_date(raw: str) -> str:
    """Convert SSRN date strings like 'Posted: 15 Jun 2026' to YYYY-MM-DD."""
    raw = raw.lower().replace("posted:", "").replace("last revised:", "").strip()
    for fmt in ("%d %b %Y", "%b %d %Y", "%Y-%m-%d", "%d %B %Y"):
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return datetime.now().strftime("%Y-%m-%d")


def fetch_listing_urls(listing_url: str = SSRN_URL, max_papers: int = 30) -> list[str]:
    """
    Scrape the journal listing page and return abstract-page URLs.

    SSRN changed their layout a few times; this function tries
    multiple selectors to stay robust.
    """
    soup = _get_soup(listing_url)
    if soup is None:
        print("[SSRN] could not fetch listing page — journal may have moved")
        return []

    urls = set()

    selectors = [
        'a[href*="abstract_id"]',
        'a[href*="abstract="]',
        'a[href*="/sol3/papers.cfm?abstract_id="]',
        ".paperlist-title a",
        'a[href*="papers.ssrn.com/sol3/papers.cfm"]',
        "h2 a",
        "h3 a",
        ".title a",
    ]

    for sel in selectors:
        for a in soup.select(sel):
            href = a.get("href", "")
            if "abstract_id" in href or "abstract=" in href:
                abs_url = urljoin(listing_url, href)
                urls.add(abs_url)
            if len(urls) >= max_papers:
                break
        if len(urls) >= max_papers:
            break

    result = list(urls)[:max_papers]
    print(f"[SSRN] found {len(result)} paper URLs on listing page")
    return result


def scrape_single_paper(abstract_url: str) -> Optional[dict]:
    """Scrape a single SSRN abstract page for metadata."""
    soup = _get_soup(abstract_url)
    if soup is None:
        return None

    title_el = soup.select_one("h1") or soup.select_one(".title") or soup.select_one("meta[name='citation_title']")
    title = ""
    if title_el:
        title = title_el.get("content", "") if title_el.name == "meta" else title_el.get_text(strip=True)
    if not title:
        return None

    authors = []
    author_els = soup.select("meta[name='citation_author']")
    if author_els:
        authors = [a.get("content", "") for a in author_els if a.get("content")]
    if not authors:
        author_spans = soup.select(".authors span") or soup.select(".author-name")
        authors = [a.get_text(strip=True) for a in author_spans if a.get_text(strip=True)]

    abstract = ""
    abs_meta = soup.select_one("meta[name='citation_abstract']") or soup.select_one("meta[name='description']")
    if abs_meta:
        abstract = abs_meta.get("content", "")
    if not abstract:
        abs_div = soup.select_one(".abstract-text") or soup.select_one("[class*='abstract']")
        if abs_div:
            abstract = abs_div.get_text("\n", strip=True)

    date_str = datetime.now().strftime("%Y-%m-%d")
    date_el = soup.select_one("meta[name='citation_publication_date']") or soup.select_one("meta[name='citation_online_date']")
    if date_el:
        date_str = date_el.get("content", date_str)

    doi_el = soup.select_one("meta[name='citation_doi']")
    doi = doi_el.get("content") if doi_el else None

    paper_id = _abs_url_to_id(abstract_url)

    return {
        "id": paper_id,
        "title": title,
        "authors": authors,
        "abstract": abstract if abstract else None,
        "journal": "SSRN",
        "journal_full": "SSRN Marketing eJOURNAL",
        "publisher": "SSRN",
        "url": abstract_url,
        "online_date": date_str,
        "coverdate": date_str,
        "published": date_str,
        "source": "ssrn",
        "doi": doi,
        "needs_filter": False,
    }


def fetch_ssrn(max_papers: int = 30) -> list[dict]:
    """Main entry: fetch recent papers from SSRN Marketing eJOURNAL."""
    urls = fetch_listing_urls(max_papers=max_papers)
    if not urls:
        return []

    papers = []
    for url in urls:
        paper = scrape_single_paper(url)
        if paper:
            papers.append(paper)
        time.sleep(1.5)

    print(f"[SSRN] successfully scraped {len(papers)} papers")
    return papers
