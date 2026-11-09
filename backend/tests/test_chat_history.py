"""会话搜索/收藏/导出/摘要与断线续答/重试去重(AG-11 / AG-16)"""
import asyncio
import json

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import chat as chat_api
from app.db import session as db_session
from app.api.chat import (
    export_session, list_conversations, set_conversation_favorite,
    summarize_session,
)
from app.db.session import Base
from app.models.conversation import ChatMessage, Conversation
from app.models.course import Course
from app.models.user import User
from app.schemas.agent import (
    ChatRequest, ConversationFavorite, ConversationSecurityLevel,
)
from app.services import conversation_summary


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    seed(session)
    yield session
    session.close()
    engine.dispose()


def seed(db):
    db.add_all([
        User(id=1, role="student", name="小明", email="a@example.com",
             password_hash="x", status="active"),
        User(id=2, role="student", name="小红", email="b@example.com",
             password_hash="x", status="active"),
        Conversation(id=10, session_id="s-a", user_id=1,
                     title="数据结构复习", branch="tutor"),
        Conversation(id=11, session_id="s-b", user_id=1,
                     title="操作系统", branch="tutor"),
        Conversation(id=12, session_id="s-c", user_id=2,
                     title="别人的会话", branch="tutor"),
    ])
    db.add_all([
        ChatMessage(conversation_id=10, role="user", content="红黑树怎么旋转？"),
        ChatMessage(conversation_id=10, role="assistant", content="左旋与右旋的步骤"),
        ChatMessage(conversation_id=11, role="user", content="进程调度算法"),
        ChatMessage(conversation_id=12, role="user", content="红黑树"),
    ])
    db.commit()


def test_search_by_title_and_message(db):
    user = db.get(User, 1)

    by_message = list_conversations(keyword="红黑树", user=user, db=db)
    assert [i["session_id"] for i in by_message["items"]] == ["s-a"]

    by_title = list_conversations(keyword="操作系统", user=user, db=db)
    assert [i["session_id"] for i in by_title["items"]] == ["s-b"]

    all_items = list_conversations(user=user, db=db)
    assert {i["session_id"] for i in all_items["items"]} == {"s-a", "s-b"}


def test_favorite_filter_and_ownership(db):
    user = db.get(User, 1)
    result = set_conversation_favorite(
        "s-a", ConversationFavorite(favorite=True), user, db,
    )
    assert result["is_favorite"] is True

    only_fav = list_conversations(favorite_only=True, user=user, db=db)
    assert [i["session_id"] for i in only_fav["items"]] == ["s-a"]

    with pytest.raises(HTTPException) as exc:
        set_conversation_favorite(
            "s-c", ConversationFavorite(favorite=True), user, db,
        )
    assert exc.value.status_code == 404


def test_export_markdown_and_ownership(db):
    user = db.get(User, 1)
    response = export_session("s-a", user, db)
    body = response.body.decode("utf-8")
    assert "# 数据结构复习" in body
    assert "## 学生" in body and "红黑树怎么旋转？" in body
    assert "## AI 助教" in body
    assert "attachment" in response.headers["content-disposition"]

    with pytest.raises(HTTPException) as exc:
        export_session("s-c", user, db)
    assert exc.value.status_code == 404


def test_summary_cache_refresh_and_fallback(db, monkeypatch):
    user = db.get(User, 1)
    calls = {"count": 0}

    async def fake_llm(transcript):
        calls["count"] += 1
        return "围绕红黑树旋转展开，重点掌握左旋与右旋。"

    monkeypatch.setattr(conversation_summary, "_llm_summary", fake_llm)

    first = asyncio.run(summarize_session("s-a", False, user, db))
    assert first["cached"] is False
    assert "红黑树" in first["summary"]
    assert calls["count"] == 1

    cached = asyncio.run(summarize_session("s-a", False, user, db))
    assert cached["cached"] is True
    assert calls["count"] == 1

    refreshed = asyncio.run(summarize_session("s-a", True, user, db))
    assert refreshed["cached"] is False
    assert calls["count"] == 2

    async def boom(transcript):
        raise RuntimeError("llm down")

    monkeypatch.setattr(conversation_summary, "_llm_summary", boom)
    fallback = asyncio.run(summarize_session("s-b", True, user, db))
    assert "轮提问" in fallback["summary"]
    assert "进程调度算法" in fallback["summary"]


def test_answer_query_checks_owner(db, monkeypatch):
    monkeypatch.setattr(chat_api, "_answers", {
        "req-owner": {
            "status": "done", "user_id": 1, "session_id": "s-a",
            "content": "完整答案", "branch": "tutor",
            "security_level": "full", "error": "",
        },
    })

    result = chat_api.get_answer("req-owner", db.get(User, 1))
    assert result["status"] == "done"
    assert result["content"] == "完整答案"

    with pytest.raises(HTTPException) as exc:
        chat_api.get_answer("req-owner", db.get(User, 2))
    assert exc.value.status_code == 404
    with pytest.raises(HTTPException) as exc:
        chat_api.get_answer("req-missing", db.get(User, 1))
    assert exc.value.status_code == 404


def test_disconnected_stream_finishes_and_caches_answer(db, monkeypatch):
    class FakeGraph:
        async def astream(self, state, stream_mode, config=None):
            await state["stream_queue"].put(("token", "完整回答"))
            yield {"tutor": {"final_output": "完整回答"}}

    class DisconnectedRequest:
        async def is_disconnected(self):
            return True

    persisted = []

    async def fake_log(*args, **kwargs):
        return None

    monkeypatch.setattr(chat_api, "get_graph", lambda: FakeGraph())
    monkeypatch.setattr(chat_api, "_persist_turn_sync",
                        lambda *args: persisted.append(args))
    monkeypatch.setattr(chat_api, "_log_interaction", fake_log)
    monkeypatch.setattr(chat_api, "_answers", {})
    monkeypatch.setattr(chat_api, "_sessions", {})
    monkeypatch.setattr(chat_api, "_session_owner", {})
    state = {
        "session_id": "s-disconnected", "branch": "tutor", "course_id": None,
        "messages": [{"role": "user", "content": "问题"}],
    }

    async def collect():
        return [
            event async for event in chat_api._stream_graph(
                state, db, db.get(User, 1),
                request=DisconnectedRequest(), request_id="req-disconnected",
            )
        ]

    assert asyncio.run(collect()) == []
    cached = chat_api._answers["req-disconnected"]
    assert cached["status"] == "done"
    assert cached["content"] == "完整回答"
    assert persisted[0][-1] == "req-disconnected"


def test_retry_replays_cache_and_reports_running(db, monkeypatch):
    cache = {
        "req-replay": {
            "status": "done", "user_id": 1, "session_id": "s-a",
            "content": "去重后的完整答案", "branch": "tutor",
            "security_level": "full", "error": "",
        },
    }
    monkeypatch.setattr(chat_api, "_answers", cache)

    async def unexpected_stream(*args, **kwargs):
        raise AssertionError("命中缓存后不应重新跑图")
        yield  # pragma: no cover

    monkeypatch.setattr(chat_api, "stream_agent_response", unexpected_stream)
    user = db.get(User, 1)

    async def collect_response():
        response = await chat_api.chat_stream(
            ChatRequest(message="重复提问", request_id="req-replay"),
            object(), user, db,
        )
        return [frame async for frame in response.body_iterator]

    frames = asyncio.run(collect_response())
    events = [json.loads(frame[6:]) for frame in frames]
    assert "".join(
        event["data"]["content"] for event in events if event["type"] == "token"
    ) == "去重后的完整答案"
    assert events[-1]["type"] == "done"

    cache["req-replay"]["status"] = "running"
    frames = asyncio.run(collect_response())
    events = [json.loads(frame[6:]) for frame in frames]
    assert events[0]["type"] == "error"
    assert "正在处理中" in events[0]["data"]["message"]


def test_persist_turn_dedupes_request_id(db, monkeypatch):
    TestingSession = sessionmaker(bind=db.get_bind())
    monkeypatch.setattr(chat_api, "SessionLocal", TestingSession)

    chat_api._persist_turn_sync(
        1, "s-dedup", "tutor", None, "原问题", "原回答", "req-dedup",
    )
    chat_api._persist_turn_sync(
        1, "s-dedup", "tutor", None, "原问题", "重复回答", "req-dedup",
    )

    conv = db.query(Conversation).filter_by(session_id="s-dedup").one()
    rows = db.query(ChatMessage).filter_by(conversation_id=conv.id).all()
    assert [(row.role, row.content) for row in rows] == [
        ("user", "原问题"), ("assistant", "原回答"),
    ]
    assert rows[-1].request_id == "req-dedup"


def test_security_override_permissions_and_persistence(db):
    """决策 #4:admin 可调整任意会话,教师仅限自己课程,学生拒绝"""
    db.add_all([
        User(id=3, role="teacher", name="教师", email="teacher@example.com",
             password_hash="x", status="active"),
        User(id=4, role="admin", name="管理员", email="admin@example.com",
             password_hash="x", status="active"),
        Course(id=100, teacher_id=3, name=" owned ", code="OWN"),
        Course(id=101, teacher_id=99, name="other", code="OTHER"),
    ])
    db.query(Conversation).filter_by(session_id="s-a").update({"course_id": 100})
    db.query(Conversation).filter_by(session_id="s-c").update({"course_id": 101})
    db.commit()
    teacher = db.get(User, 3)

    result = chat_api.set_conversation_security_level(
        "s-a", ConversationSecurityLevel(security_level="manual"), teacher, db,
    )
    assert result["security_level"] == "manual"
    assert result["level_label"] == "敏感"
    assert db.get(Conversation, 10).security_level == "manual"

    with pytest.raises(HTTPException) as exc:
        chat_api.set_conversation_security_level(
            "s-a", ConversationSecurityLevel(security_level="full"),
            db.get(User, 1), db,
        )
    assert exc.value.status_code == 403

    with pytest.raises(HTTPException) as exc:
        chat_api.set_conversation_security_level(
            "s-c", ConversationSecurityLevel(security_level="full"), teacher, db,
        )
    assert exc.value.status_code == 403

    admin = db.get(User, 4)
    result = chat_api.set_conversation_security_level(
        "s-c", ConversationSecurityLevel(security_level="confidential"), admin, db,
    )
    assert result["security_level"] == "confidential"
    assert db.get(Conversation, 12).security_level == "confidential"

    result = chat_api.set_conversation_security_level(
        "s-c", ConversationSecurityLevel(security_level=None), admin, db,
    )
    assert result["security_level"] is None
    assert db.get(Conversation, 12).security_level is None


def _collect_override_stream(db, monkeypatch, answer):
    class FakeGraph:
        async def astream(self, state, stream_mode, config=None):
            await state["stream_queue"].put(("token", answer))
            yield {"tutor": {"final_output": answer}}

    async def fake_log(*args, **kwargs):
        return None

    monkeypatch.setattr(chat_api, "get_graph", lambda: FakeGraph())
    monkeypatch.setattr(chat_api, "_persist_turn_sync", lambda *args: None)
    monkeypatch.setattr(chat_api, "_log_interaction", fake_log)
    monkeypatch.setattr(chat_api, "_answers", {})
    monkeypatch.setattr(chat_api, "_sessions", {})
    monkeypatch.setattr(chat_api, "_session_owner", {})

    async def collect():
        frames = [
            frame async for frame in chat_api.stream_agent_response(
                ChatRequest(session_id="s-a", message="问题"), db.get(User, 1), db,
            )
        ]
        return [json.loads(frame[6:]) for frame in frames]

    return asyncio.run(collect())


def test_stream_manual_downgrade_is_not_blocked_by_auto_rules(db, monkeypatch):
    conv = db.get(Conversation, 10)
    conv.security_level = "full"

    events = _collect_override_stream(db, monkeypatch, "我的学情和错题分析")

    assert "".join(
        event["data"]["content"] for event in events if event["type"] == "token"
    ) == "我的学情和错题分析"
    assert events[-1]["data"]["security_level"] == "full"
    assert events[-1]["data"]["blocked"] is False


def test_stream_manual_upgrade_never_leaks_sensitive_token(db, monkeypatch):
    conv = db.get(Conversation, 10)
    conv.security_level = "confidential"

    events = _collect_override_stream(db, monkeypatch, "普通内容")
    tokens = "".join(
        event["data"]["content"] for event in events if event["type"] == "token"
    )

    assert "普通内容" not in tokens
    assert "无权查看" in tokens
    assert events[-1]["data"]["security_level"] == "confidential"
    assert events[-1]["data"]["blocked"] is True


def test_sqlite_chat_message_request_id_migration_preserves_history(monkeypatch):
    engine = create_engine("sqlite:///:memory:", poolclass=StaticPool)
    monkeypatch.setattr(db_session, "engine", engine)
    User.__table__.create(engine)
    Conversation.__table__.create(engine)
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE conversations DROP COLUMN security_level"))
        conn.execute(text(
            "CREATE TABLE chat_messages ("
            "id INTEGER PRIMARY KEY, conversation_id INTEGER NOT NULL, "
            "role VARCHAR(20) NOT NULL, content TEXT NOT NULL, created_at DATETIME)"
        ))
    db_session._migrate_exam_record_columns()
    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        db.add_all([
            User(id=1, role="student", name="小明", email="legacy@example.com",
                 password_hash="x", status="active"),
            Conversation(id=10, session_id="legacy-session", user_id=1,
                         title="旧会话", branch="tutor"),
        ])
        db.commit()
        with engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO chat_messages "
                "(id, conversation_id, role, content, created_at) VALUES "
                "(1, 10, 'user', '旧消息', CURRENT_TIMESTAMP)"
            ))

        db_session._migrate_exam_record_columns()
        db_session._migrate_exam_record_columns()

        result = chat_api.get_history("legacy-session", db.get(User, 1), db)
        assert result["messages"] == [{"role": "user", "content": "旧消息"}]
        with engine.begin() as conn:
            columns = {
                row[1] for row in conn.execute(text("PRAGMA table_info(chat_messages)"))
            }
            original = conn.execute(text(
                "SELECT role, content FROM chat_messages WHERE id = 1"
            )).one()
        with engine.begin() as conn:
            conversation_columns = {
                row[1] for row in conn.execute(text("PRAGMA table_info(conversations)"))
            }
        assert "request_id" in columns
        assert "security_level" in conversation_columns
        assert tuple(original) == ("user", "旧消息")
    finally:
        db.close()
        engine.dispose()


def test_persisted_user_text_keeps_raw_input(db):
    """会话落库只写用户原始输入,附件拼接内容只送模型(P1-9)"""
    user = db.get(User, 1)
    chat_api._sessions["unit-raw"] = []
    chat_api._sessions["unit-raw2"] = []
    try:
        state = chat_api._build_initial_state(
            ChatRequest(
                session_id="unit-raw",
                message="请解释红黑树",
                attachments=[{"type": "image", "text": "题干文字"}],
            ),
            user,
        )
        assert state["user_input"] == "请解释红黑树"
        assert "题干文字" in state["messages"][-1]["content"]
        assert chat_api._persist_user_text(state) == "请解释红黑树"

        only_attachment = chat_api._build_initial_state(
            ChatRequest(
                session_id="unit-raw2",
                attachments=[{"type": "image", "text": "题干文字"}],
            ),
            user,
        )
        assert chat_api._persist_user_text(only_attachment) == "（多模态输入）"
    finally:
        chat_api._sessions.pop("unit-raw", None)
        chat_api._sessions.pop("unit-raw2", None)
