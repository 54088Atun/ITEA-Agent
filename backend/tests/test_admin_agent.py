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
from app.models.log import AgentRun, AgentRunSpan, InteractionLog, RiskLog
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


def test_prepare_only_returns_visible_course_id():
    """prepare 不再预加载学情/RAG,数据由各 Agent 运行时直接调用数据 API"""
    result = agent_graph.prepare_node(_state())

    assert result == {"course_id": None}
    assert "profile_snapshot" not in result
    assert "rag_context" not in result


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


def test_admin_reflect_appends_ai_tag_without_rewrite(monkeypatch):
    """缺标注时确定性补齐即可,不再调用模型复核或触发重写"""
    monkeypatch.setattr(
        "app.agent.nodes.reflect.llm_invoke",
        AsyncMock(side_effect=AssertionError("缺标注不应触发 LLM 复核")),
    )

    result = asyncio.run(reflect_node(_state(final_output="只读平台解读")))

    assert result["reflection_passed"] is True
    assert AI_TAG in result["final_output"]


def test_admin_node_queries_data_via_tools_instead_of_snapshot(monkeypatch):
    """P0-5:只读数据改由 admin.* 工具按需查询,节点不再预取平台快照"""
    admin_module = importlib.import_module("app.agent.nodes.admin")
    captured = {}

    async def fake_llm(messages, sink=None):
        captured["prompt"] = messages[0]["content"]
        await sink.put(("token", "平台只读解读"))
        return "平台只读解读"

    monkeypatch.setattr(admin_module, "llm_invoke", fake_llm)
    queue = asyncio.Queue()

    result = asyncio.run(admin_module.admin_node(_state(stream_queue=queue)))

    assert result["final_output"] == f"平台只读解读\n\n{AI_TAG}"
    assert queue.get_nowait() == ("token", "平台只读解读")
    assert "observer" in captured["prompt"]
    # 工具目录进入提示词,旧快照字段不再预置
    assert "admin.course_list" in captured["prompt"]
    assert "admin.material_stats" in captured["prompt"]
    assert '"knowledge_points"' not in captured["prompt"]


def test_admin_node_llm_failure_has_explicit_fallback(monkeypatch):
    admin_module = importlib.import_module("app.agent.nodes.admin")

    async def fail_llm(messages, sink=None):
        raise RuntimeError("model unavailable")

    monkeypatch.setattr(admin_module, "llm_invoke", fail_llm)
    result = asyncio.run(admin_module.admin_node(_state()))

    assert "暂时无法响应" in result["final_output"]
    assert AI_TAG in result["final_output"]


def test_real_admin_graph_streams_branch_token_and_done(monkeypatch):
    admin_module = importlib.import_module("app.agent.nodes.admin")
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
    assert types[0] == "run"
    assert types[1] == "branch"
    assert events[1]["data"] == {"branch": "admin", "intent": "chat"}
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


def test_admin_agent_run_trace_missing_run_returns_404():
    engine = create_engine("sqlite:///:memory:", poolclass=StaticPool)
    Base.metadata.create_all(
        engine, tables=[AgentRun.__table__, AgentRunSpan.__table__],
    )
    TestingSession = sessionmaker(bind=engine)
    try:
        with TestingSession() as db:
            with pytest.raises(HTTPException) as exc_info:
                admin_api.admin_agent_run_trace(
                    run_id=999,
                    admin=SimpleNamespace(id=1, role="admin"),
                    db=db,
                )
            assert exc_info.value.status_code == 404
    finally:
        engine.dispose()


def test_admin_agent_run_trace_returns_empty_when_no_spans():
    engine = create_engine("sqlite:///:memory:", poolclass=StaticPool)
    Base.metadata.create_all(
        engine, tables=[AgentRun.__table__, AgentRunSpan.__table__],
    )
    TestingSession = sessionmaker(bind=engine)
    try:
        with TestingSession() as db:
            db.add(AgentRun(
                id=1, user_id=2, session_id="s1", role="admin",
                branch="admin", status="success",
            ))
            db.commit()

            result = admin_api.admin_agent_run_trace(
                run_id=1,
                admin=SimpleNamespace(id=1, role="admin"),
                db=db,
            )

            assert result == {"run_id": 1, "spans": []}
    finally:
        engine.dispose()


def test_admin_agent_run_trace_orders_spans_by_seq():
    engine = create_engine("sqlite:///:memory:", poolclass=StaticPool)
    Base.metadata.create_all(
        engine, tables=[AgentRun.__table__, AgentRunSpan.__table__],
    )
    TestingSession = sessionmaker(bind=engine)
    try:
        with TestingSession() as db:
            db.add(AgentRun(
                id=1, user_id=2, session_id="s1", role="admin",
                branch="admin", status="error",
            ))
            db.add_all([
                AgentRunSpan(
                    run_id=1, seq=2, kind="tool", name="stats.read",
                    status="error", payload='{"x":1}', result='{"ok":false}',
                    tokens=12, duration_ms=30, error="boom",
                ),
                AgentRunSpan(
                    run_id=1, seq=1, kind="route", name="router",
                    status="ok", payload='{"branch":"admin"}',
                    result='{"branch":"admin"}', tokens=5, duration_ms=10,
                ),
            ])
            db.commit()

            result = admin_api.admin_agent_run_trace(
                run_id=1,
                admin=SimpleNamespace(id=1, role="admin"),
                db=db,
            )

            assert result["run_id"] == 1
            spans = result["spans"]
            assert [s["seq"] for s in spans] == [1, 2]
            assert spans[0]["kind"] == "route"
            assert spans[1]["status"] == "error"
            assert spans[1]["error"] == "boom"
            assert spans[1]["tokens"] == 12
            assert spans[1]["duration_ms"] == 30
    finally:
        engine.dispose()
