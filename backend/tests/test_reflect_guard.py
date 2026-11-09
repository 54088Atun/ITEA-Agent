"""反思校验:长代码块检测必须线性,避免正则灾难性回溯阻塞事件循环"""
import asyncio
import time
from unittest.mock import AsyncMock

from app.agent.nodes.reflect import _has_long_code_block, _quick_checks, reflect_node


def test_detects_long_code_block():
    long_block = "```python\n" + "\n".join("x = 1" for _ in range(31)) + "\n```"
    short_block = "```python\n" + "\n".join("x = 1" for _ in range(20)) + "\n```"
    assert _has_long_code_block(long_block) is True
    assert _has_long_code_block(short_block) is False


def test_detects_unclosed_long_block():
    assert _has_long_code_block("```python\n" + "\n".join("x" for _ in range(31))) is True


def test_pathological_input_is_linear():
    output = ("```" * 20000) + "\n" + ("x\n" * 20000)
    started = time.monotonic()
    _has_long_code_block(output)
    assert time.monotonic() - started < 1.0


def test_quick_checks_flags_long_block():
    output = (
        "```python\n" + "\n".join("x = 1" for _ in range(31)) + "\n```\n"
        "[AI 辅助参考,请师生审核]"
    )
    issues = _quick_checks(output, rag_context="", require_rag=False)
    assert any("超长完整代码块" in item for item in issues)


def test_reflect_skips_rag_requirement_when_course_has_no_index(monkeypatch):
    """课程无检索资料时,不能因'无知识库依据'触发反思重写"""
    monkeypatch.setattr(
        "app.agent.nodes.reflect.llm_invoke",
        AsyncMock(side_effect=AssertionError("不应触发 LLM 反思")),
    )
    state = {
        "final_output": "数据结构中的 WBS 用于分解工作包。[AI 辅助参考,请师生审核]",
        "rag_context": "",
        "reflection_count": 0,
        "branch": "tutor",
        "course_id": 210001,
        "retrieval_available": False,
    }
    result = asyncio.run(reflect_node(state))
    assert result["reflection_passed"] is True


def test_missing_ai_tag_is_patched_without_llm(monkeypatch):
    """只缺 AI 标注时直接补齐,不调用模型复核,避免普通概念题被整段重写"""
    monkeypatch.setattr(
        "app.agent.nodes.reflect.llm_invoke",
        AsyncMock(side_effect=AssertionError("缺标注不应触发 LLM 复核")),
    )
    state = {
        "final_output": "递归是函数调用自身的一种方法。",
        "rag_context": "",
        "reflection_count": 0,
        "branch": "tutor",
        "course_id": 210001,
        "retrieval_available": False,
    }
    result = asyncio.run(reflect_node(state))
    assert result["reflection_passed"] is True
    assert "[AI 辅助参考" in result["final_output"]
    assert result["reflection_count"] == 1
