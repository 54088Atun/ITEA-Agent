"""写操作先预览再执行(P0-6)

覆盖:
- 批量写动作只返回确认卡片,课程状态不变、审计零写入
- 一句话「取消」后仍是 0 变更,且不写审计
- 一句话「确认」后才执行并写 operation_logs
- 同一确认重复提交只执行一次
- 预览参数非法时不生成卡片,也不写库
- 短句意图识别不会把长句误判成确认/取消
"""
import asyncio
import importlib
import json
import time

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.session import Base
from app.models.course import Course
from app.models.log import OperationLog, SystemConfig
from app.models.user import User

admin_module = importlib.import_module("app.agent.nodes.admin")


def _db_session():
    engine = create_engine("sqlite:///:memory:", poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[
        User.__table__, Course.__table__,
        OperationLog.__table__, SystemConfig.__table__,
    ])
    TestingSession = sessionmaker(bind=engine)
    with TestingSession() as db:
        db.add_all([
            User(
                id=1, role="admin", admin_level="super", status="active",
                name="超级管理员", email="root@example.com", password_hash="x",
            ),
            User(
                id=2, role="admin", admin_level="observer", status="active",
                name="观察员", email="observer@example.com", password_hash="x",
            ),
        ])
        db.add_all([
            Course(id=11, teacher_id=1, name="离散数学", code="C11", audit_status="pending"),
            Course(id=12, teacher_id=1, name="数据结构", code="C12", audit_status="pending"),
            Course(id=13, teacher_id=1, name="操作系统", code="C13", audit_status="approved"),
        ])
        db.commit()
    return engine, TestingSession


def _state(message: str, pending: dict | None = None, **overrides):
    state = {
        "messages": [{"role": "user", "content": message}],
        "session_id": "write-preview",
        "user_id": 1,
        "user_role": "admin",
        "user_name": "超级管理员",
        "admin_level": "super",
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
        "pending_action": pending or {},
        "stream_queue": None,
    }
    state.update(overrides)
    return state


async def _fake_llm(messages, tools=None, sink=None):
    return "已生成确认卡片,请确认后执行"


def _events(queue):
    items = []
    while not queue.empty():
        kind, payload = queue.get_nowait()
        if kind != "event":
            continue
        items.append(json.loads(payload[len("data: "):].strip()))
    return items


async def _preview(TestingSession, monkeypatch):
    """跑一次预览,返回(节点结果, SSE 事件)"""
    monkeypatch.setattr(admin_module, "SessionLocal", TestingSession)
    monkeypatch.setattr(admin_module, "llm_invoke", _fake_llm)

    async def fake_decide(state):
        return {"key": "course.audit", "args": {"audit_status": "approved"}}

    monkeypatch.setattr(admin_module, "_decide_action", fake_decide)
    queue = asyncio.Queue()
    result = await admin_module.admin_node(_state("全部通过待审核课程", stream_queue=queue))
    return result, _events(queue)


def test_write_action_returns_preview_without_touching_data(monkeypatch):
    engine, TestingSession = _db_session()
    try:
        result, events = asyncio.run(_preview(TestingSession, monkeypatch))

        assert result["pending_action"]["action"] == "course.audit"
        assert result["pending_action"]["params"] == {"audit_status": "approved"}
        assert result["pending_action"]["confirmation_token"]
        assert result["pending_action"]["idempotency_key"]

        confirm_events = [e for e in events if e["type"] == "confirm_required"]
        assert len(confirm_events) == 1
        card = confirm_events[0]["data"]
        assert card["count"] == 2
        assert card["truncated"] is False
        assert [item["id"] for item in card["items"]] == [11, 12]
        assert card["message"] == "将把 2 门课程通过"
        assert card["confirmation_token"] == result["pending_action"]["confirmation_token"]

        with TestingSession() as db:
            statuses = {course.id: course.audit_status for course in db.query(Course).all()}
            assert statuses[11] == "pending"
            assert statuses[12] == "pending"
            assert db.query(OperationLog).count() == 0
    finally:
        engine.dispose()


def test_cancel_keeps_zero_changes_and_no_audit(monkeypatch):
    engine, TestingSession = _db_session()
    try:
        result, events = asyncio.run(_preview(TestingSession, monkeypatch))
        pending = result["pending_action"]

        async def fail_decide(state):
            raise AssertionError("取消时不应再识别新动作")

        monkeypatch.setattr(admin_module, "_decide_action", fail_decide)
        queue = asyncio.Queue()
        cancelled = asyncio.run(admin_module.admin_node(
            _state("取消", pending=pending, stream_queue=queue),
        ))

        assert cancelled["pending_action"] == {}
        tool_results = [e for e in _events(queue) if e["type"] == "tool_result"]
        assert "未做任何变更" in tool_results[0]["data"]["message"]

        with TestingSession() as db:
            assert all(
                course.audit_status != "approved" or course.id == 13
                for course in db.query(Course).all()
            )
            assert db.query(OperationLog).count() == 0
    finally:
        engine.dispose()


def test_confirm_executes_and_writes_audit(monkeypatch):
    engine, TestingSession = _db_session()
    try:
        preview_result, _ = asyncio.run(_preview(TestingSession, monkeypatch))
        pending = preview_result["pending_action"]

        queue = asyncio.Queue()
        confirmed = asyncio.run(admin_module.admin_node(
            _state("确认", pending=pending, stream_queue=queue),
        ))

        assert confirmed["pending_action"] == {}
        tool_results = [e for e in _events(queue) if e["type"] == "tool_result"]
        assert tool_results[0]["data"]["ok"] is True

        with TestingSession() as db:
            assert db.query(Course).filter(Course.id.in_([11, 12])).filter(
                Course.audit_status == "approved",
            ).count() == 2
            logs = db.query(OperationLog).all()
            assert len(logs) == 1
            assert logs[0].action == "approve"
            assert logs[0].target_type == "course"
            detail = json.loads(logs[0].detail)
            assert detail["course_ids"] == [11, 12]
            assert detail["source"] == "assistant"
    finally:
        engine.dispose()


def test_repeated_confirm_runs_once(monkeypatch):
    engine, TestingSession = _db_session()
    try:
        preview_result, _ = asyncio.run(_preview(TestingSession, monkeypatch))
        pending = preview_result["pending_action"]

        first = asyncio.run(admin_module.admin_node(
            _state("确认", pending=pending),
        ))
        second = asyncio.run(admin_module.admin_node(
            _state("确认", pending=pending),
        ))

        assert first["pending_action"] == {}
        assert second["pending_action"] == {}
        with TestingSession() as db:
            assert db.query(OperationLog).count() == 1
    finally:
        engine.dispose()


def test_invalid_params_do_not_create_card(monkeypatch):
    engine, TestingSession = _db_session()
    try:
        monkeypatch.setattr(admin_module, "SessionLocal", TestingSession)
        monkeypatch.setattr(admin_module, "llm_invoke", _fake_llm)

        async def fake_decide(state):
            return {"key": "course.audit", "args": {"audit_status": "bogus"}}

        monkeypatch.setattr(admin_module, "_decide_action", fake_decide)
        queue = asyncio.Queue()
        result = asyncio.run(admin_module.admin_node(
            _state("全部通过待审核课程", stream_queue=queue),
        ))

        assert result["pending_action"] == {}
        assert not [e for e in _events(queue) if e["type"] == "confirm_required"]
        with TestingSession() as db:
            assert db.query(OperationLog).count() == 0
    finally:
        engine.dispose()


def test_observer_cannot_preview_write_action(monkeypatch):
    engine, TestingSession = _db_session()
    try:
        monkeypatch.setattr(admin_module, "SessionLocal", TestingSession)
        monkeypatch.setattr(admin_module, "llm_invoke", _fake_llm)

        async def fake_decide(state):
            return {"key": "course.audit", "args": {"audit_status": "approved"}}

        monkeypatch.setattr(admin_module, "_decide_action", fake_decide)
        queue = asyncio.Queue()
        result = asyncio.run(admin_module.admin_node(_state(
            "全部通过待审核课程", user_id=2, admin_level="observer",
            user_name="观察员", stream_queue=queue,
        )))

        assert result["pending_action"] == {}
        assert not [e for e in _events(queue) if e["type"] == "confirm_required"]
        with TestingSession() as db:
            assert db.query(OperationLog).count() == 0
    finally:
        engine.dispose()


def test_expired_pending_is_not_executed(monkeypatch):
    engine, TestingSession = _db_session()
    try:
        preview_result, _ = asyncio.run(_preview(TestingSession, monkeypatch))
        pending = dict(preview_result["pending_action"], expires_at=time.time() - 1)

        called = {"decide": 0}

        async def fake_decide(state):
            called["decide"] += 1
            return None

        monkeypatch.setattr(admin_module, "_decide_action", fake_decide)
        result = asyncio.run(admin_module.admin_node(_state("确认", pending=pending)))

        assert called["decide"] == 1
        with TestingSession() as db:
            assert db.query(OperationLog).count() == 0
        assert result["pending_action"] == pending
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    "text, expected",
    [
        ("确认", "confirm"),
        ("执行", "confirm"),
        ("取消", "cancel"),
        ("算了", "cancel"),
        ("帮我看看还有哪些待审核课程", ""),
        ("", ""),
    ],
)
def test_write_intent_only_matches_short_commands(text, expected):
    assert admin_module._write_intent(text) == expected
