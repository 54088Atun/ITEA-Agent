"""P0-4 统一工具返回契约:字段、超时、降级与不可信标记"""
import asyncio
import time

from app.agent import tool_loop
from app.agent.llm import ToolPlan
from app.agent.nodes import tool_executor
from app.agent.tools import TOOL_REGISTRY
from app.agent.tools.gateway import (
    ToolSpec,
    UNTRUSTED_TOOLS,
    get_tool_spec,
    tool_result,
    tool_timeout_seconds,
    validate_tool_arguments,
)


def _state(**overrides):
    state = {
        "session_id": "tool-contract-test",
        "user_id": 11,
        "user_role": "teacher",
        "course_id": 7,
        "messages": [{"role": "user", "content": "查一下"}],
        "reflection_notes": "",
        "stream_queue": None,
    }
    state.update(overrides)
    return state


# ---------- tool_result 六字段契约 ----------

def test_tool_result_exposes_exactly_six_fields():
    result = tool_result(True, {"context": "片段"})

    assert set(result) == {
        "ok", "data", "error", "sources", "latency_ms", "untrusted",
    }
    assert result["ok"] is True
    assert result["data"] == {"context": "片段"}
    assert result["error"] is None
    assert result["sources"] == []
    assert result["latency_ms"] == 0
    assert result["untrusted"] is False


def test_tool_result_wraps_non_dict_data():
    assert tool_result(True, ["a", "b"])["data"] == {"result": ["a", "b"]}
    assert tool_result(True, "文本")["data"] == {"result": "文本"}


def test_tool_result_treats_none_data_as_empty_object():
    assert tool_result(False, None, error="boom")["data"] == {}


def test_tool_result_normalizes_field_types():
    result = tool_result(
        True, {"a": 1}, sources=None, latency_ms=None, untrusted=1,
    )

    assert result["sources"] == []
    assert result["latency_ms"] == 0
    assert result["untrusted"] is True


def test_tool_result_does_not_alias_caller_dict():
    payload = {"context": "片段"}
    result = tool_result(True, payload)
    result["data"]["context"] = "改写"

    assert payload["context"] == "片段"


# ---------- tool_timeout_seconds ----------

def test_tool_timeout_seconds_falls_back_when_spec_missing():
    assert tool_timeout_seconds(None, 20) == 20


def test_tool_timeout_seconds_falls_back_when_disabled():
    spec = ToolSpec(name="demo", description="", parameters={}, timeout_ms=0)
    assert tool_timeout_seconds(spec, 20) == 20


def test_tool_timeout_seconds_uses_spec_value():
    spec = get_tool_spec("sql_query")

    assert spec is not None
    assert tool_timeout_seconds(spec, 20) == 5.0


def test_tool_timeout_seconds_capped_by_fallback():
    spec = get_tool_spec("sql_query")

    assert tool_timeout_seconds(spec, 1) == 1


# ---------- validate_tool_arguments ----------

def test_validate_arguments_rejects_non_dict():
    spec = get_tool_spec("rag_search")

    assert validate_tool_arguments(spec, ["query"]) == "工具 rag_search 参数必须是对象"


def test_validate_arguments_rejects_unknown_keys():
    spec = get_tool_spec("rag_search")

    message = validate_tool_arguments(spec, {"query": "遍历", "fake": 1})

    assert message == "工具 rag_search 不接受参数: fake"


def test_validate_arguments_rejects_type_mismatch():
    spec = get_tool_spec("rag_search")

    message = validate_tool_arguments(spec, {"query": 123})

    assert message == "工具 rag_search 参数 query 类型应为 string"


def test_validate_arguments_rejects_enum_out_of_range():
    spec = get_tool_spec("rag_search")

    message = validate_tool_arguments(spec, {"scope": "unknown"})

    assert "工具 rag_search 参数 scope 取值不在允许范围" in message


def test_validate_arguments_accepts_valid_arguments():
    spec = get_tool_spec("rag_search")

    assert validate_tool_arguments(
        spec, {"query": "遍历", "course_id": 7, "scope": "courseware"},
    ) is None


def test_validate_arguments_skips_none_values():
    spec = get_tool_spec("rag_search")

    assert validate_tool_arguments(spec, {"scope": None}) is None


def test_validate_arguments_rejects_bool_for_integer():
    spec = get_tool_spec("rag_search")

    message = validate_tool_arguments(spec, {"top_k": True})

    assert message == "工具 rag_search 参数 top_k 类型应为 integer"


def test_validate_arguments_allows_extra_keys_when_declared():
    spec = get_tool_spec("rag_search")

    assert validate_tool_arguments(
        spec, {"query": "遍历", "injected": 1}, allowed_extra={"injected"},
    ) is None


# ---------- 超时降级 ----------

def test_loop_degrades_with_unavailable_message_on_timeout(monkeypatch):
    monkeypatch.setattr(tool_loop, "TOOL_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setitem(
        TOOL_REGISTRY, "course_evidence",
        lambda **kw: time.sleep(0.3) or {"context": "迟到的结果"},
    )
    rounds = {"n": 0}

    async def planner(messages, tools):
        rounds["n"] += 1
        if rounds["n"] == 1:
            return ToolPlan(tool_calls=[{
                "id": "c1", "name": "course_evidence", "arguments": {"query": "q"},
            }])
        return "数据暂不可用,先给通用思路"

    text, trace = asyncio.run(tool_loop.run_tool_loop(
        [{"role": "user", "content": "查一下"}], _state(),
        planner=planner, tools=[],
    ))

    result = trace[0]["result"]
    assert result["ok"] is False
    assert "数据暂不可用" in result["error"]
    assert text == "数据暂不可用,先给通用思路"


# ---------- 不可信标记 ----------

def test_untrusted_tools_marked(monkeypatch):
    monkeypatch.setitem(
        TOOL_REGISTRY, "course_evidence",
        lambda **kw: {"context": "片段"},
    )

    payload = tool_executor._execute_single(
        {"name": "course_evidence", "arguments": {"query": "遍历", "course_id": 7}},
        _state(),
    )

    assert "course_evidence" in UNTRUSTED_TOOLS
    assert payload["ok"] is True
    assert payload["untrusted"] is True


def test_local_tool_not_marked_untrusted(monkeypatch):
    monkeypatch.setitem(
        TOOL_REGISTRY, "stats_analyzer",
        lambda **kw: {"summary": "统计"},
    )

    payload = tool_executor._execute_single(
        {"name": "stats_analyzer", "arguments": {"course_id": 7, "metric": "weakness"}},
        _state(),
    )

    assert payload["ok"] is True
    assert payload["untrusted"] is False
