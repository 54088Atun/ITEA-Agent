"""P0-1 工具调用循环 + P0-2 检索按需化"""
import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.agent import llm as llm_module
from app.agent import tool_loop
from app.agent.llm import ToolPlan
from app.agent.nodes import tool_executor
from app.agent.nodes import tutor as tutor_module
from app.agent.tools import TOOL_REGISTRY


def _state(**overrides):
    state = {
        "session_id": "tool-loop-test",
        "user_id": 11,
        "user_role": "student",
        "course_id": 7,
        "messages": [{"role": "user", "content": "解释二叉树的遍历"}],
        "reflection_notes": "",
        "stream_queue": None,
    }
    state.update(overrides)
    return state


# ---------- LLM 工具绑定 ----------

def test_llm_invoke_binds_tools_and_returns_plan(monkeypatch):
    captured = {}

    class FakeBound:
        async def ainvoke(self, messages):
            return SimpleNamespace(
                content="先查课程资料",
                tool_calls=[{
                    "name": "course_evidence",
                    "args": {"query": "遍历"},
                    "id": "call_1",
                }],
            )

    class FakeLLM:
        def bind_tools(self, tools):
            captured["tools"] = tools
            return FakeBound()

    monkeypatch.setattr(llm_module, "get_llm", lambda temperature=None: FakeLLM())

    plan = asyncio.run(llm_module.llm_invoke(
        [{"role": "user", "content": "解释遍历"}],
        tools=[{"name": "course_evidence", "description": "检索", "parameters": {}}],
    ))

    assert isinstance(plan, ToolPlan)
    assert captured["tools"][0]["type"] == "function"
    assert captured["tools"][0]["function"]["name"] == "course_evidence"
    assert plan.tool_calls == [{
        "id": "call_1", "name": "course_evidence", "arguments": {"query": "遍历"},
    }]


def test_llm_invoke_without_tool_calls_returns_text(monkeypatch):
    class FakeBound:
        async def ainvoke(self, messages):
            return SimpleNamespace(content="直接回答", tool_calls=[])

    class FakeLLM:
        def bind_tools(self, tools):
            return FakeBound()

    monkeypatch.setattr(llm_module, "get_llm", lambda temperature=None: FakeLLM())

    result = asyncio.run(llm_module.llm_invoke(
        [{"role": "user", "content": "你好"}],
        tools=[{"name": "course_evidence", "description": "检索", "parameters": {}}],
    ))

    assert result == "直接回答"


# ---------- 工具调用循环 ----------

def test_loop_executes_tool_then_answers(monkeypatch):
    executed = []
    monkeypatch.setitem(
        TOOL_REGISTRY, "course_evidence",
        lambda **kw: executed.append(kw) or {"context": "片段A", "fragments": []},
    )
    rounds = {"n": 0}

    async def planner(messages, tools):
        rounds["n"] += 1
        if rounds["n"] == 1:
            return ToolPlan(tool_calls=[{
                "id": "c1", "name": "course_evidence",
                "arguments": {"query": "遍历", "top_k": 3},
            }])
        assert any(message.get("role") == "tool" for message in messages)
        return "最终回答"

    text, trace = asyncio.run(tool_loop.run_tool_loop(
        [{"role": "user", "content": "解释遍历"}], _state(),
        planner=planner, tools=[],
    ))

    assert text == "最终回答"
    assert [item["name"] for item in trace] == ["course_evidence"]
    assert executed, "模型请求的工具未被执行"


def test_loop_returns_direct_answer_without_tools():
    async def planner(messages, tools):
        return "直接回答"

    text, trace = asyncio.run(tool_loop.run_tool_loop(
        [{"role": "user", "content": "你好"}], _state(),
        planner=planner, tools=[],
    ))

    assert text == "直接回答"
    assert trace == []


def test_loop_stops_at_max_steps(monkeypatch):
    executed = []
    monkeypatch.setitem(
        TOOL_REGISTRY, "course_evidence",
        lambda **kw: executed.append(kw) or {"context": "", "fragments": []},
    )
    monkeypatch.setattr(
        tool_loop, "llm_invoke",
        AsyncMock(return_value="达到上限后的收尾回答"),
    )

    async def planner(messages, tools):
        return ToolPlan(tool_calls=[{
            "id": f"c{len(executed)}", "name": "course_evidence",
            "arguments": {"query": "q"},
        }])

    text, trace = asyncio.run(tool_loop.run_tool_loop(
        [{"role": "user", "content": "一直查"}], _state(),
        planner=planner, tools=[], max_steps=2,
    ))

    assert len(trace) == 2
    assert len(executed) == 2
    assert text == "达到上限后的收尾回答"


def test_loop_rejects_unauthorized_tool(monkeypatch):
    rounds = {"n": 0}

    async def planner(messages, tools):
        rounds["n"] += 1
        if rounds["n"] == 1:
            return ToolPlan(tool_calls=[{
                "id": "c1", "name": "sql_query", "arguments": {"sql": "select 1"},
            }])
        return "换一种方式回答"

    text, trace = asyncio.run(tool_loop.run_tool_loop(
        [{"role": "user", "content": "查一下"}], _state(),
        planner=planner, tools=[],
    ))

    assert text == "换一种方式回答"
    assert trace[0]["result"]["error"]
    assert "无权" in trace[0]["result"]["error"]


def test_loop_degrades_on_tool_timeout(monkeypatch):
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

    assert "超时" in trace[0]["result"]["error"]
    assert text == "数据暂不可用,先给通用思路"


# ---------- 按角色暴露工具 ----------

def test_tool_schemas_filtered_by_role():
    student_tools = {item["name"] for item in tool_executor.tool_schemas_for_role("student")}
    assert "course_evidence" in student_tools
    assert "profile_query" in student_tools
    assert "sql_query" not in student_tools


# ---------- tutor 按需检索 ----------

def test_tutor_skips_retrieval_for_small_talk(monkeypatch):
    calls = []
    monkeypatch.setitem(
        TOOL_REGISTRY, "course_evidence",
        lambda **kw: calls.append(kw) or {"context": "", "fragments": []},
    )

    async def fake_llm(messages, sink=None, tools=None):
        return "你好,有什么可以帮你?"

    monkeypatch.setattr(tutor_module, "llm_invoke", fake_llm)
    asyncio.run(tutor_module.tutor_node(
        _state(messages=[{"role": "user", "content": "你好"}]),
    ))

    assert calls == [], "寒暄不应触发课程检索"


def test_tutor_forces_retrieval_for_course_question(monkeypatch):
    calls = []
    monkeypatch.setitem(
        TOOL_REGISTRY, "course_evidence",
        lambda **kw: calls.append(kw) or {
            "context": "[1] (来源: 第3章_二叉树.pdf) 遍历分为前中后序",
            "fragments": [],
        },
    )

    async def fake_llm(messages, sink=None, tools=None):
        return "先从根节点开始思考。"

    monkeypatch.setattr(tutor_module, "llm_invoke", fake_llm)
    result = asyncio.run(tutor_module.tutor_node(_state()))

    assert len(calls) == 1, "课程事实题应至少检索一次"
    labels = [item["label"] for item in result["sources"]]
    assert "第3章_二叉树.pdf" in labels
