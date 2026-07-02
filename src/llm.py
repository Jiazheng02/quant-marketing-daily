"""
统一 LLM 客户端。

优先级链：DeepSeek API → Ollama 本地 → 降级（返回 None）
"""

import json
import re
import requests

from src.config import (
    DEEPSEEK_API_KEY,
    DEEPSEEK_BASE_URL,
    OLLAMA_BASE_URL,
    OLLAMA_MODEL,
    OLLAMA_TIMEOUT,
)


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------
def _normalize_quotes(text: str) -> str:
    """将弯引号 / 中文引号替换为 JSON 转义形式。"""
    text = text.replace("\u201c", '\\"').replace("\u201d", '\\"')
    text = text.replace("\u300c", '\\"').replace("\u300d", '\\"')
    text = text.replace("\u2018", "'").replace("\u2019", "'")
    return text


def _clean_json(raw: str) -> str:
    """移除 JSON 字符串中非法控制字符（RFC 8259）。

    LLM 生成的内容常在字符串值里夹带未转义的 \\n / \\r / \\t，
    导致 json.loads() 报 Invalid control character。
    这里把它们替换成空格，尽量保住原文意思。
    """
    return re.sub(r'[\x00-\x1f\x7f-\x9f]', ' ', raw)

def _extract_json(text: str) -> dict | None:
    """从 LLM 输出中鲁棒地提取 JSON 对象。

    按优先级尝试：
    1. 直接 json.loads（最快）
    2. 去掉 ```json 围栏后再解析
    3. 从第一个 { 或 [ 用 raw_decode 解析（允许后面有冗余文本）
    4. 手动括号匹配提取最外层 JSON 再解析
    """
    if not text or not text.strip():
        return None

    # --- 策略 1: 直接解析 ---
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # --- 策略 2: 去掉 markdown 围栏 ---
    cleaned = text.strip()
    # 去掉开头的 ```json 或 ```
    if cleaned.startswith("```"):
        # 找到第一个换行后的内容
        first_nl = cleaned.find("\n")
        if first_nl >= 0:
            cleaned = cleaned[first_nl + 1:]
        else:
            cleaned = cleaned[3:]
        # 去掉结尾的 ```
        last_backticks = cleaned.rfind("```")
        if last_backticks >= 0:
            cleaned = cleaned[:last_backticks]
        cleaned = cleaned.strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass

    # --- 策略 3: raw_decode 从第一个 { 或 [ 开始 ---
    for start_char in ('{', '['):
        start_idx = text.find(start_char)
        if start_idx == -1:
            continue
        try:
            decoder = json.JSONDecoder()
            obj, _ = decoder.raw_decode(text[start_idx:])
            return obj
        except json.JSONDecodeError:
            continue

    # --- 策略 4: 手动括号匹配，处理截断/残缺 JSON ---
    for start_char, end_char in (('{', '}'), ('[', ']')):
        start_idx = text.find(start_char)
        if start_idx == -1:
            continue

        depth = 0
        in_str = False
        escape = False
        last_meaningful = start_idx  # 最后一个有效字符的位置

        for i in range(start_idx, len(text)):
            ch = text[i]

            if escape:
                escape = False
                continue
            if ch == '\\':
                escape = True
                continue

            if ch == '"' and not in_str:
                in_str = True
                continue
            if in_str:
                if ch == '"':
                    in_str = False
                continue

            if ch in '{[':
                depth += 1
            elif ch in '}]':
                depth -= 1
                if depth == 0:
                    # 找到完整匹配
                    candidate = text[start_idx:i + 1]
                    try:
                        return json.loads(candidate)
                    except json.JSONDecodeError:
                        # 可能是截断的 JSON，尝试修复
                        pass

            # 记录最后一个可能不是空白/控制字符的位置
            if ch not in ' \t\n\r':
                last_meaningful = i

        # 括号没闭合（截断响应），尝试自动修复
        if depth > 0:
            # 在字符串内（未关闭的引号）先补引号
            if in_str:
                # 找到最后一个未闭合的字符串开头，直接截断到那里之前
                # 更简单：直接丢弃最后一个未闭合的 key/value，倒回到上一个完整元素
                pass  # 太复杂，fall through 到下面的截断修复

            # 简单修复：补上缺失的闭合括号
            repaired = text[start_idx:last_meaningful + 1].rstrip()
            # 如果末尾是 , 或 : 去掉
            repaired = repaired.rstrip(',:')
            # 补引号（如果字符串未闭合）
            if in_str:
                repaired += '"'
            # 补闭合括号
            repaired += end_char * depth
            try:
                return json.loads(repaired)
            except json.JSONDecodeError:
                continue

    return None


# ---------------------------------------------------------------------------
# 可用性检测（缓存结果，避免每次调用都探测）
# ---------------------------------------------------------------------------
_ollama_checked: bool | None = None  # True = available, False = unavailable


def _ollama_available() -> bool:
    global _ollama_checked
    if _ollama_checked is not None:
        return _ollama_checked
    try:
        r = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=5)
        if r.status_code == 200:
            data = r.json()
            # 检查目标模型是否存在
            models = [m.get("name", "") for m in data.get("models", [])]
            found = any(OLLAMA_MODEL in m or m.startswith(OLLAMA_MODEL.split(":")[0]) for m in models)
            _ollama_checked = found
            if found:
                print(f"[LLM] Ollama available: {OLLAMA_MODEL} @ {OLLAMA_BASE_URL}")
            else:
                print(f"[LLM] Ollama running but model '{OLLAMA_MODEL}' not found. "
                      f"Available: {models[:5]}...")
            return found
        _ollama_checked = False
        return False
    except Exception:
        _ollama_checked = False
        return False


# ---------------------------------------------------------------------------
# 统一 JSON 提取
# ---------------------------------------------------------------------------
def chat_json(system: str, user: str, temperature: float = 0.3) -> dict | None:
    """以 JSON 格式返回结构化结果。返回 None 表示全部失败。"""

    # 1) DeepSeek API
    if DEEPSEEK_API_KEY:
        try:
            from openai import OpenAI
            client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)
            resp = client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=temperature,
                max_tokens=2000,
                response_format={"type": "json_object"},
            )
            raw = resp.choices[0].message.content.strip()
            return json.loads(_normalize_quotes(raw))
        except Exception as e:
            print(f"[LLM] DeepSeek JSON failed: {e}")

    # 2) Ollama 本地回落
    if _ollama_available():
        try:
            # 强化 prompt：明确要求只输出 JSON，禁止 thinking/解释
            prompt = (
                f"{system}\n\n"
                f"CRITICAL: Output ONLY a single valid JSON object/array.\n"
                f"- No thinking tags (e.g. <think>...</think>)\n"
                f"- No markdown fences (e.g. ```json)\n"
                f"- No text before or after the JSON\n"
                f"- Start with {{ or [ and end with }} or ]\n\n"
                f"{user}\n\n"
                f"JSON only:"
            )
            r = requests.post(
                f"{OLLAMA_BASE_URL}/api/generate",
                json={
                    "model": OLLAMA_MODEL,
                    "prompt": prompt,
                    "stream": False,
                    "format": "json",
                    "options": {
                        "temperature": temperature,
                        "num_predict": 4096,
                    },
                },
                timeout=OLLAMA_TIMEOUT,
            )
            if r.status_code == 200:
                raw = r.json().get("response", "").strip()
                if not raw:
                    print(f"[LLM] Ollama returned empty response")
                    return None
                # 清洗控制字符 + 规范化弯引号
                raw = _clean_json(raw)
                raw = _normalize_quotes(raw)

                # 用鲁棒提取代替直接 json.loads
                result = _extract_json(raw)
                if result is None:
                    # 仍然失败，打印更多调试信息
                    print(f"[LLM] Ollama JSON extract failed")
                    print(f"  response length: {len(raw)}")
                    print(f"  first 300 chars: {raw[:300]}")
                    print(f"  last 200 chars: {raw[-200:]}")
                return result
            else:
                print(f"[LLM] Ollama HTTP {r.status_code}")
        except Exception as e:
            print(f"[LLM] Ollama failed: {e}")

    # 3) 降级
    print("[LLM] No backend available — degraded mode")
    return None


# ---------------------------------------------------------------------------
# 统一文本提取
# ---------------------------------------------------------------------------
def chat_text(system: str, user: str, temperature: float = 0.3) -> str | None:
    """返回纯文本结果。返回 None 表示失败。"""

    # 1) DeepSeek API
    if DEEPSEEK_API_KEY:
        try:
            from openai import OpenAI
            client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)
            resp = client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=temperature,
                max_tokens=1500,
            )
            return resp.choices[0].message.content.strip()
        except Exception as e:
            print(f"[LLM] DeepSeek text failed: {e}")

    # 2) Ollama 本地回落
    if _ollama_available():
        try:
            prompt = f"{system}\n\n---\n\n{user}"
            r = requests.post(
                f"{OLLAMA_BASE_URL}/api/generate",
                json={
                    "model": OLLAMA_MODEL,
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "temperature": temperature,
                        "num_predict": 4096,
                    },
                },
                timeout=OLLAMA_TIMEOUT,
            )
            if r.status_code == 200:
                return r.json().get("response", "").strip()
            print(f"[LLM] Ollama text failed: HTTP {r.status_code}")
        except Exception as e:
            print(f"[LLM] Ollama text failed: {e}")

    print("[LLM] No backend available — degraded mode")
    return None


# ---------------------------------------------------------------------------
# 后端状态报告（供 fetch.py 仪表盘使用）
# ---------------------------------------------------------------------------
def backend_status() -> str:
    if DEEPSEEK_API_KEY:
        return "DeepSeek API"
    if _ollama_available():
        return f"Ollama ({OLLAMA_MODEL})"
    return "degraded (no LLM)"
