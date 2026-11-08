"""AG-10 三级角色能力矩阵、功能声明与工具授权"""
import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.agent.nodes import tool_executor
from app.agent.nodes.collab import ROLE_ALLOWED_AGENTS
from app.api import records
from app.services.capabilities import role_capabilities
from app.services.feature_flags import public_features


EXPECTED_TOOLS = {
    "student": [
        "rag_search", "course_evidence", "profile_query",
        "reminder_scheduler",
    ],
    "teacher": [
        "rag_search", "course_evidence", "profile_query",
        "doc_generator", "stats_analyzer", "sql_query",
        "reminder_scheduler", "web.search", "web.fetch",
    ],
    "admin": [
        "rag_search", "course_evidence", "profile_query",
        "doc_generator", "stats_analyzer",
        "sql_query", "reminder_scheduler",
        "admin.course_list", "admin.material_stats", "admin.user_lookup",
        "admin.risk_summary", "admin.config_get",
        "web.search", "web.fetch",
        "project.search_code", "project.read_file", "project.git_diff",
        "project.search_logs", "project.run_tests", "project.db_schema",
    ],
}
EXPECTED_SCOPES = {
    "student": "enrolled_approved_courses",
    "teacher": "owned_courses",
    "admin": "all_courses",
}


def test_role_capabilities_matrix():
    for role in ("student", "teacher", "admin"):
        assert role_capabilities(role) == {
            "role": role,
            "tools": EXPECTED_TOOLS[role],
            "agents": ROLE_ALLOWED_AGENTS[role],
            "course_data_scope": EXPECTED_SCOPES[role],
        }


def test_public_features_declares_capabilities_and_defaults_to_student():
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None

    assert public_features(db)["capabilities"] == role_capabilities("student")
    assert public_features(db, role="teacher")["capabilities"] == role_capabilities("teacher")


def test_features_route_passes_authenticated_user_role(monkeypatch):
    db = MagicMock()
    user = SimpleNamespace(role="admin")
    expected = {"capabilities": role_capabilities("admin")}
    mock_public_features = MagicMock(return_value=expected)
    monkeypatch.setattr(records, "public_features", mock_public_features)

    assert records.get_features(user=user, db=db) is expected
    mock_public_features.assert_called_once_with(db, "admin")


def _state(role):
    return {"user_role": role, "course_id": 7, "user_id": 11}


@pytest.mark.parametrize("name", ["doc_generator", "stats_analyzer"])
def test_student_cannot_execute_teacher_only_tools(monkeypatch, name):
    calls = []

    def target():
        calls.append(name)
        return {"executed": True}

    monkeypatch.setitem(tool_executor.TOOL_REGISTRY, name, target)

    result = tool_executor._execute_single(
        {"name": name, "arguments": {}}, _state("student"),
    )

    assert calls == [], "越权目标函数被执行"
    assert result["error"]
    assert result["available"] == EXPECTED_TOOLS["student"]


@pytest.mark.parametrize(
    "name,arguments",
    [
        ("rag_search", {"query": "等价类", "course_id": 7}),
        ("doc_generator", {"doc_type": "lesson_plan", "data": {}}),
        ("stats_analyzer", {"course_id": 7, "metric": "weakness"}),
        ("reminder_scheduler", {"user_id": 11, "task_type": "review"}),
    ],
)
def test_teacher_can_execute_role_tools(monkeypatch, name, arguments):
    def target(**kwargs):
        return {"executed": name, "arguments": kwargs}

    monkeypatch.setitem(tool_executor.TOOL_REGISTRY, name, target)

    payload = tool_executor._execute_single(
        {"name": name, "arguments": arguments}, _state("teacher"),
        approval=[name],
    )
    assert payload["ok"] is True
    assert payload["data"] == {"executed": name, "arguments": arguments}


def test_allowed_tool_preserves_default_argument_injection(monkeypatch):
    def target(course_id, user_id, **kwargs):
        return {"course_id": course_id, "user_id": user_id}

    monkeypatch.setitem(tool_executor.TOOL_REGISTRY, "reminder_scheduler", target)

    payload = tool_executor._execute_single(
        {"name": "reminder_scheduler", "arguments": {"task_type": "review"}},
        _state("teacher"),
        approval=["reminder_scheduler"],
    )
    assert payload["ok"] is True
    assert payload["data"] == {"course_id": 7, "user_id": 11}


def test_unknown_tool_behavior_is_unchanged():
    result = tool_executor._execute_single(
        {"name": "missing_tool", "arguments": {}}, _state("student"),
    )

    assert result["ok"] is False
    assert result["error"] == "未知工具: missing_tool"
    assert result["available"] == list(tool_executor.TOOL_REGISTRY.keys())


def test_allowed_tool_exception_behavior_is_unchanged(monkeypatch):
    def target(**kwargs):
        raise RuntimeError("boom")

    monkeypatch.setitem(tool_executor.TOOL_REGISTRY, "doc_generator", target)

    result = tool_executor._execute_single(
        {"name": "doc_generator",
         "arguments": {"doc_type": "lesson_plan", "data": {}}},
        _state("teacher"),
    )
    assert result["ok"] is False
    assert "工具 doc_generator 执行失败: boom" in result["error"]


@pytest.fixture()
def tutor_stubs(monkeypatch):
    """隔离 tutor 节点的外部依赖,捕获送入模型的消息"""
    from app.agent.nodes import tutor
    from app.agent.tools import TOOL_REGISTRY

    captured = {}
    # P0-2:检索改由工具按需执行,测试中替换为固定返回,避免触达真实数据源
    monkeypatch.setitem(
        TOOL_REGISTRY, "course_evidence",
        lambda **kw: {"context": "", "fragments": []},
    )
    monkeypatch.setattr(tutor, "load_prompt", lambda name: "system")
    monkeypatch.setattr(tutor, "render_prompt", lambda template, **kw: "system")
    monkeypatch.setattr(tutor, "build_sources", lambda *a, **k: [])

    async def fake_llm(messages, sink=None, tools=None):
        captured["messages"] = messages
        return "先想一想遍历的终止条件"

    monkeypatch.setattr(tutor, "llm_invoke", fake_llm)
    return tutor, captured


def _message_texts(captured):
    return [str((item or {}).get("content") or "") for item in captured["messages"]]


def test_tutor_does_not_execute_user_code(tutor_stubs):
    """代码排错降级为静态分析:不得出现沙箱执行结果"""
    tutor, captured = tutor_stubs
    state = {
        "user_role": "student", "course_id": 7, "user_id": 11,
        "messages": [{"role": "user", "content": "```python\nprint(1)\n```"}],
    }

    asyncio.run(tutor.tutor_node(state))

    texts = _message_texts(captured)
    assert any("系统不执行用户代码" in text for text in texts)
    assert not any("沙箱执行结果" in text for text in texts)


def test_tutor_code_hint_covers_javascript(tutor_stubs):
    """语言识别不再丢弃 JS/TS,提示词按真实语言说明"""
    tutor, captured = tutor_stubs
    state = {
        "user_role": "student", "course_id": 7, "user_id": 11,
        "messages": [{"role": "user", "content": "```js\nconsole.log(1)\n```"}],
    }

    asyncio.run(tutor.tutor_node(state))

    assert any("javascript" in text for text in _message_texts(captured))


@pytest.fixture()
def teacher_tool_stubs(monkeypatch):
    from app.agent.nodes import teacher
    from app.agent.tools import TOOL_REGISTRY

    calls = []
    monkeypatch.setattr(teacher, "fetch_syllabus", lambda *a, **k: "")
    monkeypatch.setattr(teacher, "build_sources", lambda *a, **k: [])
    monkeypatch.setitem(
        TOOL_REGISTRY, "doc_generator",
        lambda **kw: calls.append(kw) or {"file_url": "/x", "file_name": "a"},
    )
    return teacher, calls


def test_teacher_generates_doc_for_teacher_role(teacher_tool_stubs, monkeypatch):
    from app.agent.llm import ToolPlan

    teacher, calls = teacher_tool_stubs
    called = {"n": 0}

    async def fake_llm(messages, sink=None, tools=None):
        called["n"] += 1
        if called["n"] == 1:
            return ToolPlan(tool_calls=[{
                "id": "c1", "name": "doc_generator",
                "arguments": {
                    "doc_type": "lesson_plan",
                    "data": {"course_name": "测试课程"},
                },
            }])
        return "教案框架"

    monkeypatch.setattr(teacher, "llm_invoke", fake_llm)
    state = {
        "user_role": "teacher", "course_id": 7, "user_id": 11,
        "messages": [{"role": "user", "content": "导出教案"}],
    }

    asyncio.run(teacher.teacher_node(state))

    assert len(calls) == 1


def test_teacher_skips_doc_when_role_lacks_tool(teacher_tool_stubs, monkeypatch):
    from app.agent.llm import ToolPlan

    teacher, calls = teacher_tool_stubs
    called = {"n": 0}

    async def fake_llm(messages, sink=None, tools=None):
        called["n"] += 1
        if called["n"] == 1:
            return ToolPlan(tool_calls=[{
                "id": "c1", "name": "doc_generator",
                "arguments": {
                    "doc_type": "lesson_plan",
                    "data": {"course_name": "测试课程"},
                },
            }])
        return "教案框架"

    monkeypatch.setattr(teacher, "llm_invoke", fake_llm)
    state = {
        "user_role": "student", "course_id": 7, "user_id": 11,
        "messages": [{"role": "user", "content": "导出教案"}],
    }

    asyncio.run(teacher.teacher_node(state))

    assert calls == [], "角色无权时仍生成了文档"
