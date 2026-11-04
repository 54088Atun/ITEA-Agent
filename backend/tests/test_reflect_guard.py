"""反思校验:长代码块检测必须线性,避免正则灾难性回溯阻塞事件循环"""
import time

from app.agent.nodes.reflect import _has_long_code_block, _quick_checks


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
