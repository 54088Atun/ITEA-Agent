"""回答来源标注(ST-02 / AG-12)

- 回答区分课程资料、学情数据与通用知识
- 来源清单由节点返回,页脚由对话层在安全裁决后统一追加
"""
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from app.agent import graph as agent_graph
from app.agent.llm import ToolPlan
from app.agent.nodes import reflect as reflect_module
from app.agent.nodes import teacher as teacher_module
from app.agent.nodes import tutor as tutor_module
from app.agent.sources import (
    append_sources_footer, build_sources, collect_course_sources, render_footer,
)
from app.agent.tools import TOOL_REGISTRY
from app.api import chat as chat_api
from app.schemas.agent import ChatRequest

RAG_CONTEXT = (
    "[1] (来源: 第3章_二叉树.pdf) 二叉树的遍历分为前序、中序、后序。\n\n"
    "[2] (来源: 第3章_二叉树.pdf) 层序遍历使用队列实现。\n\n"
    "[3] (来源: 实验指导.docx) 完成遍历实验并提交报告。"
)


def _state(**overrides):
    state = {
        "messages": [{"role": "user", "content": "解释二叉树的遍历"}],
        "session_id": "sources-test",
        "user_id": 1,
        "user_role": "student",
        "admin_level": None,
        "user_name": "学生",
        "course_id": 10,
        "intent": "chat",
        "branch": "tutor",
        "task_plan": [],
        "current_step": 0,
        "collaborate": False,
        "collab_plan": [],
        "collab_results": [],
        "tool_calls": [],
        "tool_results": {},
        "rag_context": "",
        "sources": [],
        "profile_snapshot": {},
        "profile_updates": {},
        "risk_flag": False,
        "risk_type": "",
        "reflection_passed": False,
        "reflection_notes": "",
        "reflection_count": 0,
        "final_output": "",
        "stream_queue": None,
    }
    state.update(overrides)
    return state


def test_collect_course_sources_dedupes_and_limits():
    assert collect_course_sources(RAG_CONTEXT) == ["第3章_二叉树.pdf", "实验指导.docx"]
    assert collect_course_sources("") == []
    assert collect_course_sources("(来源: A) (来源: B) (来源: C)", limit=2) == ["A", "B"]


def test_build_sources_marks_course_profile_and_general():
    sources = build_sources(
        RAG_CONTEXT, has_profile=True, extra_labels=["班级学情统计"],
    )
    labels = [item["label"] for item in sources]
    assert "第3章_二叉树.pdf" in labels
    assert "学情数据：掌握度 / 错题 / 复习记录" in labels
    assert "班级学情统计" in labels
    assert any("课程资料未覆盖" in label for label in labels)


def test_build_sources_without_course_marks_general_knowledge():
    sources = build_sources("", has_profile=False)
    assert len(sources) == 1
    assert sources[0]["type"] == "general"
    assert "未检索到本课程资料" in sources[0]["label"]


def test_append_sources_footer_is_idempotent():
    sources = build_sources(RAG_CONTEXT)
    output = append_sources_footer("回答正文", sources)
    assert output.startswith("回答正文")
    assert render_footer(sources) in output
    assert append_sources_footer(output, sources) == output
    assert append_sources_footer("", sources) == ""


def test_tutor_returns_course_and_profile_sources(monkeypatch):
    """P0-2:课程与学情均由工具按需取回,来源页脚仍完整"""
    monkeypatch.setitem(
        TOOL_REGISTRY, "course_evidence",
        lambda **kw: {"context": RAG_CONTEXT, "fragments": []},
    )
    monkeypatch.setitem(
        TOOL_REGISTRY, "profile_query",
        lambda **kw: {"summary": '{"weak_mastery":[{"point":"二叉树","level":0.4}]}'},
    )

    calls = {"n": 0}

    async def fake_llm(messages, sink=None, tools=None):
        calls["n"] += 1
        if calls["n"] == 1:
            return ToolPlan(tool_calls=[
                {"id": "c1", "name": "profile_query", "arguments": {}},
            ])
        return "先从根节点开始思考。"

    monkeypatch.setattr(tutor_module, "llm_invoke", fake_llm)
    result = asyncio.run(tutor_module.tutor_node(_state()))

    # 来源清单单独返回,不写入正文,避免被安全分级误判
    assert "**参考来源**" not in result["final_output"]
    types = {item["type"] for item in result["sources"]}
    assert types == {"course", "profile", "general"}
    labels = [item["label"] for item in result["sources"]]
    assert "第3章_二叉树.pdf" in labels


def test_teacher_marks_class_stats_source(monkeypatch):
    monkeypatch.setattr(teacher_module, "fetch_syllabus", lambda *a, **k: "课程大纲")
    monkeypatch.setitem(
        TOOL_REGISTRY, "course_evidence",
        lambda **kw: {"context": RAG_CONTEXT, "fragments": []},
    )
    monkeypatch.setitem(
        TOOL_REGISTRY, "stats_analyzer",
        lambda **kw: {"weak_points": ["递归"]},
    )

    calls = {"n": 0}

    async def fake_llm(messages, sink=None, tools=None):
        calls["n"] += 1
        if calls["n"] == 1:
            return ToolPlan(tool_calls=[
                {"id": "c1", "name": "course_evidence",
                 "arguments": {"query": "二叉树", "course_id": 10}},
                {"id": "c2", "name": "stats_analyzer",
                 "arguments": {"course_id": 10, "metric": "weakness"}},
            ])
        return "教学框架"

    monkeypatch.setattr(teacher_module, "llm_invoke", fake_llm)
    result = asyncio.run(teacher_module.teacher_node(_state(
        user_role="teacher",
        branch="teacher",
        messages=[{"role": "user", "content": "根据班级学情设计教学框架"}],
    )))

    labels = [item["label"] for item in result["sources"]]
    assert "班级学情统计" in labels
    assert "第3章_二叉树.pdf" in labels


def test_stream_response_appends_sources_footer(monkeypatch):
    """SSE 全链路:来源页脚追加在安全裁决之后,不触发敏感级别拦截"""
    monkeypatch.setitem(
        TOOL_REGISTRY, "course_evidence",
        lambda **kw: {"context": RAG_CONTEXT, "fragments": []},
    )
    monkeypatch.setitem(
        TOOL_REGISTRY, "profile_query",
        lambda **kw: {"summary": '{"weak_mastery":[{"point":"二叉树","level":0.4}]}'},
    )
    monkeypatch.setattr(
        reflect_module, "llm_invoke", AsyncMock(return_value='{"passed": true}'),
    )

    calls = {"n": 0}

    async def fake_llm(messages, sink=None, tools=None):
        calls["n"] += 1
        if calls["n"] == 1:
            return ToolPlan(tool_calls=[
                {"id": "c1", "name": "profile_query", "arguments": {}},
            ])
        text = "先从根节点开始思考。"
        if sink is not None:
            await sink.put(("token", text))
        return text

    monkeypatch.setattr(tutor_module, "llm_invoke", fake_llm)
    monkeypatch.setattr(chat_api, "get_graph", agent_graph.build_graph)
    # 课程可见性由 prepare_node 的用例单测覆盖;此处只验证来源页脚链路
    monkeypatch.setattr(agent_graph, "_visible_course_id", lambda state: 10)
    monkeypatch.setattr(chat_api, "_log_interaction", AsyncMock())
    monkeypatch.setattr(chat_api, "_persist_turn_sync", lambda *a, **k: None)
    monkeypatch.setattr(chat_api, "_sessions", {})
    monkeypatch.setattr(chat_api, "_session_owner", {})

    user = SimpleNamespace(id=1, role="student", admin_level=None, name="学生")

    async def collect():
        return [
            event async for event in chat_api.stream_agent_response(
                ChatRequest(
                    session_id="sources-sse", course_id=10,
                    message="解释二叉树的遍历",
                ),
                user, MagicMock(), force_branch="tutor",
            )
        ]

    events = [json.loads(frame[6:]) for frame in asyncio.run(collect())]
    tokens = "".join(e["data"]["content"] for e in events if e["type"] == "token")

    assert "**参考来源**" in tokens
    assert "第3章_二叉树.pdf" in tokens
    assert "学情数据" in tokens
    assert events[-1]["type"] == "done"
    assert events[-1]["data"]["security_level"] == "full"
    assert events[-1]["data"]["blocked"] is False


def test_general_knowledge_answer_has_no_course_source(monkeypatch):
    monkeypatch.setitem(
        TOOL_REGISTRY, "course_evidence",
        lambda **kw: {"context": "", "fragments": []},
    )

    async def fake_llm(messages, sink=None, tools=None):
        return "这是通用知识回答。"

    monkeypatch.setattr(tutor_module, "llm_invoke", fake_llm)
    result = asyncio.run(tutor_module.tutor_node(_state(course_id=None)))

    assert [item["type"] for item in result["sources"]] == ["general"]
    assert "未检索到本课程资料" in result["sources"][0]["label"]
