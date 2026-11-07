"""P0-1 工具调用循环 + P0-2 检索按需化"""
import asyncio
import os
import subprocess
import tempfile
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest

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


# ---------- 高危工具确认与配额(共享执行边界) ----------

def test_loop_blocks_high_risk_tool_without_trusted_approval(monkeypatch):
    executed = []
    monkeypatch.setitem(
        TOOL_REGISTRY, "reminder_scheduler",
        lambda **kw: executed.append(kw) or {"scheduled": True},
    )
    rounds = {"n": 0}

    async def planner(messages, tools):
        rounds["n"] += 1
        if rounds["n"] == 1:
            return ToolPlan(tool_calls=[{
                "id": "r1", "name": "reminder_scheduler",
                "arguments": {"task_type": "review", "confirmed": True},
            }])
        return "请确认后再安排提醒"

    text, trace = asyncio.run(tool_loop.run_tool_loop(
        [{"role": "user", "content": "明天提醒我复习"}], _state(),
        planner=planner, tools=[],
    ))

    assert executed == []
    assert trace[0]["result"]["requires_confirmation"] is True
    assert text == "请确认后再安排提醒"


def test_loop_executes_high_risk_tool_with_trusted_approval(monkeypatch):
    executed = []
    monkeypatch.setitem(
        TOOL_REGISTRY, "reminder_scheduler",
        lambda **kw: executed.append(kw) or {"scheduled": True},
    )
    rounds = {"n": 0}

    async def planner(messages, tools):
        rounds["n"] += 1
        if rounds["n"] == 1:
            return ToolPlan(tool_calls=[{
                "id": "r1", "name": "reminder_scheduler",
                "arguments": {"task_type": "review"},
            }])
        return "已安排"

    text, trace = asyncio.run(tool_loop.run_tool_loop(
        [{"role": "user", "content": "明天提醒我复习"}], _state(),
        planner=planner, tools=[],
        approval=["reminder_scheduler"],
    ))

    assert len(executed) == 1
    assert "confirmed" not in executed[0]
    assert trace[0]["result"]["ok"] is True
    assert text == "已安排"


def test_loop_forced_call_requires_trusted_approval(monkeypatch):
    executed = []
    monkeypatch.setitem(
        TOOL_REGISTRY, "reminder_scheduler",
        lambda **kw: executed.append(kw) or {"scheduled": True},
    )

    async def planner(messages, tools):
        return "需要人工确认"

    _, trace = asyncio.run(tool_loop.run_tool_loop(
        [{"role": "user", "content": "安排提醒"}], _state(),
        planner=planner, tools=[],
        forced_call={
            "id": "forced-1", "name": "reminder_scheduler",
            "arguments": {"task_type": "review"},
        },
    ))

    assert executed == []
    assert trace[0]["result"]["requires_confirmation"] is True


def test_loop_forced_call_executes_with_trusted_approval(monkeypatch):
    executed = []
    monkeypatch.setitem(
        TOOL_REGISTRY, "reminder_scheduler",
        lambda **kw: executed.append(kw) or {"scheduled": True},
    )

    async def planner(messages, tools):
        return "已安排"

    _, trace = asyncio.run(tool_loop.run_tool_loop(
        [{"role": "user", "content": "安排提醒"}], _state(),
        planner=planner, tools=[],
        forced_call={
            "id": "forced-1", "name": "reminder_scheduler",
            "arguments": {"task_type": "review"},
        },
        approval=["reminder_scheduler"],
    ))

    assert len(executed) == 1
    assert trace[0]["result"]["ok"] is True


def test_loop_enforces_per_tool_quota(monkeypatch):
    executed = []
    monkeypatch.setitem(
        TOOL_REGISTRY, "rag_search",
        lambda **kw: executed.append(kw) or {"context": "", "fragments": []},
    )
    limit = 3
    calls = [{
        "id": f"q{i}", "name": "rag_search", "arguments": {"query": f"q{i}"},
    } for i in range(limit + 2)]

    async def planner(messages, tools):
        return ToolPlan(tool_calls=calls) if not executed else "资料已足够"

    _, trace = asyncio.run(tool_loop.run_tool_loop(
        [{"role": "user", "content": "连续检索"}], _state(),
        planner=planner, tools=[],
    ))

    assert len(executed) == limit
    assert "最多调用" in trace[-1]["result"]["error"]


# ---------- 按角色暴露工具 ----------

def test_tool_schemas_filtered_by_role():
    student_tools = {item["name"] for item in tool_executor.tool_schemas_for_role("student")}
    assert "course_evidence" in student_tools
    assert "profile_query" in student_tools
    assert "sql_query" not in student_tools


# ---------- 宿主机代码执行 fail-closed ----------

@pytest.fixture()
def host_execution_spy(monkeypatch, tmp_path):
    run = Mock(return_value=SimpleNamespace(stdout="", stderr="", returncode=0))
    env_copy = Mock(return_value={})
    tempfile_factory = MagicMock()
    temp_path = tmp_path / "legacy-host-execution.py"
    tempfile_factory.return_value.__enter__.return_value.name = str(temp_path)
    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setattr(tempfile, "NamedTemporaryFile", tempfile_factory)
    monkeypatch.setattr(os.environ, "copy", env_copy)
    return SimpleNamespace(
        run=run, env_copy=env_copy, tempfile=tempfile_factory, temp_path=temp_path,
    )


def _assert_no_host_execution(spy):
    assert spy.run.call_count == 0
    assert spy.tempfile.call_count == 0
    assert spy.env_copy.call_count == 0
    assert not spy.temp_path.exists()


def test_loop_rejects_legacy_code_executor_call(host_execution_spy):
    rounds = {"n": 0}

    async def planner(messages, tools):
        rounds["n"] += 1
        if rounds["n"] == 1:
            return ToolPlan(tool_calls=[{
                "id": "legacy-code", "name": "code_executor",
                "arguments": {"code": "print('must not run')", "language": "python"},
            }])
        return "已说明代码执行不可用"

    text, trace = asyncio.run(tool_loop.run_tool_loop(
        [{"role": "user", "content": "运行代码"}], _state(),
        planner=planner, tools=[],
    ))

    assert text == "已说明代码执行不可用"
    assert trace[0]["result"]["ok"] is False
    assert "不可用" in trace[0]["result"]["error"]
    _assert_no_host_execution(host_execution_spy)


def test_loop_rejects_forced_code_executor_call(host_execution_spy):
    async def planner(messages, tools):
        return "forced 调用已拒绝"

    text, trace = asyncio.run(tool_loop.run_tool_loop(
        [{"role": "user", "content": "运行代码"}], _state(),
        planner=planner, tools=[],
        forced_call={
            "id": "forced-code", "name": "code_executor",
            "arguments": {"code": "print('must not run')"},
        },
    ))

    assert text == "forced 调用已拒绝"
    assert trace[0]["result"]["ok"] is False
    assert "不可用" in trace[0]["result"]["error"]
    _assert_no_host_execution(host_execution_spy)


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
