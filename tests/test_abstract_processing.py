"""
LLM abstract post-processing tests.
"""

import src.abstract as abstract_mod

from src.abstract import (
    _clean_generated_value,
    _looks_batch_contaminated,
    _looks_untranslated,
    _valid_mapping_value,
)


def test_clean_generated_translation_removes_model_added_title_and_label():
    raw = "《测试论文标题》\n摘要：这是完整翻译。"

    result = _clean_generated_value(raw, "abstract_zh")

    assert result == "这是完整翻译。"


def test_detects_batch_contaminated_full_translation():
    batch = [
        {"title": "Paper A", "title_zh": "论文A"},
        {"title": "Paper B", "title_zh": "论文B"},
    ]
    raw = "《论文A》\n摘要：第一篇。\n\n——\n\n《论文B》\n摘要：第二篇。"

    assert _looks_batch_contaminated(raw, "abstract_zh", batch, 0)


def test_inline_chinese_dash_is_not_batch_contamination():
    batch = [{"title": "Paper A", "title_zh": "论文A"}]
    raw = "研究引入最常用的知识保护策略——泄漏预防——的一系列隐藏成本。"

    assert not _looks_batch_contaminated(raw, "abstract_zh", batch, 0)


def test_valid_mapping_value_rejects_other_paper_title():
    batch = [
        {"title": "Paper A", "title_zh": "论文A"},
        {"title": "Paper B", "title_zh": "论文B"},
    ]
    mapping = {"0": "第一篇翻译。\n论文B\n第二篇翻译。"}

    result = _valid_mapping_value(mapping, "0", "abstract_zh", batch, 0)

    assert result == ""


def test_clean_generated_value_removes_trailing_json_artifact():
    raw = "研究重新审视营销知识保护策略。\","

    result = _clean_generated_value(raw, "one_line_summary")

    assert result == "研究重新审视营销知识保护策略。"


def test_rejects_untranslated_full_translation():
    raw = (
        "The authors build a game-theoretic model and examine how an alliance "
        "affects price competition in the market. They find that the alliance "
        "impact depends on differentiation and show that consumer surplus can "
        "increase even if price competition is relaxed."
    )

    assert _looks_untranslated(raw)


def test_full_translation_single_invalid_retries(monkeypatch):
    calls = []

    def fake_chat_json(system, user, temperature=0.3):
        calls.append((system, user, temperature))
        if len(calls) == 1:
            return {
                "0": (
                    "The authors and the research study find and show that the strategy "
                    "is important in marketing and the firm context. "
                ) * 3
            }
        return {"0": "知识是营销中的关键资源，企业通常认为必须防止有价值的知识泄露给竞争者。"}

    monkeypatch.setattr(abstract_mod, "chat_json", fake_chat_json)
    papers = [
        {
            "title": "Rethinking Marketing Knowledge Protection",
            "journal": "JM",
            "abstract": "Knowledge is a key resource in marketing.",
        }
    ]

    abstract_mod._batch_process(
        papers,
        abstract_mod.ABSTRACT_ZH_SYSTEM,
        "abstract_zh",
        "full",
    )

    assert len(calls) == 2
    assert calls[1][2] == 0.1
    assert "Return exactly" in calls[1][1]
    assert papers[0]["abstract_zh"] == "知识是营销中的关键资源，企业通常认为必须防止有价值的知识泄露给竞争者。"


def test_one_line_summary_runs_per_paper(monkeypatch):
    calls = []

    def fake_chat_json(system, user, temperature=0.3):
        calls.append(user)
        return {"0": f"第{len(calls)}篇论文的中文总结。"}

    monkeypatch.setattr(abstract_mod, "chat_json", fake_chat_json)
    papers = [
        {"title": "Paper A", "journal": "JM", "abstract": "Abstract A."},
        {"title": "Paper B", "journal": "JM", "abstract": "Abstract B."},
    ]

    abstract_mod._batch_process(
        papers,
        abstract_mod.ONE_LINER_SYSTEM,
        "one_line_summary",
        "one-line",
    )

    assert len(calls) == 2
    assert "Paper A" in calls[0]
    assert "Paper B" not in calls[0]
    assert "Paper B" in calls[1]
    assert papers[0]["one_line_summary"] == "第1篇论文的中文总结。"
    assert papers[1]["one_line_summary"] == "第2篇论文的中文总结。"
