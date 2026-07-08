#!/usr/bin/env python3
"""
Quant Marketing Daily — 主入口。

10 步管线（+ 前后诊断检查）：
  [1] RSS/Crossref 发现 → 论文元数据（不含摘要）
  [2] DOI 标准化 + 去重（同一次运行内）
  [3] seen + date 预过滤
  [4] 候选池 relevance-first 截断
  [5] 摘要抓取 → 从出版商详情页 HTML 提取
  [6] MngSci → Marketing accepted_by + 关键词兜底过滤（先过滤减少 LLM 工作量）
  [7] 标题翻译 → 中文译名（LLM batch）
  [8] Abstract 处理 → 一句话总结 + 完整中文翻译（LLM per-paper）
  [9] 渲染 + 保存 Markdown
  [10] 成功后 commit seen_dois

  诊断：管线前后各检查一次 MktSci 待抓取队列，如有 pending DOI 则输出提示

用法:
  python -m src.fetch                  # 正常模式
  python -m src.fetch --dry-run        # 仅 RSS/Crossref + 去重 + 日期过滤 + relevance 截断，不抓摘要/不写 seen
  python -m src.fetch --rebuild        # 忽略 seen 重建今天日报，不写 seen
  python -m src.fetch --include-ssrn   # P0 + SSRN（P2 功能）

时区：Asia/Shanghai（需求 §2.1）
"""

import argparse
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import today_str, MAX_CANDIDATE_PAPERS
from src.parsers.rss_journals import fetch_all_rss
from src.dedup import (
    deduplicate,
    filter_seen_and_date,
    truncate_papers,
    commit_seen,
)
from src.scraper.abstract import scrape_abstracts
from src.translate import translate_titles
from src.filter_mngsci import filter_mngsci
from src.abstract import process_abstract
from src.render import render_markdown, save_report


def main() -> None:
    parser = argparse.ArgumentParser(description="Quant Marketing Daily")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="仅 RSS/Crossref 解析 + 去重 + 日期过滤 + relevance 截断，不抓摘要、不写 seen_dois、不产日报",
    )
    parser.add_argument(
        "--include-ssrn",
        action="store_true",
        help="追加 SSRN Working Papers（P2，默认关闭）",
    )
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="忽略 seen_dois 重建当日窗口日报；不提交 seen_dois",
    )
    args = parser.parse_args()

    print("=" * 60)
    mode = "DRY-RUN" if args.dry_run else ("REBUILD" if args.rebuild else "NORMAL")
    print(f"Quant Marketing Daily — Pipeline [{mode}]")
    print(f"北京时间: {today_str()}")
    print("=" * 60)

    # =====================================================================
    # [0] 检查 MktSci 待抓取队列（在开始时就提醒）
    # =====================================================================
    _check_pending_mktsci()

    # =====================================================================
    # [1] RSS/Crossref 发现
    # =====================================================================
    print("\n[1/10] RSS/Crossref 发现 → 论文元数据（不含摘要）")
    papers = fetch_all_rss()
    print(f"  → {len(papers)} raw papers")

    if args.include_ssrn:
        # P2: SSRN
        try:
            from src.parsers.ssrn_marketing import fetch_ssrn
            ssrn = fetch_ssrn(max_papers=30)
            if ssrn:
                print(f"  + {len(ssrn)} SSRN papers")
                papers.extend(ssrn)
        except Exception as e:
            print(f"  [WARN] SSRN fetch failed: {e}")

    if not papers:
        print("  → 无 RSS/Crossref 数据，终止。")
        return

    # =====================================================================
    # [2] DOI 去重
    # =====================================================================
    print("\n[2/10] DOI 标准化 + 去重")
    papers = deduplicate(papers)

    # =====================================================================
    # [3] seen + date 预过滤
    # =====================================================================
    print("\n[3/10] seen + date 预过滤")
    candidates = filter_seen_and_date(papers, ignore_seen=args.rebuild)

    if not candidates:
        print("  → 无新候选论文。")
        if args.dry_run:
            print("[DRY-RUN] 管线在此结束（不产日报/不写 seen）。")
            return
        _render_empty()
        return

    # =====================================================================
    # [4] relevance-first 截断（候选上限由 MAX_CANDIDATE_PAPERS 控制）
    # =====================================================================
    candidates, truncated = truncate_papers(candidates, MAX_CANDIDATE_PAPERS)

    # =====================================================================
    # Dry-run: 在此停止
    # =====================================================================
    if args.dry_run:
        print("\n" + "=" * 60)
        print(f"[DRY-RUN] 候选论文 ({len(candidates)} 篇):")
        for i, p in enumerate(candidates):
            print(f"  {i + 1}. [{p['journal']}] {p['title'][:80]}")
            print(f"     online_date={p.get('online_date', '(none)')}  "
                  f"coverdate={p.get('coverdate', '(none)')}  "
                  f"doi={p.get('doi', '(none)')}")
        if truncated:
            print(f"  (另有 {truncated} 篇被截断)")
        print("\n[Dry-run] 管线在此结束（不抓摘要/不写 seen/不产日报）。")
        print("确认 RSS 数据无误后，运行 python -m src.fetch 进入正式模式。")
        return

    # =====================================================================
    # [5] 摘要抓取
    # =====================================================================
    print(f"\n[5/10] 摘要抓取（{len(candidates)} 篇候选）")
    candidates = scrape_abstracts(candidates)

    # =====================================================================
    # [6] MngSci accepted_by + 关键词兜底过滤（先过滤，减少 LLM 翻译/摘要开销）
    # =====================================================================
    print("\n[6/10] MngSci → Marketing accepted_by + 关键词兜底过滤")
    candidates = filter_mngsci(candidates)

    # =====================================================================
    # [7] 标题翻译
    # =====================================================================
    print(f"\n[7/10] 标题翻译 → 中文译名（{len(candidates)} 篇）")
    candidates = translate_titles(candidates)

    # =====================================================================
    # [8] AI 摘要（一句话 + 完整中文翻译）
    # =====================================================================
    print(f"\n[8/10] AI 摘要（{len(candidates)} 篇）")
    candidates = process_abstract(candidates)

    # =====================================================================
    # [9] 渲染 + 保存
    # =====================================================================
    print("\n[9/10] 渲染 Markdown")
    md = render_markdown(candidates)
    path = save_report(md, preserve_richer_existing=not args.rebuild)

    # =====================================================================
    # [10] commit seen_dois（成功后）
    # =====================================================================
    print("\n[10/10] 提交 seen_dois")
    if args.rebuild:
        print("[REBUILD] 跳过 seen_dois 写入，避免重建日报污染增量状态。")
    else:
        # 提交所有候选论文的 DOI（包含摘要失败的），避免每日重复抓取
        commit_seen(candidates)

    # =====================================================================
    # [11] 检查 MktSci 待抓取队列
    # =====================================================================
    _check_pending_mktsci()

    print("\n" + "=" * 60)
    print(f"完成! 日报: {path}")
    print("=" * 60)


def _check_pending_mktsci() -> None:
    """检查 MktSci 待抓取队列，输出提示信息。"""
    try:
        from src.scraper.informs import get_pending_mktsci, load_mktsci_cache
        
        pending = get_pending_mktsci()
        if not pending:
            return
        
        cache = load_mktsci_cache()
        uncached = [d for d in pending if d not in cache]
        
        if not uncached:
            # 所有待处理 DOI 已缓存，清空待处理列表
            from src.scraper.informs import clear_pending_mktsci
            clear_pending_mktsci()
            print("[MktSci] 所有待处理摘要已缓存，已清空待处理队列。")
            return
        
        print(f"\n⚠️  MktSci 完整摘要待抓取 ({len(uncached)} 篇):")
        print("=" * 60)
        print("以下论文的摘要不完整（Crossref 只有一句话，Scrapling 自动补抓失败），需要人工/云端补完整版本：")
        print()
        for doi in uncached:
            url = f"https://pubsonline.informs.org/doi/abs/{doi}"
            print(f"  DOI: {doi}")
            print(f"  URL: {url}")
        print()
        print("处理选项：")
        print("  1. 运行 `python -m src.process_pending` 查看可直接复制的 URLs")
        print("  2. 将 URLs 提供给 AI 助手，使用浏览器/WebFetch 抓取完整摘要")
        print("  3. 运行 `python -m src.enrich_mktsci --add DOI \"完整摘要\"` 写入缓存后重新运行管线")
        print("=" * 60)
        
    except Exception as e:
        print(f"[WARN] 检查 MktSci 待抓取队列失败: {e}")


def _render_empty() -> None:
    """渲染空日报（今日无新论文）。"""
    md = render_markdown([])
    path = save_report(md)
    print("\n" + "=" * 60)
    print(f"完成!（今日无新论文） 日报: {path}")
    print("=" * 60)


if __name__ == "__main__":
    main()
