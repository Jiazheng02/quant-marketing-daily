"""
INFORMS article-page extraction helpers.

This module is deliberately optional at runtime: if Scrapling or a browser
backend is unavailable, callers should keep using Crossref/S2 fallbacks.
"""

from __future__ import annotations

import html
import os
import re
from typing import Any

from bs4 import BeautifulSoup
from dotenv import load_dotenv


MIN_FULL_ABSTRACT_LENGTH = 200
_ENV_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    ".env",
)
load_dotenv(_ENV_PATH)

INFORMS_PAGE_TIMEOUT_MS = int(os.environ.get("INFORMS_PAGE_TIMEOUT_MS", "25000"))
INFORMS_USE_STEALTH = os.environ.get("INFORMS_USE_STEALTH", "0").strip().lower() in {
    "1",
    "true",
    "yes",
}
INFORMS_STEALTH_HEADLESS = os.environ.get("INFORMS_STEALTH_HEADLESS", "1").strip().lower() not in {
    "0",
    "false",
    "no",
}
INFORMS_SOLVE_CLOUDFLARE = os.environ.get("INFORMS_SOLVE_CLOUDFLARE", "0").strip().lower() in {
    "1",
    "true",
    "yes",
}
INFORMS_REAL_CHROME = os.environ.get("INFORMS_REAL_CHROME", "1").strip().lower() not in {
    "0",
    "false",
    "no",
}
INFORMS_USER_DATA_DIR = os.environ.get("INFORMS_USER_DATA_DIR", "").strip()

_ABSTRACT_HEADING_RE = re.compile(r"^\s*abstract\s*$", re.IGNORECASE)
_BOUNDARY_RE = re.compile(
    r"\b(?:History|Funding|Supplemental Material|Back to Top|Article Information|"
    r"Figures|References|Related|Metrics|Information|Cite as)\b",
    re.IGNORECASE,
)
_PW_PROFILE_DIR = os.environ.get("INFORMS_PW_PROFILE_DIR", "").strip() or os.path.join(
    os.path.dirname(_ENV_PATH),
    "data",
    ".pw-profile",
)
_PW_HEADLESS = os.environ.get("INFORMS_PW_HEADLESS", "1").strip().lower() not in {
    "0", "false", "no",
}

_BAD_PAGE_RE = re.compile(
    r"\b(?:cloudflare|turnstile|checking your browser|request username|login to your account)\b",
    re.IGNORECASE,
)


def extract_informs_abstract_from_html(
    html_text: str | bytes | None,
    min_length: int = MIN_FULL_ABSTRACT_LENGTH,
) -> str | None:
    """Extract a full article abstract from an INFORMS article page."""
    if not html_text:
        return None

    if isinstance(html_text, bytes):
        html_text = html_text.decode("utf-8", errors="ignore")

    soup = BeautifulSoup(html_text, "lxml")

    for candidate in _metadata_candidates(soup):
        abstract = _clean_abstract(candidate)
        if _is_full_abstract(abstract, min_length):
            return abstract

    for candidate in _structured_candidates(soup):
        abstract = _clean_abstract(candidate)
        if _is_full_abstract(abstract, min_length):
            return abstract

    text = soup.get_text("\n", strip=True)
    abstract = _clean_abstract(_extract_from_text(text))
    if _is_full_abstract(abstract, min_length):
        return abstract

    return None


def fetch_full_abstract_with_scrapling(
    doi: str,
    min_length: int = MIN_FULL_ABSTRACT_LENGTH,
) -> str | None:
    """Best-effort INFORMS full-page fetch via Scrapling."""
    url = f"https://pubsonline.informs.org/doi/abs/{doi}"

    for fetch_name, fetch_call in _scrapling_fetchers(url):
        try:
            response = fetch_call()
        except Exception as exc:
            print(f"[INFORMS-page] {fetch_name} failed for {doi}: {exc}")
            continue

        status = getattr(response, "status", None)
        if isinstance(status, int) and status >= 400:
            print(f"[INFORMS-page] {fetch_name} returned HTTP {status} for {doi}")
            continue

        abstract = extract_informs_abstract_from_html(_response_html(response), min_length=min_length)
        if abstract:
            print(f"[INFORMS-page] full abstract via {fetch_name} for {doi} ({len(abstract)} chars)")
            return abstract

        print(f"[INFORMS-page] {fetch_name} did not expose a full abstract for {doi}")

    return None


def _scrapling_fetchers(url: str):
    try:
        from scrapling.fetchers import Fetcher
    except Exception as exc:
        print(f"[INFORMS-page] Scrapling unavailable: {exc}")
        return []

    fetchers = [
        (
            "scrapling-fetcher",
            lambda: Fetcher.get(
                url,
                impersonate="chrome",
                stealthy_headers=True,
                timeout=INFORMS_PAGE_TIMEOUT_MS // 1000,
            ),
        )
    ]

    if INFORMS_USE_STEALTH:
        try:
            from scrapling.fetchers import StealthyFetcher
        except Exception as exc:
            print(f"[INFORMS-page] Scrapling stealth unavailable: {exc}")
        else:
            stealth_kwargs = {
                "headless": INFORMS_STEALTH_HEADLESS,
                "real_chrome": INFORMS_REAL_CHROME,
                "solve_cloudflare": INFORMS_SOLVE_CLOUDFLARE,
                "network_idle": True,
                "timeout": INFORMS_PAGE_TIMEOUT_MS,
                "wait": 1000,
            }
            if INFORMS_USER_DATA_DIR:
                stealth_kwargs["user_data_dir"] = INFORMS_USER_DATA_DIR

            fetchers.append(
                (
                    "scrapling-stealth",
                    lambda: StealthyFetcher.fetch(url, **stealth_kwargs),
                )
            )

    return fetchers


def _metadata_candidates(soup: BeautifulSoup) -> list[str]:
    candidates: list[str] = []
    for selector in [
        'meta[name="citation_abstract"]',
        'meta[name="dc.Description"]',
        'meta[name="description"]',
        'meta[property="og:description"]',
    ]:
        node = soup.select_one(selector)
        if node and node.get("content"):
            candidates.append(str(node["content"]))
    return candidates


def _structured_candidates(soup: BeautifulSoup) -> list[str]:
    candidates: list[str] = []

    for selector in [
        ".abstractSection",
        ".article__abstract",
        ".hlFld-Abstract",
        "#abstract",
        "[id*='abstract' i]",
        "[class*='abstract' i]",
    ]:
        for node in soup.select(selector):
            text = _node_text(node)
            if text:
                candidates.append(text)

    for heading in soup.find_all(re.compile(r"^h[1-6]$")):
        if not _ABSTRACT_HEADING_RE.match(heading.get_text(" ", strip=True)):
            continue
        text = _text_after_heading(heading)
        if text:
            candidates.append(text)

    return candidates


def _node_text(node: Any) -> str:
    paragraphs = [p.get_text(" ", strip=True) for p in node.find_all("p") if p.get_text(" ", strip=True)]
    if paragraphs:
        return " ".join(paragraphs)
    return node.get_text(" ", strip=True)


def _text_after_heading(heading: Any) -> str:
    parts: list[str] = []
    for sibling in heading.next_siblings:
        name = getattr(sibling, "name", None)
        if name and re.match(r"^h[1-6]$", name):
            break

        text = sibling.get_text(" ", strip=True) if hasattr(sibling, "get_text") else str(sibling).strip()
        if not text:
            continue
        if _BOUNDARY_RE.search(text):
            boundary = _BOUNDARY_RE.search(text)
            if boundary and boundary.start() > 0:
                parts.append(text[: boundary.start()].strip())
            break
        parts.append(text)

    return " ".join(parts)


def _extract_from_text(text: str) -> str | None:
    match = re.search(
        r"(?:^|\n)\s*Abstract\s*\n(?P<body>.*?)(?:\n\s*(?:History|Funding|Supplemental Material|Back to Top|Article Information|Figures|References)\b)",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return None
    return match.group("body")


def _clean_abstract(text: str | None) -> str | None:
    if not text:
        return None

    text = html.unescape(text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"^Abstract\s*", "", text, flags=re.IGNORECASE).strip()

    boundary = _BOUNDARY_RE.search(text)
    if boundary:
        text = text[: boundary.start()].strip()

    return text or None


def _is_full_abstract(text: str | None, min_length: int) -> bool:
    if not text or len(text) < min_length:
        return False
    if _BAD_PAGE_RE.search(text):
        return False
    return True


def _response_html(response: Any) -> str:
    for attr in ("html_content", "text"):
        value = getattr(response, attr, None)
        if value:
            return str(value)

    body = getattr(response, "body", None)
    if isinstance(body, bytes):
        encoding = getattr(response, "encoding", "utf-8")
        return body.decode(encoding, errors="ignore")
    if body:
        return str(body)

    return str(response)


# ---------------------------------------------------------------------------
# Playwright with persistent Chrome profile
# ---------------------------------------------------------------------------

def fetch_mktsci_with_playwright(
    doi: str,
    min_length: int = MIN_FULL_ABSTRACT_LENGTH,
) -> str | None:
    """Fetch full MktSci abstract via Playwright + persistent Chrome profile.

    Uses ``launch_persistent_context`` so the ``cf_clearance`` cookie
    survives across runs.  First run with ``INFORMS_PW_HEADLESS=0``
    (visible browser) to complete Turnstile manually; subsequent headless
    runs reuse the saved cookie automatically.

    Returns the full abstract text, or ``None`` on failure.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        print(f"[INFORMS-pw] Playwright unavailable: {exc}")
        return None

    url = f"https://pubsonline.informs.org/doi/abs/{doi}"
    os.makedirs(_PW_PROFILE_DIR, exist_ok=True)
    print(f"[INFORMS-pw] Profile dir: {_PW_PROFILE_DIR}")
    print(f"[INFORMS-pw] Headless: {_PW_HEADLESS}")
    print(f"[INFORMS-pw] Going to: {url}")

    try:
        with sync_playwright() as pw:
            print(f"[INFORMS-pw] Launching persistent context...")
            context = pw.chromium.launch_persistent_context(
                _PW_PROFILE_DIR,
                headless=_PW_HEADLESS,
                args=[
                    "--no-sandbox",
                    "--disable-blink-features=AutomationControlled",
                ],
            )
            print(f"[INFORMS-pw] Context launched. Pages: {len(context.pages)}")
            page = context.pages[0] if context.pages else context.new_page()
            print(f"[INFORMS-pw] Page created. Going to URL...")

            page.goto(url, wait_until="domcontentloaded", timeout=INFORMS_PAGE_TIMEOUT_MS)
            print(f"[INFORMS-pw] Page loaded. Title: {page.title()}")

            # Cloudflare challenge check — only if title still shows challenge page
            page_title = page.title()
            content = page.content()
            is_cloudflare = _BAD_PAGE_RE.search(content) and page_title in (
                "Just a moment...",
                "Please wait...",
                "Checking your browser...",
            )
            if is_cloudflare:
                if _PW_HEADLESS:
                    print(
                        f"[INFORMS-pw] Cloudflare challenge detected (headless mode). "
                        f"Re-run with INFORMS_PW_HEADLESS=0 in .env to complete it manually."
                    )
                    context.close()
                    return None
                # visible mode — wait for challenge to clear (poll title change)
                print("[INFORMS-pw] Cloudflare detected. Waiting for clearance (up to 60 s)...")
                import time
                for i in range(120):  # 120 * 0.5s = 60 s
                    time.sleep(0.5)
                    title = page.title()
                    if title != "Just a moment..." and not _BAD_PAGE_RE.search(page.content()):
                        print(f"[INFORMS-pw] Cloudflare cleared. New title: {title}")
                        break
                else:
                    print("[INFORMS-pw] Timed out waiting for Cloudflare clearance.")
                    context.close()
                    return None

            html_content = page.content()
            abstract = extract_informs_abstract_from_html(html_content, min_length=min_length)
            context.close()

            if abstract:
                print(f"[INFORMS-pw] full abstract via Playwright for {doi} ({len(abstract)} chars)")
                return abstract

            print(f"[INFORMS-pw] Playwright returned page but no full abstract for {doi}")
            return None

    except Exception as exc:
        print(f"[INFORMS-pw] Playwright failed for {doi}: {exc}")
        return None
