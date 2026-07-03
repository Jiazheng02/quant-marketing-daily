"""
Quant relevance scoring.

This module ranks papers by the user's quantitative marketing research profile.
It is intentionally separate from ``filter_mngsci.py``: MngSci filtering answers
"is this a marketing paper?", while this module answers "is this a quant paper
worth preserving before the 30-paper truncation?".
"""

import re


CORE_QUANT_KEYWORDS = [
    # Econometrics / causal identification
    "causal inference",
    "identification",
    "instrumental variable",
    "instrumental variables",
    "difference-in-differences",
    "diff-in-diff",
    "regression discontinuity",
    "synthetic control",
    "panel data",
    "econometric",
    "endogeneity",
    "copula",
    # Structural / demand / choice
    "structural model",
    "structural estimation",
    "demand estimation",
    "demand model",
    "choice model",
    "discrete choice",
    "conjoint",
    "consideration set",
    "heterogeneity",
    # Experiments with managerially relevant treatment design
    "field experiment",
    "randomized experiment",
    "randomized controlled trial",
    "natural experiment",
    # Pricing / auctions / platforms
    "pricing",
    "dynamic pricing",
    "price discrimination",
    "price competition",
    "auction",
    "platform",
    "marketplace",
    "two-sided market",
    "network effect",
    # Quant ML / AI / recommender systems
    "machine learning",
    "deep learning",
    "neural network",
    "llm",
    "large language model",
    "large language models",
    "generative ai",
    "recommendation",
    "recommendations",
    "recommender",
    "recommender system",
    "recommender systems",
]


SECONDARY_QUANT_KEYWORDS = [
    "advertising",
    "search advertising",
    "sponsored search",
    "targeting",
    "personalization",
    "online review",
    "rating",
    "subscription",
    "churn",
    "retention",
    "customer lifetime value",
    "crm",
    "digital payment",
    "market response",
    "market share",
    "sales response",
    "demand",
    "purchase",
]


BROAD_MARKETING_KEYWORDS = [
    "marketing",
    "consumer",
    "customer",
    "brand",
    "product",
    "retail",
    "sales",
    "promotion",
]


LOW_PRIORITY_BEHAVIORAL_KEYWORDS = [
    "attitude",
    "emotion",
    "identity",
    "mindset",
    "self",
    "moral",
    "morality",
    "persuasion",
    "well-being",
    "stigma",
    "language",
    "framing",
    "gesture",
    "hand gesture",
    "aesthetic",
    "aesthetics",
    "sensory",
    "goal failure",
    "subjective poverty",
    "sociocultural",
    "social norm",
]


RELEVANCE_TIERS = {
    "core_quant": 0,
    "quant_relevant": 1,
    "broad_marketing": 2,
    "low_priority": 3,
}


def _normalize(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[‐‑‒–—]", "-", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _contains(text: str, keyword: str) -> bool:
    keyword = _normalize(keyword)
    pattern = r"(?<![a-z0-9])" + re.escape(keyword) + r"(?![a-z0-9])"
    return re.search(pattern, text) is not None


def _count_matches(text: str, keywords: list[str]) -> int:
    return sum(1 for keyword in keywords if _contains(text, keyword))


def quant_relevance_counts(title: str, abstract: str | None = None) -> dict[str, int]:
    """Return keyword-hit counts by relevance category."""
    text = _normalize(title + " " + (abstract or ""))
    return {
        "core": _count_matches(text, CORE_QUANT_KEYWORDS),
        "secondary": _count_matches(text, SECONDARY_QUANT_KEYWORDS),
        "broad": _count_matches(text, BROAD_MARKETING_KEYWORDS),
        "behavioral": _count_matches(text, LOW_PRIORITY_BEHAVIORAL_KEYWORDS),
    }


def quant_relevance_score(title: str, abstract: str | None = None) -> int:
    """Weighted score for quant-marketing relevance."""
    counts = quant_relevance_counts(title, abstract)
    return (
        counts["core"] * 3
        + counts["secondary"] * 2
        + counts["broad"]
        - counts["behavioral"] * 2
    )


def quant_relevance_tier(title: str, abstract: str | None = None) -> str:
    """Classify a paper into a coarse relevance tier."""
    counts = quant_relevance_counts(title, abstract)
    score = quant_relevance_score(title, abstract)

    if counts["core"] >= 2 or (counts["core"] >= 1 and score >= 3):
        return "core_quant"
    if score >= 3:
        return "quant_relevant"
    if score >= 1:
        return "broad_marketing"
    return "low_priority"


def paper_relevance_sort_key(paper: dict, include_abstract: bool = False) -> tuple[int, int]:
    """Sort key part for preserving quant-relevant papers.

    Lower is better. The second element is negative score so stronger papers
    sort ahead within the same coarse tier.
    """
    abstract = paper.get("abstract") if include_abstract else None
    title = paper.get("title", "")
    tier = quant_relevance_tier(title, abstract)
    score = quant_relevance_score(title, abstract)
    return (RELEVANCE_TIERS[tier], -score)
