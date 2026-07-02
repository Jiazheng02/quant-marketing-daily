"""
Management Science → Marketing Department 论文过滤。

策略：
  1. 优先：Crossref "This paper was accepted by XX, [department]"
     - 包含 "marketing" → 保留
     - 包含其他部门 → 丢弃
  2. 兜底：关键词比分（无 accepted-by 数据时）
     - pos - neg >= 2 → 保留
     - 否则 → 丢弃
  3. 不区分 confirmed/uncertain
"""

import re

# ---------------------------------------------------------------------------
# Accepted-by 部门识别
# ---------------------------------------------------------------------------

def _is_marketing_by_accepted(accepted_by: str) -> bool | None:
    """从 accepted-by 文本判断是否为 Marketing 部门。

    Returns:
        True  → marketing
        False → 其他部门（明确非 marketing）
        None  → 无法判断（如 Virtual Special Issue）
    """
    if not accepted_by:
        return None

    text = accepted_by.lower()

    # 明确的 marketing 信号
    if re.search(r"\bmarketing\b", text):
        return True

    # 有 accepted_by 值但不是 marketing → 明确排除
    if text:
        return False

    # 无 accepted_by 值 → 无法判断，走关键词比分兜底
    return None


# ---------------------------------------------------------------------------
# 关键词比分（兜底）
# ---------------------------------------------------------------------------
MARKETING_KEYWORDS = [
    # Core marketing
    "marketing", "marketing mix", "market response", "market share",
    # Consumer / Customer
    "consumer", "consumer choice", "customer",
    "customer satisfaction", "customer experience", "customer engagement",
    "customer acquisition", "customer lifetime value",
    # Pricing
    "pricing", "price", "price promotion",
    "dynamic pricing", "price discrimination", "price sensitivity", "reference price",
    "coupon", "discount",
    # Product
    "product", "product launch", "product design", "product line",
    "new product", "assortment", "bundle",
    # Promotion / Advertising
    "promotion", "advertising",
    "search advertising", "sponsored search", "display advertising",
    "targeting", "personalize", "personalization",
    # Brand
    "brand", "brand equity", "brand loyalty", "brand extension",
    # Channel / Retail
    "retail", "retailer", "channel",
    "e-commerce", "online marketplace",
    "sales", "salesperson", "sales force",
    # Digital / Platform
    "digital platform", "social media", "influencer",
    "online review", "rating", "user-generated content",
    "recommendation", "recommender",
    "search", "platform", "two-sided market", "network effect",
    # Engagement / Loyalty
    "loyalty", "loyalty program",
    "word of mouth", "subscription", "freemium",
    "conversion", "click-through", "purchase funnel",
    # Research methods
    "choice model", "structural model", "field experiment",
    "conjoint", "discrete choice", "consideration set",
    "segmentation",
    # Metrics / KPIs
    "demand", "purchase", "shopping",
    "willingness to pay", "acquisition", "retention", "churn",
    "CRM",
]

NON_MARKETING_KEYWORDS = [
    "portfolio optimiz", "asset pricing", "volatility", "hedge fund",
    "supply chain", "inventory", "manufacturing", "logistics",
    "operations management", "queuing", "scheduling",
    "information system", "software development", "IT governance",
    "accounting", "audit", "financial report",
    "organizational behavior", "human resource", "team diversity",
    "corporate governance", "CEO", "board of director",
    "earnings", "dividend", "merger", "acquisition",
    "stochastic control", "option pricing",
    "sustainability reporting", "ESG disclosure", "ESG performance", "ESG risk",
    "discount rate", "cash flow",  # 金融术语 → 防 discount/channel 误匹配
    "data science", "machine learning pipeline",
]


def _keyword_score(title: str, abstract: str | None) -> tuple[int, int]:
    text = (title + " " + (abstract or "")).lower()
    pos = sum(1 for kw in MARKETING_KEYWORDS if kw in text)
    neg = sum(1 for kw in NON_MARKETING_KEYWORDS if kw in text)
    return pos, neg


# ---------------------------------------------------------------------------
# 截断排序加权（标题关键词预判，用于截断前优先保留 marketing 论文）
# ---------------------------------------------------------------------------
def mngsci_marketing_boost(paper: dict) -> int:
    """MngSci 论文标题级别的 marketing 信号强度。

    仅用于截断排序的 tiebreaker——不依赖 full abstract 或 accepted_by。
    仅凭标题中的 marketing 关键词判断是否有保留价值。

    Returns:
        0 → 有 marketing 信号（排序优先）
        1 → 无信号（排序靠后）
        非 MngSci 论文一律返回 0（不影响其他期刊的排序）
    """
    if paper.get("journal") != "MngSci":
        return 0

    title = paper.get("title", "")
    pos, neg = _keyword_score(title, None)  # title only
    return 0 if pos > 0 else 1


# ---------------------------------------------------------------------------
# 主过滤函数
# ---------------------------------------------------------------------------
def filter_mngsci(papers: list[dict]) -> list[dict]:
    """过滤 MngSci 论文，只保留 Marketing 部门相关。

    非 MngSci 论文原样返回。
    """
    mngsci = [p for p in papers if p.get("journal") == "MngSci"]
    others = [p for p in papers if p.get("journal") != "MngSci"]

    if not mngsci:
        return papers

    print(f"[MngSci] {len(mngsci)} MngSci papers — filtering by accepted-by + keyword fallback")

    kept = []
    for p in mngsci:
        accepted_by = p.get("mngsci_accepted_by", "")
        title = p.get("title", "")

        # 1. 优先：accepted-by 部门判断
        is_mkt = _is_marketing_by_accepted(accepted_by)
        if is_mkt is True:
            kept.append(p)
            print(f"  + [dept=mkt] {title[:70]}...")
            continue
        elif is_mkt is False:
            print(f"  - [dept=other] {title[:70]}...")
            continue  # 明确非 marketing，丢弃

        # 2. is_mkt is None（无数据 或 Virtual Special Issue）
        pos, neg = _keyword_score(title, p.get("abstract"))
        score = pos - neg

        if score >= 2:
            if accepted_by:
                print(f"  ? [kw={score:+d},dept=special] {title[:70]}... kept")
            else:
                print(f"  ? [kw={score:+d},no-dept] {title[:70]}... kept")
            kept.append(p)
        else:
            if accepted_by:
                print(f"  - [kw={score:+d},dept=special] {title[:70]}... dropped")
            else:
                print(f"  - [kw={score:+d},no-dept] {title[:70]}... dropped")

    print(f"[MngSci] {len(kept)}/{len(mngsci)} kept")
    return others + kept
