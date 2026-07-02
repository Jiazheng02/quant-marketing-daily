"""
批量标题翻译（中文）。

通过统一 llm.py 客户端调用，支持 DeepSeek API 或 Ollama 本地。
所有标题单 batch 发送以最小化 HTTP 往返。
"""

from src.llm import chat_json
from src.config import TRANSLATION_BATCH_SIZE


TRANSLATE_SYSTEM = """你是一位专业学术论文翻译。这些论文来自 Marketing Science、Journal of Marketing、Quantitative Marketing and Economics 等相关领域。请将以下英文论文标题翻译成中文。

要求：
- 使用准确的中文专业术语
- 保持简洁，不超过原标题长度
- 保留专有名词、品牌名、技术术语的原语言
- 仅返回 JSON 对象，映射论文索引（字符串）到中文标题（字符串）

示例：
{
  "0": "社交媒体广告对消费者购买决策的因果效应研究",
  "1": "双边市场结构模型下的平台定价策略分析"
}"""


def translate_titles(papers: list[dict]) -> list[dict]:
    """为论文列表批量翻译标题，原地添加 title_zh 字段。

    无 LLM 可用时：title_zh 置空。
    """
    if not papers:
        return papers

    print(f"[TRANSLATE] {len(papers)} titles...")

    for batch_start in range(0, len(papers), TRANSLATION_BATCH_SIZE):
        batch = papers[batch_start: batch_start + TRANSLATION_BATCH_SIZE]

        items = []
        for j, p in enumerate(batch):
            items.append(f"[{j}] {p['title']}")

        user_msg = "\n".join(items) + "\n\n---\nReturn JSON only."

        try:
            mapping = chat_json(TRANSLATE_SYSTEM, user_msg, temperature=0.1)
        except Exception as e:
            print(f"[TRANSLATE] batch failed: {e}")
            mapping = None

        for j, p in enumerate(batch):
            key = str(j)
            if mapping and key in mapping and mapping[key]:
                p["title_zh"] = mapping[key].strip()
            else:
                p["title_zh"] = ""

    translated = sum(1 for p in papers if p.get("title_zh"))
    print(f"[TRANSLATE] {translated}/{len(papers)} titles translated")
    return papers
