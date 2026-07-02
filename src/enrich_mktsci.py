"""
MktSci 完整摘要缓存管理器。

pubsonline.informs.org 有 Cloudflare Turnstile 防护。主管线会先用 Scrapling
做 best-effort 自动补抓；失败后 DOI 会进入 pending 队列。

工作流：
  1. 管线运行后，短摘要的 MktSci DOIs 自动写入 data/pending_mktsci.json
  2. 使用浏览器/WebFetch/其他云端工具逐个抓取 pubsonline.informs.org/doi/abs/{doi} 的完整摘要
  3. 调用本脚本 `python -m src.enrich_mktsci --add <doi> "<abstract>"` 写入缓存
  4. 调用 `python -m src.enrich_mktsci --regenerate 2026-07-02` 重新渲染日报

使用示例：
  # 查看待处理列表
  python -m src.enrich_mktsci --list

  # 添加一篇论文的完整摘要
  python -m src.enrich_mktsci --add "10.1287/mksc.2024.1138" "Full abstract text here..."

  # 所有待处理 DOI 已写入缓存后，重新生成日报
  python -m src.enrich_mktsci --regenerate 2026-07-02
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.scraper.informs import (
    load_mktsci_cache,
    save_to_mktsci_cache,
    get_pending_mktsci,
    clear_pending_mktsci,
)
from src.config import today_str


def cmd_list() -> None:
    """列出待人工或云端补抓的 DOI 及其页面 URL。"""
    pending = get_pending_mktsci()
    if not pending:
        print("No pending MktSci DOIs — all abstracts are complete.")
        return

    print(f"Pending MktSci DOIs ({len(pending)}):")
    print()
    for doi in pending:
        url = f"https://pubsonline.informs.org/doi/abs/{doi}"
        print(f"  {doi}")
        print(f"  → {url}")
        print()

    cache = load_mktsci_cache()
    cached = set(cache.keys())
    uncached = [d for d in pending if d not in cached]
    if uncached:
        print(f"{len(uncached)} DOIs not yet in cache — use browser/WebFetch on each URL above.")
    else:
        print("All pending DOIs are cached! Run --regenerate to update the report.")


def cmd_add(doi: str, abstract: str) -> None:
    """手动添加一篇论文的完整摘要到缓存。"""
    if not abstract or len(abstract.strip()) < 100:
        print(f"ERROR: abstract too short ({len(abstract)} chars). "
              f"Expected >= 100 chars for a meaningful abstract.")
        return

    save_to_mktsci_cache(doi, abstract)
    print(f"Added to cache: {doi} ({len(abstract)} chars)")

    # 检查是否所有待处理 DOI 都已缓存
    pending = get_pending_mktsci()
    cache = load_mktsci_cache()
    uncached = [d for d in pending if d not in cache]
    if not uncached:
        print("\nAll pending DOIs are now cached! Run --regenerate to update the report.")
    else:
        print(f"\n{len(uncached)} DOIs still pending: {uncached}")


def cmd_regenerate(date_str: str | None = None) -> None:
    """使用最新缓存重新渲染日报。"""
    if not date_str:
        date_str = today_str()

    # 重新运行渲染流程
    from src.dedup import filter_seen_and_date, deduplicate, truncate_papers
    from src.parsers.rss_journals import fetch_all_rss
    from src.scraper.abstract import scrape_abstracts
    from src.filter_mngsci import filter_mngsci
    from src.abstract import process_abstract
    from src.render import render_markdown, save_report
    from src.config import MAX_CANDIDATE_PAPERS

    print(f"Re-running pipeline for {date_str} with updated MktSci cache...")
    print()

    # [1] RSS 发现
    papers = fetch_all_rss()
    print(f"[1] RSS: {len(papers)} raw papers")

    # [2-3] 去重 + 过滤
    papers = deduplicate(papers)
    candidates = filter_seen_and_date(papers)
    candidates, _ = truncate_papers(candidates, MAX_CANDIDATE_PAPERS)
    print(f"[2-3] {len(candidates)} candidates after dedup + date filter")

    # [4] 摘要抓取（这次会命中 MktSci 缓存）
    candidates = scrape_abstracts(candidates)
    print(f"[4] abstracts scraped")

    # [5-6] MngSci 过滤 + DeepSeek 摘要
    candidates = filter_mngsci(candidates)
    candidates = process_abstract(candidates)
    print(f"[5-6] filtered + abstract processed: {len(candidates)} papers")

    # [7] 渲染
    md = render_markdown(candidates)
    path = save_report(md, date_str=date_str)

    print(f"\nReport regenerated: {path}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="MktSci full abstract cache manager & report regenerator"
    )
    parser.add_argument(
        "--list", action="store_true",
        help="List pending MktSci DOIs that need manual/cloud full-abstract fetch"
    )
    parser.add_argument(
        "--add", nargs=2, metavar=("DOI", "ABSTRACT"),
        help="Add a full abstract to the cache: DOI 'abstract text'"
    )
    parser.add_argument(
        "--regenerate", nargs="?", const="", metavar="DATE",
        help="Regenerate the report with updated MktSci abstracts (default: today)"
    )
    parser.add_argument(
        "--clear-pending", action="store_true",
        help="Clear the pending DOIs list (after all have been cached)"
    )

    args = parser.parse_args()

    if args.list:
        cmd_list()
    elif args.add:
        cmd_add(args.add[0], args.add[1])
    elif args.regenerate is not None:
        cmd_regenerate(args.regenerate)
    elif args.clear_pending:
        clear_pending_mktsci()
        print("Pending DOIs list cleared.")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
