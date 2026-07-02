"""
Abstract 处理（双层：一句话总结 + 完整中文翻译）。

通过统一 llm.py 客户端调用：
  DeepSeek API 优先 → Ollama 本地回落 → 降级（留空）
"""

import re

from src.llm import chat_json, backend_status


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------
ONE_LINER_SYSTEM = """你是一位专业学术论文翻译。这些论文来自 Marketing Science、Quantitative Marketing、Empirical IO 等相关领域。请根据论文摘要，为每篇论文写一句中文总结。

要求：
- 仅依据摘要内容
- 包含：
  (1) 研究问题
  (2) 核心发现
- 不得补充摘要之外的信息
- 不得评价论文
- 每句话控制在40-60字
- 保持学术中文风格
- 每个 JSON key 只能包含对应索引那一篇论文的一句话总结
- 不要混入其他论文的信息

只回复 JSON：
{"0":"...","1":"..."}"""


ABSTRACT_ZH_SYSTEM = """你是一位专业学术论文翻译。这些论文来自 Marketing Science、Quantitative Marketing、Empirical IO 等相关领域。请将以下每篇论文的英文摘要完整翻译成中文。

要求：
- 完整逐句翻译
- 不得遗漏任何一句
- 保留所有编号、括号、数学符号
- 保留原有段落结构
- 不增加解释
- 不总结
- 不润色
- 学术中文表达自然准确
- 每个 JSON key 只能包含对应索引那一篇论文的摘要翻译
- value 里不要重复标题，不要添加“摘要：”，不要使用分隔线

只回复 JSON：
{"0":"...","1":"..."}"""


# ---------------------------------------------------------------------------
# 逐篇生成
# ---------------------------------------------------------------------------
def _batch_process(
    papers: list[dict],
    system_prompt: str,
    field: str,
    label: str,
    temperature: float = 0.3,
) -> None:
    """对 papers 中每篇逐篇生成摘要字段，写入 field 字段。"""
    # 摘要类内容宁可慢一点也逐篇跑，避免本地小模型在 batch 内串块。
    batch_size = 1
    for batch_start in range(0, len(papers), batch_size):
        batch = papers[batch_start: batch_start + batch_size]

        mapping = _request_mapping(batch, system_prompt, label, temperature)

        invalid: list[int] = []
        for j, p in enumerate(batch):
            key = str(j)
            value = _valid_mapping_value(mapping, key, field, batch, j)
            if value:
                p[field] = value
            else:
                p[field] = ""
                invalid.append(j)

        retry_invalid = invalid and (len(batch) > 1 or field == "abstract_zh")
        if retry_invalid:
            print(f"[ABSTRACT] {label}: retrying {len(invalid)} invalid item(s) individually")
            for j in invalid:
                p = batch[j]
                retry_temperature = 0.1 if field == "abstract_zh" else temperature
                single_mapping = _request_mapping(
                    [p],
                    system_prompt,
                    label,
                    retry_temperature,
                    strict_single=(field == "abstract_zh"),
                )
                value = _valid_mapping_value(single_mapping, "0", field, [p], 0)
                p[field] = value or ""

    filled = sum(1 for p in papers if p.get(field))
    print(f"[ABSTRACT] {label}: {filled}/{len(papers)}")


def _request_mapping(
    batch: list[dict],
    system_prompt: str,
    label: str,
    temperature: float,
    strict_single: bool = False,
) -> dict | None:
    items = []
    for j, p in enumerate(batch):
        abstract = (p.get("abstract") or "")
        items.append(
            f"[{j}] Title: {p['title']}\n"
            f"    Journal: {p.get('journal_full', p.get('journal', ''))}\n"
            f"    Abstract: {abstract}"
        )

    user_msg = "\n\n---\n\n".join(items) + "\n\n---\nReturn JSON only."
    if strict_single and len(batch) == 1:
        user_msg += (
            '\nIMPORTANT: Translate only the Abstract text for [0]. Return exactly {"0":"中文翻译"}.\n'
            "Do not include the title, source English abstract, labels, separators, or explanations."
        )

    try:
        mapping = chat_json(system_prompt, user_msg, temperature=temperature)
    except Exception as e:
        print(f"[ABSTRACT] {label} batch failed: {e}")
        return None

    return mapping if isinstance(mapping, dict) else None


def _valid_mapping_value(
    mapping: dict | None,
    key: str,
    field: str,
    batch: list[dict],
    index: int,
) -> str:
    if not mapping or key not in mapping:
        return ""
    value = mapping.get(key)
    if not isinstance(value, str):
        return ""

    if _looks_batch_contaminated(value, field, batch, index):
        return ""

    cleaned = _clean_generated_value(value, field)
    if field == "abstract_zh" and _looks_untranslated(cleaned):
        return ""

    return cleaned


def _clean_generated_value(value: str, field: str) -> str:
    text = value.strip()
    if text.endswith('",'):
        text = text[:-2].rstrip()
    if text.startswith('"') and text.endswith('"'):
        text = text[1:-1].strip()

    if field == "abstract_zh":
        text = re.sub(r"^\s*《[^》]{1,200}》\s*", "", text)
        text = re.sub(r"^\s*(?:摘要|Abstract)\s*[:：]\s*", "", text, flags=re.IGNORECASE)
    return text.strip()


def _looks_batch_contaminated(value: str, field: str, batch: list[dict], index: int) -> bool:
    if not value or not value.strip():
        return True

    if field != "abstract_zh":
        return False

    if re.search(r"(^|\n)\s*(?:-{3,}|—{2,})\s*(?=\n|$)", value):
        return True

    if len(re.findall(r"(^|\n)\s*《[^》]+》", value)) > 1:
        return True

    abstract_label_count = len(re.findall(r"(^|\n)\s*(?:摘要|Abstract)\s*[:：]", value, flags=re.IGNORECASE))
    if abstract_label_count > 1:
        return True

    for j, paper in enumerate(batch):
        if j == index:
            continue
        other_title = paper.get("title", "")
        other_title_zh = paper.get("title_zh", "")
        if other_title and other_title in value:
            return True
        if other_title_zh and other_title_zh in value:
            return True

    return False


def _looks_untranslated(value: str) -> bool:
    if not value:
        return True

    ascii_letters = len(re.findall(r"[A-Za-z]", value))
    cjk_chars = len(re.findall(r"[\u4e00-\u9fff]", value))
    if ascii_letters > 120 and ascii_letters > cjk_chars * 2:
        return True

    common_english_markers = len(
        re.findall(r"\b(?:the|and|of|to|in|we|this|authors|research|study|find|show)\b", value, flags=re.IGNORECASE)
    )
    return common_english_markers >= 20 and cjk_chars < 50


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------
def process_abstract(papers: list[dict]) -> list[dict]:
    """生成双层中文内容（一句话 + 完整翻译，原地修改 + 返回）。

    无 LLM 可用时：one_line_summary 和 abstract_zh 均留空。
    render.py 根据字段存在与否决定渲染行为。
    """
    if not papers:
        return papers

    backend = backend_status()
    print(f"[ABSTRACT] backend: {backend}")
    if backend == "degraded (no LLM)":
        for p in papers:
            p["one_line_summary"] = ""
            p["abstract_zh"] = ""
        return papers

    # Phase 1: 一句话摘要（先跑，作为快速预览）
    print("[ABSTRACT] Phase 1/2: one-line summaries...")
    _batch_process(papers, ONE_LINER_SYSTEM, "one_line_summary", "one-line")

    # Phase 2: 完整中文翻译
    print("[ABSTRACT] Phase 2/2: full translations...")
    _batch_process(papers, ABSTRACT_ZH_SYSTEM, "abstract_zh", "full")

    return papers
