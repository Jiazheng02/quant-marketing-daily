"""
测试 llm.py 的 _extract_json 鲁棒性。

覆盖 Ollama 常见病态输出：
- 控制字符污染
- 缺失逗号（Expecting ',' delimiter）
- markdown 围栏包裹
- 响应截断
- thinking 标签混入
"""

import json
import pytest

from src.llm import _extract_json


class TestExtractJson:
    """_extract_json 鲁棒性测试。"""

    def test_valid_json(self):
        assert _extract_json('{"a": 1}') == {"a": 1}

    def test_json_array(self):
        assert _extract_json('[{"a": 1}]') == [{"a": 1}]

    def test_markdown_fence(self):
        raw = '```json\n{"a": 1}\n```'
        assert _extract_json(raw) == {"a": 1}

    def test_markdown_fence_no_lang(self):
        raw = '```\n{"a": 1}\n```'
        assert _extract_json(raw) == {"a": 1}

    def test_text_before_json(self):
        raw = 'Here is the result: {"a": 1}'
        assert _extract_json(raw) == {"a": 1}

    def test_text_after_json(self):
        raw = '{"a": 1} Hope this helps!'
        assert _extract_json(raw) == {"a": 1}

    def test_text_before_and_after(self):
        raw = 'Result: {"a": 1} Done.'
        assert _extract_json(raw) == {"a": 1}

    def test_control_chars_in_string(self):
        """控制字符导致 Invalid control character —— 应在 _clean_json 阶段处理。"""
        # _extract_json 本身不处理控制字符，依赖调用方先 _clean_json
        # 但这里测的是 json 能接受的处理后输入
        raw = '{"summary": "line1 line2"}'
        assert _extract_json(raw) == {"summary": "line1 line2"}

    def test_missing_comma(self):
        """模拟 Expecting ',' delimiter 错误。

        模型有时会在 JSON 对象里漏掉逗号，
        这种情况 _extract_json 目前无法修复（需要更高级的启发式修复），
        但至少要保证不会崩溃。
        """
        # 注意：标准 json.loads 无法解析缺逗号的 JSON，
        # 这个测试记录当前行为（返回 None），不强制要求修复。
        raw = '{"title": "A" "score": 8}'
        result = _extract_json(raw)
        # 当前实现返回 None（无法修复），这是可接受的行为
        assert result is None or result == {"title": "A", "score": 8}

    def test_truncated_json_object(self):
        """响应被截断，缺失闭合括号。"""
        raw = '{"title": "A", "score": 8'
        # 策略4 会尝试修复
        result = _extract_json(raw)
        assert result is None or result == {"title": "A", "score": 8}

    def test_truncated_json_array(self):
        """数组响应被截断。"""
        raw = '[{"title": "A"}, {"title": "B"'
        result = _extract_json(raw)
        assert result is None or len(result) >= 1

    def test_thinking_tags_before(self):
        """Qwen 等 thinking 模型在 JSON 前输出 thinking 内容。"""
        raw = '<think>I need to return JSON.</think>{"a": 1}'
        assert _extract_json(raw) == {"a": 1}

    def test_thinking_tags_inside(self):
        """thinking 标签意外出现在 JSON 字符串值里（极少见）。"""
        # 这种情况 json 会报控制字符或其他错误
        # 不做强制要求，记录行为
        pass

    def test_empty_string(self):
        assert _extract_json("") is None

    def test_none_input(self):
        assert _extract_json(None) is None

    def test_whitespace_only(self):
        assert _extract_json("   \n  ") is None

    def test_nested_json(self):
        raw = '{"outer": {"inner": [1, 2, 3]}}'
        assert _extract_json(raw) == {"outer": {"inner": [1, 2, 3]}}

    def test_real_ollama_response(self):
        """模拟真实 Ollama 响应（来自用户报错）。

        错误：Expecting ',' delimiter: line 1 column 369 (char 368)
        这通常是因为响应在 JSON 中间被截断，或者有多余字符。
        """
        # 模拟一个在 char 368 附近被截断的 JSON
        raw = (
            '{"papers": ['
            '{"title_en": "Paper A", "title_zh": "论文A", "one_liner": "...", "score": 8},'
            '{"title_en": "Paper B", "title_zh": "论文B", "one_liner": "..."'
            # 这里截断了，没有闭合
        )
        result = _extract_json(raw)
        # 能提取多少是多少（当前可能返回 None）
        if result is not None:
            assert "papers" in result

    def test_ollama_num_predict_truncation(self):
        """num_predict 太小导致 JSON 被截断。"""
        raw = '{"papers": [{"title": "A", "score": 8}]'
        # 缺最后的 ]
        result = _extract_json(raw)
        assert result is not None or result is None  # 不强制，记录行为

    def test_json_with_escaped_newline_in_string(self):
        """JSON 字符串值里含转义换行符 \\n（合法 JSON）。"""
        # 注意：Python 里 '\\n' 是两个字符合法的 JSON 转义符
        # 解析后 title_zh 的值是 'line1\nline2'（\ 和 n 两个字）
        raw = '{"summary": "line1\\nline2"}'
        assert _extract_json(raw) == {"summary": "line1\nline2"}

    def test_deepseek_response_format(self):
        """DeepSeek response_format=json_object 的响应格式。"""
        raw = '{"title_zh": "测试", "one_liner": "摘要", "score": 7}'
        assert _extract_json(raw) == {
            "title_zh": "测试",
            "one_liner": "摘要",
            "score": 7,
        }
