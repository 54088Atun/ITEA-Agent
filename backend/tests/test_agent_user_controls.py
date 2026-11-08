"""P2-5 用户可控:执行时间线、运行取消、中途调整计划与归属校验

覆盖:
- 本人可按 run_id 拉取步骤时间线,解析 payload/result 并汇总工具与 token
- 他人运行 403,管理员可查看,记录不存在 404
- SSE 在首个分支事件前下发 run_id,供前端暂停与时间线使用
- 运行中途可提交计划调整:仅本人 running 运行可提交,下一超级步生效
"""
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.agent.graph as agent_graph
import app.services.agent_runs as runs_module
from app.agent.nodes.plan_patch import plan_patch_node
from app.api import agent as agent_api
from app.api import chat as chat_api
from app.db.session import Base
from app.models.log import AgentCheckpoint, AgentPlanRevision, AgentRun, AgentRunSpan
from app.schemas.agent import ChatRequest, PlanRevisionCreate


def _session():
    engine = create_engine("sqlite:///:memory:", poolclass=StaticPool)
    Base.metadata.create_all(
        engine, tables=[AgentRun.__table__, AgentRunSpan.__table__],
    )
    db = sessionmaker(bind=engine)()
    db.add(AgentRun(
        id=1, user_id=7, session_id="s1", role="student",
        branch="tutor", status="success", duration_ms=120,
    ))
    db.add_all([
        AgentRunSpan(
            run_id=1, seq=1, kind="route", name="router", status="ok",
            payload='{"branch": "tutor"}', result='{"branch": "tutor"}',
            duration_ms=10,
        ),
        AgentRunSpan(
            run_id=1, seq=2, kind="tool", name="rag_search", status="ok",
            result='{"ok": true}', tokens=30, duration_ms=80,
        ),
        AgentRunSpan(
            run_id=1, seq=3, kind="answer", name="tutor", status="ok",
            result='{"chars": 20}', tokens=20, duration_ms=30,
        ),
    ])
    db.commit()
    return engine, db


def test_timeline_returns_owner_spans_in_order():
    engine, db = _session()
    try:
        result = agent_api.agent_run_timeline(
            1, user=SimpleNamespace(id=7, role="student"), db=db,
        )

        assert result["run"]["branch"] == "tutor"
        assert [item["seq"] for item in result["timeline"]] == [1, 2, 3]
        assert result["timeline"][0]["kind_label"] == "路由"
        assert result["timeline"][0]["payload"] == {"branch": "tutor"}
        assert result["timeline"][1]["result"] == {"ok": True}
        assert result["summary"] == {
            "steps": 3, "tools": ["rag_search"], "tokens": 50,
        }
    finally:
        db.close()
        engine.dispose()


def test_timeline_rejects_other_users_and_allows_admin():
    engine, db = _session()
    try:
        with pytest.raises(HTTPException) as exc:
            agent_api.agent_run_timeline(
                1, user=SimpleNamespace(id=8, role="student"), db=db,
            )
        assert exc.value.status_code == 403

        admin_result = agent_api.agent_run_timeline(
            1, user=SimpleNamespace(id=99, role="admin"), db=db,
        )
        assert admin_result["summary"]["steps"] == 3
    finally:
        db.close()
        engine.dispose()


def test_timeline_missing_run_returns_404():
    engine, db = _session()
    try:
        with pytest.raises(HTTPException) as exc:
            agent_api.agent_run_timeline(
                404, user=SimpleNamespace(id=7, role="student"), db=db,
            )
        assert exc.value.status_code == 404
    finally:
        db.close()
        engine.dispose()


def test_stream_emits_run_id_before_branch(monkeypatch):
    class FakeGraph:
        async def astream(self, state, stream_mode="updates", config=None):
            if False:
                yield {}

    monkeypatch.setattr(chat_api, "get_graph", lambda: FakeGraph())
    monkeypatch.setattr(chat_api, "start_run", lambda *a, **k: 42)
    monkeypatch.setattr(chat_api, "finish_run", lambda *a, **k: None)
    monkeypatch.setattr(chat_api, "_log_interaction", AsyncMock())
    monkeypatch.setattr(chat_api, "_persist_turn_sync", lambda *a, **k: None)
    monkeypatch.setattr(chat_api, "_sessions", {})
    monkeypatch.setattr(chat_api, "_session_owner", {})

    user = SimpleNamespace(id=7, role="student", admin_level=None, name="学生")

    async def collect():
        return [
            event async for event in chat_api.stream_agent_response(
                ChatRequest(session_id="timeline-sse", message="你好"),
                user, MagicMock(),
            )
        ]

    events = [json.loads(frame[6:]) for frame in asyncio.run(collect())]

    assert events[0]["type"] == "run"
    assert events[0]["data"]["run_id"] == 42
    assert events[-1]["type"] == "done"


# ---------- 运行中途调整计划 ----------

def _plan_session():
    engine = create_engine("sqlite:///:memory:", poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[
        AgentRun.__table__, AgentPlanRevision.__table__, AgentCheckpoint.__table__,
    ])
    db = sessionmaker(bind=engine)()
    db.add_all([
        AgentRun(id=1, user_id=7, session_id="s1", role="student",
                 branch="teacher", status="running"),
        AgentRun(id=2, user_id=7, session_id="s2", role="student",
                 branch="teacher", status="success"),
        AgentRun(id=3, user_id=8, session_id="s3", role="student",
                 branch="teacher", status="running"),
    ])
    db.commit()
    return engine, db


def test_revise_plan_requires_owner_and_running_run():
    engine, db = _plan_session()
    try:
        student = SimpleNamespace(id=7, role="student")
        created = agent_api.revise_agent_plan(
            1, PlanRevisionCreate(instruction="只看 3 班的提交率"), user=student, db=db,
        )
        assert created["status"] == "pending"
        assert created["run_id"] == 1
        assert created["session_id"] == "s1"

        plan = agent_api.agent_run_plan(1, user=student, db=db)
        assert plan["status"] == "running"
        assert plan["task_plan"] == []
        assert [item["instruction"] for item in plan["revisions"]] == ["只看 3 班的提交率"]

        with pytest.raises(HTTPException) as exc:
            agent_api.revise_agent_plan(
                3, PlanRevisionCreate(instruction="越权调整"), user=student, db=db,
            )
        assert exc.value.status_code == 403

        with pytest.raises(HTTPException) as exc:
            agent_api.revise_agent_plan(
                2, PlanRevisionCreate(instruction="任务已结束"), user=student, db=db,
            )
        assert exc.value.status_code == 409

        with pytest.raises(HTTPException) as exc:
            agent_api.revise_agent_plan(
                1, PlanRevisionCreate(instruction="   "), user=student, db=db,
            )
        assert exc.value.status_code == 400

        with pytest.raises(HTTPException) as exc:
            agent_api.revise_agent_plan(
                1, PlanRevisionCreate(instruction="x" * 501), user=student, db=db,
            )
        assert exc.value.status_code == 400

        with pytest.raises(HTTPException) as exc:
            agent_api.agent_run_plan(1, user=SimpleNamespace(id=8, role="student"), db=db)
        assert exc.value.status_code == 403
    finally:
        db.close()
        engine.dispose()


def test_revise_plan_limits_pending_revisions():
    engine, db = _plan_session()
    try:
        student = SimpleNamespace(id=7, role="student")
        for i in range(runs_module.MAX_PLAN_REVISIONS):
            agent_api.revise_agent_plan(
                1, PlanRevisionCreate(instruction=f"调整 {i}"), user=student, db=db,
            )
        with pytest.raises(HTTPException) as exc:
            agent_api.revise_agent_plan(
                1, PlanRevisionCreate(instruction="再调一次"), user=student, db=db,
            )
        assert exc.value.status_code == 400
    finally:
        db.close()
        engine.dispose()


def test_plan_patch_node_merges_instruction_and_marks_applied(monkeypatch):
    engine = create_engine(
        "sqlite:///:memory:", poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine, tables=[AgentPlanRevision.__table__])
    factory = sessionmaker(bind=engine)
    session = factory()
    session.add(AgentPlanRevision(
        run_id=5, session_id="s1", user_id=7, instruction="只看 3 班",
    ))
    session.commit()
    session.close()
    monkeypatch.setattr(runs_module, "SessionLocal", factory)

    state = {
        "run_id": 5,
        "messages": [{"role": "user", "content": "统计近 4 周提交率"}],
        "task_plan": [],
        "current_step": 0,
    }
    result = asyncio.run(plan_patch_node(state))

    assert [item["instruction"] for item in result["plan_revisions"]] == ["只看 3 班"]
    merged = result["messages"][-1]["content"]
    assert merged.startswith("统计近 4 周提交率")
    assert "【计划调整,请优先满足】只看 3 班" in merged
    assert result["task_plan"] == [
        {"step": 1, "action": "revise", "instruction": "只看 3 班"},
    ]
    assert result["current_step"] == 1

    check = factory()
    try:
        row = check.query(AgentPlanRevision).first()
        assert row.status == "applied" and row.applied_at is not None
    finally:
        check.close()

    # 已生效的调整不会重复应用,且清空标记避免条件边再次回跳
    again = asyncio.run(plan_patch_node({**state, **result}))
    assert again == {"plan_revisions": []}

    engine.dispose()


def test_expire_plan_revisions_marks_unused_pending(monkeypatch):
    engine = create_engine(
        "sqlite:///:memory:", poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine, tables=[AgentPlanRevision.__table__])
    factory = sessionmaker(bind=engine)
    session = factory()
    session.add(AgentPlanRevision(
        run_id=6, session_id="s2", user_id=7, instruction="未消费",
    ))
    session.commit()
    session.close()
    monkeypatch.setattr(runs_module, "SessionLocal", factory)

    runs_module.expire_plan_revisions(6)

    check = factory()
    try:
        assert check.query(AgentPlanRevision).first().status == "expired"
    finally:
        check.close()
    engine.dispose()


def test_plan_patch_routes_back_to_business_node():
    assert agent_graph.route_after_plan_patch(
        {"plan_revisions": [{"id": 1}], "branch": "teacher"}
    ) == "teacher"
    assert agent_graph.route_after_plan_patch(
        {"plan_revisions": [{"id": 1}], "branch": "team"}
    ) == "collab_merge"
    assert agent_graph.route_after_plan_patch(
        {"plan_revisions": [], "branch": "teacher"}
    ) == "planner"
    assert "plan_patch" in agent_graph.build_graph().get_graph().nodes


def test_stream_emits_plan_revised_and_resets_before_answer(monkeypatch):
    class FakeGraph:
        async def astream(self, state, stream_mode="updates", config=None):
            yield {"plan_patch": {"plan_revisions": [
                {"id": 1, "instruction": "只看 3 班"},
            ]}}
            yield {"tutor": {"final_output": "按 3 班重答 [AI 辅助参考,请师生审核]"}}

    monkeypatch.setattr(chat_api, "get_graph", lambda: FakeGraph())
    monkeypatch.setattr(chat_api, "start_run", lambda *a, **k: 43)
    monkeypatch.setattr(chat_api, "finish_run", lambda *a, **k: None)
    monkeypatch.setattr(chat_api, "expire_plan_revisions", lambda *a, **k: None)
    monkeypatch.setattr(chat_api, "write_span", lambda *a, **k: None)
    monkeypatch.setattr(chat_api, "_log_interaction", AsyncMock())
    monkeypatch.setattr(chat_api, "_persist_turn_sync", lambda *a, **k: None)
    monkeypatch.setattr(chat_api, "_sessions", {})
    monkeypatch.setattr(chat_api, "_session_owner", {})

    user = SimpleNamespace(id=7, role="student", admin_level=None, name="学生")

    async def collect():
        return [
            event async for event in chat_api.stream_agent_response(
                ChatRequest(session_id="plan-sse", message="统计提交率"),
                user, MagicMock(),
            )
        ]

    events = [json.loads(frame[6:]) for frame in asyncio.run(collect())]
    types = [item["type"] for item in events]

    assert events[0]["type"] == "run"
    assert "plan_revised" in types
    reset_index = types.index("reset")
    revised_index = types.index("plan_revised")
    token_index = next(
        i for i, item in enumerate(events)
        if item["type"] == "token" and "按 3 班重答" in item["data"]["content"]
    )
    assert reset_index < revised_index < token_index
    assert events[-1]["type"] == "done"
