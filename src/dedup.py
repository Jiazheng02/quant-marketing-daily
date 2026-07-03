"""
DOI 去重 + seen 注册表 + 统一日期窗口过滤。

日期窗口规则（需求 §3.2）：
  当月前 7 天 → fetch_from = 上月1号
  否则        → fetch_from = 今天 - 30天
"""

import json
import os
from datetime import datetime, timedelta

from src.config import TZ, SEEN_DOIS_FILE, JOURNALS


# ---------------------------------------------------------------------------
# seen_dois 注册表
# ---------------------------------------------------------------------------
def load_seen() -> dict[str, str]:
    if not os.path.exists(SEEN_DOIS_FILE):
        return {}
    with open(SEEN_DOIS_FILE, "r") as f:
        return json.load(f)


def save_seen(seen: dict[str, str]) -> None:
    os.makedirs(os.path.dirname(SEEN_DOIS_FILE), exist_ok=True)
    with open(SEEN_DOIS_FILE, "w") as f:
        json.dump(seen, f, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# 日期窗口计算
# ---------------------------------------------------------------------------
def compute_fetch_from() -> str:
    """计算日期窗口起点（Asia/Shanghai 时区）。"""
    today = datetime.now(TZ)
    if today.day <= 7:
        # 当月前 7 天 → 从上月 1 号开始
        first_of_month = today.replace(day=1)
        last_month = first_of_month - timedelta(days=1)
        fetch_from = last_month.replace(day=1)
    else:
        fetch_from = today - timedelta(days=30)

    return fetch_from.strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# DOI 去重（同一次运行内）
# ---------------------------------------------------------------------------
def deduplicate(papers: list[dict]) -> list[dict]:
    """同一次运行内按 DOI 去重（保留第一次出现）。"""
    seen: dict[str, dict] = {}
    for p in papers:
        pid = p["id"]
        if pid not in seen:
            seen[pid] = p

    count = len(papers)
    unique = list(seen.values())
    if count > len(unique):
        print(f"[DEDUP] {count} raw → {len(unique)} unique (removed {count - len(unique)})")
    return unique


# ---------------------------------------------------------------------------
# seen + date 预过滤
# ---------------------------------------------------------------------------
def filter_seen_and_date(papers: list[dict], ignore_seen: bool = False) -> list[dict]:
    """seen 注册表 + 日期窗口联合预过滤。

    在摘要抓取之前执行，减少 HTTP / AI 成本。
    返回的新论文列表即候选论文。
    """
    seen_registry = {} if ignore_seen else load_seen()
    fetch_from = compute_fetch_from()

    candidates = []
    seen_dropped = 0
    date_dropped = 0

    for p in papers:
        pid = p["id"]

        # seen 过滤
        if not ignore_seen and pid in seen_registry:
            seen_dropped += 1
            continue

        # date 过滤
        od = p.get("online_date", "")
        if od and od < fetch_from:
            date_dropped += 1
            continue

        candidates.append(p)

    total = len(papers)
    mode = "ignored" if ignore_seen else str(seen_dropped)
    print(f"[PRE-FILTER] {total} → {len(candidates)} candidates (seen: {mode}, date: {date_dropped})")
    return candidates


# ---------------------------------------------------------------------------
# 30 篇 relevance-first 截断
# ---------------------------------------------------------------------------
def truncate_papers(
    papers: list[dict], max_count: int = 30
) -> tuple[list[dict], int]:
    """按 quant relevance 优先截断。

    排序：有 online_date → quant relevance → 期刊优先级 → online_date 降 →
    MngSci 营销 tie-breaker → 标题字母序

    quant relevance 使用标题级信号，确保真正相关的 quant paper 在摘要抓取前
    不会被 behavioral/psych paper 挤出 30 篇候选上限。
    """
    if len(papers) <= max_count:
        return papers, 0

    priority = {k: j["priority"] for k, j in JOURNALS.items()}

    # 延迟导入，避免循环依赖
    from src.filter_mngsci import mngsci_marketing_boost
    from src.relevance import paper_relevance_sort_key

    def sort_key(p: dict):
        od = p.get("online_date", "")
        if od:
            parts = od.split("-")
            date_tuple = (-int(parts[0]), -int(parts[1]), -int(parts[2]))
        else:
            date_tuple = (0, 0, 0)
        relevance_key = paper_relevance_sort_key(p, include_abstract=False)
        prio = priority.get(p.get("journal", ""), 99)
        boost = mngsci_marketing_boost(p)
        title = p.get("title", "")
        return (0 if od else 1, relevance_key, prio, date_tuple, boost, title)

    sorted_papers = sorted(papers, key=sort_key)
    truncated = sorted_papers[:max_count]
    dropped = len(papers) - max_count

    print(f"[TRUNCATE] {len(papers)} → {max_count} (dropped {dropped})")
    return truncated, dropped


# ---------------------------------------------------------------------------
# 注册表提交（管线成功后调用）
# ---------------------------------------------------------------------------
def commit_seen(papers: list[dict]) -> None:
    """将论文 ID 写入 seen 注册表（包含摘要失败但保留的论文）。"""
    seen = load_seen()
    today = datetime.now(TZ).strftime("%Y-%m-%d")
    cutoff = (datetime.now(TZ) - timedelta(days=90)).strftime("%Y-%m-%d")

    pruned = {k: v for k, v in seen.items() if v >= cutoff}
    added = 0
    for p in papers:
        pid = p["id"]
        if pid not in pruned:
            pruned[pid] = today
            added += 1

    save_seen(pruned)
    print(f"[SEEN] committed {added} new DOIs to registry (total: {len(pruned)})")
