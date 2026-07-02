"""
MktSci 待人工/云端补抓队列处理器。

此脚本供 AI 助手运行，自动化以下流程：
  1. 读取 data/pending_mktsci.json
  2. 输出每个待处理 DOI 的 INFORMS 原文页
  3. 复用 INFORMS 页面解析器从 HTML 中提取摘要文本
  4. 调用 enrich_mktsci.py --add 写入缓存
  5. 清空 pending_mktsci.json

用法:
  python -m src.process_pending
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.scraper.informs import (
    load_mktsci_cache,
    get_pending_mktsci,
    clear_pending_mktsci,
)


def process_pending() -> None:
    """处理所有待抓取的 MktSci DOIs。"""
    pending = get_pending_mktsci()
    if not pending:
        print("✅ 无待处理的 MktSci DOIs")
        return
    
    cache = load_mktsci_cache()
    uncached = [d for d in pending if d not in cache]
    
    if not uncached:
        print("✅ 所有待处理 DOIs 已缓存，清空待处理队列。")
        clear_pending_mktsci()
        return
    
    print(f"📋 发现 {len(uncached)} 个待抓取的 MktSci DOIs:")
    print()
    
    # 输出可直接复制的 URLs 列表
    print("=" * 60)
    print("可直接复制到浏览器/WebFetch 的 URLs:")
    print("=" * 60)
    for doi in uncached:
        url = f"https://pubsonline.informs.org/doi/abs/{doi}"
        print(url)
    print("=" * 60)
    print()
    
    # 详细列表
    for doi in uncached:
        url = f"https://pubsonline.informs.org/doi/abs/{doi}"
        print(f"  [{uncached.index(doi) + 1}/{len(uncached)}] {doi}")
        print(f"  URL: {url}")
        print()
    
    print("=" * 60)
    print("处理步骤:")
    print("=" * 60)
    print("1. 复制上述 URLs")
    print("2. 使用浏览器、WorkBuddy WebFetch 或其他云端工具抓取每个 URL")
    print("3. 从返回内容中提取完整摘要")
    print("4. 运行以下命令写入缓存:")
    print()
    for doi in uncached:
        print(f"   python -m src.enrich_mktsci --add \"{doi}\" \"<完整摘要>\"")
    print()
    print("=" * 60)


if __name__ == "__main__":
    process_pending()
