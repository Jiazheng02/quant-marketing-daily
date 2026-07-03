"""
Quant relevance scoring tests.
"""

from src.relevance import quant_relevance_score, quant_relevance_tier


def test_llm_recommendation_is_core_quant():
    title = "LLM-Based Recommendation and Dynamic Pricing in Online Marketplaces"

    assert quant_relevance_tier(title) == "core_quant"
    assert quant_relevance_score(title) >= 6


def test_behavioral_psych_title_is_low_priority():
    title = "Language Framing, Hand Gestures, and Consumer Identity"

    assert quant_relevance_tier(title) == "low_priority"


def test_field_experiment_keeps_behavioral_intervention_relevant():
    title = "A Field Experiment on Digital Payment Adoption"
    abstract = "We estimate treatment effects on merchant adoption and usage."

    assert quant_relevance_tier(title, abstract) == "core_quant"
