import asyncio
import importlib
import inspect
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.agent import graph as agent_graph
from app.agent.nodes.reflect import reflect_node
from app.api import admin as admin_api
from app.api import chat as chat_api
from app.core.deps import get_current_user, require_admin
from app.core.security import create_access_token
from app.db.session import Base
from app.models.course import Course, CourseMaterial, KnowledgePoint
from app.models.log import InteractionLog, RiskLog
from app.models.user import User
from app.schemas.agent import ChatRequest


AI_TAG = "[AI 辅助参考,请管理员复核]"


def _state(**overrides):
    state = {
        "messages": [{"role": "user", "content": "汇总平台数据"}],
        "session_id": "admin-test",
        "user_id": 99,
        "user_role": "admin",
        "user_name": "观察员",
        "admin_level": "observer",
        "course_id": None,
        "intent": "chat",
        "branch": "admin",
        "task_plan": [],
        "current_step": 0,
        "tool_calls": [],
        "tool_results": {},
        "rag_context": "",
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


def _stats_session():
    engine = create_engine("sqlite:///:memory:", poolclass=StaticPool)
    Base.metadata.create_all(
        engine,
        tables=[
            User.__table__, Course.__table__, CourseMaterial.__table__,
            KnowledgePoint.__table__, RiskLog.__table__, InteractionLog.__table__,
        ],
    )
    TestingSession = sessionmaker(bind=engine)
    with TestingSession() as db:
        db.add_all([
            User(id=1, role="teacher", name="教师", email="t@example.com", password_hash="x"),
            User(id=2, role="student", name="学生甲", email="s1@example.com", password_hash="x"),
            User(id=3, role="student", name="学生乙", email="s2@example.com", password_hash="x"),
        ])
        db.add_all([
            Course(id=1, teacher_id=1, name=" pending ", code="C1", audit_status="pending"),
            Course(id=2, teacher_id=1, name=" approved ", code="C2", audit_status="approved"),
        ])
        db.add_all([
            KnowledgePoint(id=1, course_id=1, name="知识点一"),
            KnowledgePoint(id=2, course_id=1, name="知识点二"),
            CourseMaterial(id=1, course_id=1, type="courseware", title="课件", file_path="x"),
            RiskLog(id=1, user_id=2, request_content="风险请求"),
            InteractionLog(id=1, user_id=2, session_id="s1", role="student", content="一"),
            InteractionLog(id=2, user_id=3, session_id="s2", role="student", content="二"),
        ])
        db.commit()
    return engine, TestingSession


def test_admin_prepare_skips_course_memory_and_rag(monkeypatch):
    memory_load = MagicMock(return_value={"profile_snapshot": {"unexpected": True}})
    rag_search = MagicMock(return_value={"context": "无关课程内容", "fragments": [{}]})
    monkeypatch.setattr(agent_graph, "memory_load_node", memory_load)
    monkeypatch.setattr(agent_graph, "rag_search", rag_search)

    result = agent_graph.prepare_node(_state())

    assert result == {"profile_snapshot": {}, "rag_context": "", "course_id": None}
    memory_load.assert_not_called()
    rag_search.assert_not_called()


def test_admin_is_registered_and_routed_in_real_graph():
    assert "admin" in agent_graph.BUSINESS_NODES
    assert agent_graph.route_by_branch(_state()) == "admin"
    assert "admin" in agent_graph.build_graph().get_graph().nodes


def test_admin_reflect_does_not_require_course_rag(monkeypatch):
    llm = AsyncMock(return_value='{"passed": true}')
    monkeypatch.setattr("app.agent.nodes.reflect.llm_invoke", llm)

    result = asyncio.run(reflect_node(_state(
        final_output=f"平台 algorithm 统计解读。{AI_TAG}",
    )))

    assert result["reflection_passed"] is True
    llm.assert_not_called()


def test_admin_reflect_keeps_ai_tag_check(monkeypatch):
    monkeypatch.setattr(
        "app.agent.nodes.reflect.llm_invoke",
        AsyncMock(return_value='{"passed": true}'),
    )

    result = asyncio.run(reflect_node(_state(final_output="只读平台解读")))

    assert result["reflection_passed"] is False
    assert "标识" in result["reflection_notes"]


def test_admin_node_aggregates_read_only_stats_and_streams(monkeypatch):
    admin_module = importlib.import_module("app.agent.nodes.admin")
    engine, TestingSession = _stats_session()
    monkeypatch.setattr(admin_module, "SessionLocal", TestingSession)
    captured = {}

    async def fake_llm(messages, sink=None):
        captured["prompt"] = messages[0]["content"]
        await sink.put(("token", "平台只读解读"))
        return "平台只读解读"

    monkeypatch.setattr(admin_module, "llm_invoke", fake_llm)
    queue = asyncio.Queue()
    try:
        result = asyncio.run(admin_module.admin_node(_state(stream_queue=queue)))

        assert result["final_output"] == f"平台只读解读\n\n{AI_TAG}"
        assert queue.get_nowait() == ("token", "平台只读解读")
        assert "observer" in captured["prompt"]
        assert '"student": 2' in captured["prompt"]
        assert '"pending": 1' in captured["prompt"]
        assert '"knowledge_points": 2' in captured["prompt"]
        assert '"materials": 1' in captured["prompt"]
        assert '"risk_logs": 1' in captured["prompt"]
        assert '"interaction_logs": 2' in captured["prompt"]
    finally:
        engine.dispose()


def test_admin_node_llm_failure_has_explicit_fallback(monkeypatch):
    admin_module = importlib.import_module("app.agent.nodes.admin")
    monkeypatch.setattr(admin_module, "_load_platform_stats", lambda: {"users_by_role": {}})

    async def fail_llm(messages, sink=None):
        raise RuntimeError("model unavailable")

    monkeypatch.setattr(admin_module, "llm_invoke", fail_llm)
    result = asyncio.run(admin_module.admin_node(_state()))

    assert "暂时无法响应" in result["final_output"]
    assert AI_TAG in result["final_output"]


def test_real_admin_graph_streams_branch_token_and_done(monkeypatch):
    admin_module = importlib.import_module("app.agent.nodes.admin")
    monkeypatch.setattr(
        admin_module, "_load_platform_stats",
        lambda: {"users_by_role": {"admin": 1}},
    )
    captured = {}

    async def fake_llm(messages, sink=None):
        captured["prompt"] = messages[0]["content"]
        await sink.put(("token", "只读回答"))
        return "只读回答"

    monkeypatch.setattr(admin_module, "llm_invoke", fake_llm)
    monkeypatch.setattr(chat_api, "get_graph", agent_graph.build_graph)
    monkeypatch.setattr(chat_api, "_log_interaction", AsyncMock())
    monkeypatch.setattr(chat_api, "_sessions", {})
    monkeypatch.setattr(chat_api, "_session_owner", {})
    user = SimpleNamespace(id=99, role="admin", admin_level="observer", name="观察员")

    async def collect():
        return [
            event async for event in chat_api.stream_agent_response(
                ChatRequest(session_id="admin-test", course_id=None, message="汇总平台数据"),
                user, MagicMock(), force_branch="admin",
            )
        ]

    events = [json.loads(frame[6:]) for frame in asyncio.run(collect())]
    types = [event["type"] for event in events]

    assert "admin" in chat_api.ANSWER_NODES
    assert types[0] == "branch"
    assert events[0]["data"] == {"branch": "admin", "intent": "chat"}
    assert "token" in types
    assert types[-1] == "done"
    assert "只读回答" in "".join(
        event["data"]["content"] for event in events if event["type"] == "token"
    )
    assert AI_TAG in "".join(
        event["data"]["content"] for event in events if event["type"] == "token"
    )
    assert "observer" in captured["prompt"]


def test_admin_chat_stream_route_uses_admin_permission_and_forced_branch(monkeypatch):
    endpoint = admin_api.admin_chat_stream
    signature = inspect.signature(endpoint)
    assert signature.parameters["admin"].default.dependency is require_admin
    assert any(
        route.path == "/admin/chat/stream"
        and "POST" in route.methods
        and route.endpoint is endpoint
        for route in admin_api.router.routes
    )
    captured = {}

    async def fake_stream(req, user, db, force_branch=None, request=None):
        captured.update(force_branch=force_branch, request=request, user=user)
        yield "data: {}\n\n"

    monkeypatch.setattr(admin_api, "stream_agent_response", fake_stream)
    request = MagicMock()
    user = SimpleNamespace(id=1, role="admin", admin_level="normal")
    response = asyncio.run(endpoint(
        ChatRequest(session_id=None, course_id=None, message="平台概况"),
        request, user, MagicMock(),
    ))

    assert isinstance(response, StreamingResponse)
    assert response.media_type == "text/event-stream"
    assert response.headers["Cache-Control"] == "no-cache"

    async def consume():
        async for _ in response.body_iterator:
            pass

    asyncio.run(consume())
    assert captured["force_branch"] == "admin"
    assert captured["request"] is request
    assert captured["user"] is user


@pytest.mark.parametrize(
    "role, admin_level, user_status, expected_status",
    [
        ("admin", "super", "active", None),
        ("admin", "normal", "active", None),
        ("admin", "observer", "active", None),
        ("admin", "normal", "disabled", 403),
        ("teacher", None, "active", 403),
        ("student", None, "active", 403),
    ],
)
def test_admin_chat_access_through_real_dependency_chain(
    role, admin_level, user_status, expected_status
):
    engine = create_engine("sqlite:///:memory:", poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[User.__table__])
    TestingSession = sessionmaker(bind=engine)
    with TestingSession() as db:
        user = User(
            id=1,
            role=role,
            admin_level=admin_level,
            name="权限测试",
            email=f"{role}-{admin_level}-{user_status}@example.com",
            password_hash="hash",
            status=user_status,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        token = create_access_token(user.id, user.role)

        if expected_status is None:
            current_user = get_current_user(token=token, db=db)
            assert require_admin(current_user).admin_level == admin_level
        else:
            with pytest.raises(HTTPException) as exc_info:
                require_admin(get_current_user(token=token, db=db))
            assert exc_info.value.status_code == expected_status
    engine.dispose()
