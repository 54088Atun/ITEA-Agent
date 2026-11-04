"""P1-5 可靠执行:检查点落盘、持久化幂等键与死信队列"""
import asyncio
import json
from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.agent.checkpoint import DBCheckpointSaver, graph_config, thread_id_of
from app.api import agent as agent_api
from app.api import chat as chat_api
from app.db.session import Base
from app.models.log import AgentCheckpoint, AgentDeadLetter, AgentRun
from app.models.user import User
from app.services import agent_runs as runs_module


def _session_factory():
    engine = create_engine(
        "sqlite:///:memory:", poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine, tables=[
        User.__table__, AgentRun.__table__, AgentCheckpoint.__table__,
        AgentDeadLetter.__table__,
    ])
    return sessionmaker(bind=engine)


def _checkpoint(checkpoint_id: str, final: str = "回答") -> dict:
    return {
        "v": 1,
        "id": checkpoint_id,
        "ts": "2026-01-01T00:00:00+00:00",
        "channel_values": {"final_output": final, "stream_queue": object()},
        "channel_versions": {"final_output": "1"},
        "versions_seen": {},
        "updated_channels": ["final_output"],
    }


CONFIG = {"configurable": {"thread_id": "session:s1", "checkpoint_ns": ""}}


# ---------- 检查点 ----------

def test_checkpointer_roundtrip_drops_runtime_channel():
    saver = DBCheckpointSaver(_session_factory())
    result = saver.put(
        CONFIG, _checkpoint("cp-1"), {"source": "loop", "step": 0}, {"final_output": "1"},
    )
    assert result["configurable"]["checkpoint_id"] == "cp-1"

    item = saver.get_tuple(CONFIG)
    assert item is not None
    assert item.checkpoint["id"] == "cp-1"
    assert item.checkpoint["channel_values"] == {"final_output": "回答"}
    assert item.metadata == {"source": "loop", "step": 0}
    assert item.pending_writes == []


def test_checkpointer_latest_list_before_and_delete():
    saver = DBCheckpointSaver(_session_factory())
    for idx, (cid, parent) in enumerate(zip(["cp-a", "cp-b", "cp-c"], [None, "cp-a", "cp-b"])):
        cfg = {
            **CONFIG,
            "configurable": {**CONFIG["configurable"], "checkpoint_id": parent},
        }
        saver.put(cfg, _checkpoint(cid, final=f"第{idx}步"),
                  {"source": "loop", "step": idx}, {"final_output": str(idx)})

    latest = saver.get_tuple(CONFIG)
    assert latest.checkpoint["id"] == "cp-c"

    listed = [item.checkpoint["id"] for item in saver.list(CONFIG)]
    assert listed == ["cp-a", "cp-b", "cp-c"]

    limited = [item.checkpoint["id"] for item in saver.list(CONFIG, limit=2)]
    assert limited == ["cp-a", "cp-b"]

    before = [item.checkpoint["id"] for item in saver.list(
        CONFIG,
        before={"configurable": {**CONFIG["configurable"], "checkpoint_id": "cp-b"}},
    )]
    assert before == ["cp-a"]

    saver.delete_thread(CONFIG["configurable"]["thread_id"])
    assert saver.get_tuple(CONFIG) is None


def test_checkpointer_async_wrappers():
    saver = DBCheckpointSaver(_session_factory())

    async def scenario():
        await saver.aput(
            CONFIG, _checkpoint("cp-1"), {"source": "loop", "step": 0}, {},
        )
        item = await saver.aget_tuple(CONFIG)
        assert item is not None and item.checkpoint["id"] == "cp-1"
        items = [it async for it in saver.alist(CONFIG)]
        assert len(items) == 1
        await saver.adelete_thread(CONFIG["configurable"]["thread_id"])

    asyncio.run(scenario())


def test_graph_config_binds_thread_and_run():
    config = graph_config("s1", run_id=9)
    assert config["configurable"]["thread_id"] == thread_id_of("s1")
    assert config["configurable"]["run_id"] == 9


# ---------- 持久化幂等键 ----------

def test_find_run_by_request_prefers_finished_run():
    session = _session_factory()()
    now = datetime.utcnow()
    session.add_all([
        AgentRun(id=1, user_id=7, role="student", session_id="s1",
                 request_id="req-1", status="running", created_at=now),
        AgentRun(id=2, user_id=7, role="student", session_id="s1",
                 request_id="req-1", status="success", output_preview="完成",
                 created_at=now, finished_at=now),
    ])
    session.commit()

    found = runs_module.find_run_by_request(session, "req-1", 7)
    assert found["id"] == 2 and found["status"] == "success"
    assert runs_module.find_run_by_request(session, "req-1", 8) is None
    assert runs_module.find_run_by_request(session, "", 7) is None


def test_mark_stale_running_as_failed_creates_dead_letter(monkeypatch):
    factory = _session_factory()
    monkeypatch.setattr(runs_module, "SessionLocal", factory)
    session = factory()
    session.add_all([
        AgentRun(id=1, user_id=7, role="student", session_id="s1",
                 request_id="req-old", status="running",
                 input_preview="旧问题",
                 created_at=datetime.utcnow() - timedelta(hours=1)),
        AgentRun(id=2, user_id=7, role="student", session_id="s1",
                 request_id="req-new", status="running",
                 created_at=datetime.utcnow()),
    ])
    session.commit()

    assert runs_module.mark_stale_running_as_failed(600) == 1
    session.expire_all()

    assert session.get(AgentRun, 1).status == "failed"
    assert session.get(AgentRun, 2).status == "running"
    letters = session.query(AgentDeadLetter).all()
    assert len(letters) == 1
    assert letters[0].run_id == 1 and letters[0].request_id == "req-old"


# ---------- 死信队列 ----------

def test_dead_letter_lifecycle(monkeypatch):
    factory = _session_factory()
    monkeypatch.setattr(runs_module, "SessionLocal", factory)
    session = factory()
    dead_id = runs_module.add_dead_letter(
        user_id=7, run_id=1, session_id="s1", request_id="req-1",
        reason="模型超时", payload={"message": "问题", "session_id": "s1"},
    )
    assert dead_id

    listing = runs_module.list_dead_letters(session, user_id=7)
    assert listing["total"] == 1
    assert listing["items"][0]["payload"] == {"message": "问题", "session_id": "s1"}

    detail = runs_module.get_dead_letter(session, dead_id)
    assert detail["status"] == "pending"

    assert runs_module.mark_dead_letter_replayed(session, dead_id, 99) == "replayed"
    detail = runs_module.get_dead_letter(session, dead_id)
    assert detail["retry_count"] == 1 and detail["last_run_id"] == 99

    assert runs_module.discard_dead_letter(session, dead_id) == "discarded"
    assert runs_module.list_dead_letters(session, status="discarded")["total"] == 1
    assert runs_module.get_dead_letter(session, 12345) is None


# ---------- 运行记录映射 ----------

@pytest.mark.parametrize("run_status,expected", [
    ("success", "done"),
    ("blocked", "blocked"),
    ("cancelled", "cancelled"),
    ("running", "running"),
    ("failed", "error"),
])
def test_record_from_run_maps_status(run_status, expected):
    record = chat_api._record_from_run({
        "user_id": 7, "session_id": "s1", "status": run_status,
        "branch": "tutor", "output_preview": "内容", "error": "",
    })
    assert record["status"] == expected
    assert record["content"] == "内容"


# ---------- 恢复状态重建 ----------

def test_build_resume_state_filters_internal_channels(monkeypatch):
    monkeypatch.setattr(chat_api, "load_latest_state", lambda sid, rid=None: {
        "channel_values": {
            "session_id": "s1",
            "messages": [{"role": "user", "content": "问题"}],
            "final_output": "已有回答",
            "branch:to:router": "internal",
            "stream_queue": object(),
        },
    })
    state = chat_api.build_resume_state("s1", 1)
    assert state["final_output"] == "已有回答"
    assert state["messages"]
    assert "branch:to:router" not in state
    assert state["stream_queue"] is None


def test_build_resume_state_returns_none_without_checkpoint(monkeypatch):
    monkeypatch.setattr(chat_api, "load_latest_state", lambda sid, rid=None: None)
    assert chat_api.build_resume_state("s1", 1) is None


# ---------- 管理接口 ----------

def _user_and_session(factory=None):
    factory = factory or _session_factory()
    session = factory()
    session.add(User(id=7, role="student", name="学生",
                     email="s@example.com", password_hash="x"))
    session.commit()
    return session, session.get(User, 7)


def test_dead_letter_list_and_discard(monkeypatch):
    factory = _session_factory()
    monkeypatch.setattr(runs_module, "SessionLocal", factory)
    session, user = _user_and_session(factory)
    dead_id = runs_module.add_dead_letter(
        user_id=7, session_id="s1", request_id="req-1",
        reason="模型超时", payload={"session_id": "s1", "message": "问题"},
    )
    listing = agent_api.list_agent_dead_letters(None, 1, 20, user, session)
    assert listing["total"] == 1

    result = agent_api.discard_agent_dead_letter(dead_id, user, session)
    assert result["status"] == "discarded"
    with pytest.raises(HTTPException) as exc:
        agent_api.discard_agent_dead_letter(dead_id, user, session)
    assert exc.value.status_code == 400


def test_dead_letter_replay_starts_background(monkeypatch):
    factory = _session_factory()
    monkeypatch.setattr(runs_module, "SessionLocal", factory)
    session, user = _user_and_session(factory)
    dead_id = runs_module.add_dead_letter(
        user_id=7, session_id="s1", request_id="req-1",
        reason="模型超时", payload={"session_id": "s1", "message": "原问题"},
    )
    captured = {}
    monkeypatch.setattr(
        agent_api, "replay_in_background",
        lambda req, owner: captured.update(req=req, owner=owner),
    )

    result = asyncio.run(agent_api.replay_agent_dead_letter(dead_id, user, session))
    assert result["status"] == "replaying"
    assert captured["req"].message == "原问题"
    assert captured["req"].request_id.startswith("replay-")
    assert runs_module.get_dead_letter(session, dead_id)["status"] == "replayed"


def test_resume_requires_checkpoint_and_rejects_running(monkeypatch):
    session, user = _user_and_session()
    session.add(AgentRun(id=2, user_id=7, role="student", session_id="s1", status="failed"))
    session.add(AgentRun(id=3, user_id=7, role="student", session_id="s1", status="running"))
    session.commit()

    with pytest.raises(HTTPException) as exc:
        asyncio.run(agent_api.resume_agent_run(2, user, session))
    assert exc.value.status_code == 400  # 无检查点

    with pytest.raises(HTTPException) as exc:
        asyncio.run(agent_api.resume_agent_run(3, user, session))
    assert exc.value.status_code == 409  # 仍在执行

    monkeypatch.setattr(
        agent_api, "build_resume_state",
        lambda sid, rid: {"session_id": sid, "messages": []},
    )
    captured = {}
    monkeypatch.setattr(
        agent_api, "resume_in_background",
        lambda state, owner, rid: captured.update(state=state, request_id=rid),
    )
    result = asyncio.run(agent_api.resume_agent_run(2, user, session))
    assert result["status"] == "resuming"
    assert captured["request_id"].startswith("resume-")
