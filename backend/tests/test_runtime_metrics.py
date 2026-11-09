"""NF-06 进程内运行指标与四类执行接入"""
import asyncio
import importlib
import inspect
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.agent.nodes.collab
from app.api import admin as admin_api
from app.api import chat as chat_api
from app.core.config import settings
from app.core.deps import require_admin
from app.db.session import Base
from app.models.course import Course, CourseMaterial
from app.models.user import User
from app.schemas.agent import ChatRequest
from app.services import asr, material_parse_jobs
from app.services.runtime_metrics import (
    record_runtime_metric, reset_runtime_metrics, runtime_metrics_snapshot,
)


@pytest.fixture(autouse=True)
def clean_runtime_metrics():
    reset_runtime_metrics()
    yield
    reset_runtime_metrics()


def test_metrics_count_failure_rate_and_average_duration():
    empty = runtime_metrics_snapshot()
    assert set(empty) == {"parse", "index", "asr", "sse"}
    assert empty["asr"] == {
        "total": 0,
        "success": 0,
        "failure": 0,
        "rejected": 0,
        "disconnected": 0,
        "failure_rate": 0,
        "avg_duration_ms": 0,
    }

    record_runtime_metric("parse", "success", 100)
    record_runtime_metric("parse", "failure", 300)

    assert runtime_metrics_snapshot()["parse"] == {
        "total": 2,
        "success": 1,
        "failure": 1,
        "rejected": 0,
        "disconnected": 0,
        "failure_rate": 0.5,
        "avg_duration_ms": 200,
    }


@pytest.fixture()
def parse_db():
    engine = create_engine("sqlite:///:memory:", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    db.add_all([
        User(id=1, role="teacher", name="教师", email="teacher@example.com",
             password_hash="x", status="active"),
        Course(id=10, teacher_id=1, name="课程", code="C101", audit_status="approved"),
    ])
    db.commit()
    yield db
    db.close()
    engine.dispose()


def _parse_job(db, path):
    material = CourseMaterial(
        course_id=10, type="courseware", title=path.name,
        file_path=str(path), chunk_count=0,
    )
    db.add(material)
    db.commit()
    db.refresh(material)
    return material_parse_jobs.enqueue(db, material)


def test_parse_job_records_each_terminal_once(parse_db, tmp_path, monkeypatch):
    good = tmp_path / "good.txt"
    good.write_text("good", encoding="utf-8")
    bad = tmp_path / "bad.txt"
    bad.write_text("bad", encoding="utf-8")
    missing = tmp_path / "missing.txt"

    monkeypatch.setattr(material_parse_jobs, "moderation_enabled", lambda db: True)
    monkeypatch.setattr(material_parse_jobs, "record_rejection", lambda *args: None)
    monkeypatch.setattr(
        material_parse_jobs,
        "screen_with_config",
        lambda db, text: {
            "flagged": text == "bad",
            "categories": ["custom"] if text == "bad" else [],
            "hits": [],
        },
    )

    assert material_parse_jobs.run_parse_job(
        parse_db, _parse_job(parse_db, good).id,
    ).status == "done"
    assert material_parse_jobs.run_parse_job(
        parse_db, _parse_job(parse_db, bad).id,
    ).status == "rejected"
    assert material_parse_jobs.run_parse_job(
        parse_db, _parse_job(parse_db, missing).id,
    ).status == "failed"

    metric = runtime_metrics_snapshot()["parse"]
    assert metric["total"] == 3
    assert metric["success"] == 1
    assert metric["rejected"] == 1
    assert metric["failure"] == 1


def test_parse_job_records_unhandled_error_and_reraises(
    parse_db, tmp_path, monkeypatch,
):
    path = tmp_path / "good.txt"
    path.write_text("good", encoding="utf-8")
    job = _parse_job(parse_db, path)
    error = LookupError("moderation unavailable")
    monkeypatch.setattr(material_parse_jobs, "moderation_enabled", lambda db: True)

    def fail_moderation(db, text):
        raise error

    monkeypatch.setattr(material_parse_jobs, "screen_with_config", fail_moderation)

    with pytest.raises(LookupError) as exc_info:
        material_parse_jobs.run_parse_job(parse_db, job.id)

    assert exc_info.value is error
    metric = runtime_metrics_snapshot()["parse"]
    assert metric["total"] == 1
    assert metric["failure"] == 1


def test_index_records_only_real_builds_once(tmp_path, monkeypatch):
    rag_module = importlib.import_module("app.agent.tools.rag_search")
    error = RuntimeError("embedding unavailable")
    monkeypatch.setattr(rag_module.settings, "RAG_VECTOR_ENABLED", True)

    class FakeEmbedding:
        fail = False

        def encode(self, texts, normalize_embeddings):
            if self.fail:
                raise error
            return np.ones((len(texts), 2), dtype="float32")

    class FakeIndex:
        def __init__(self, dimensions):
            self.dimensions = dimensions

        def add(self, embeddings):
            self.embeddings = embeddings

    embedding = FakeEmbedding()
    manager = rag_module.RAGManager.__new__(rag_module.RAGManager)
    manager._embedding_model = embedding
    manager._indexes = {}
    manager._index_dir = str(tmp_path)
    monkeypatch.setitem(sys.modules, "faiss", SimpleNamespace(
        IndexFlatIP=FakeIndex,
        write_index=lambda index, path: None,
    ))
    documents = [{"content": "索引内容", "source": "讲义", "scope": "courseware"}]

    manager.build_index(10, [])
    manager.build_index(10, documents)
    embedding.fail = True
    # 向量构建失败不阻断:索引仍以词法模式可用,仅记录一次失败指标
    assert manager.build_index(11, documents) == 1

    metric = runtime_metrics_snapshot()["index"]
    assert metric["total"] == 2
    assert metric["success"] == 1
    assert metric["failure"] == 1


def _enable_openai_asr(monkeypatch):
    monkeypatch.setattr(settings, "ASR_PROVIDER", "openai")
    monkeypatch.setattr(settings, "ASR_MODEL", "whisper-1")
    monkeypatch.setattr(settings, "ASR_API_KEY", "key")


def test_asr_records_success_and_all_failure_types_once(monkeypatch):
    _enable_openai_asr(monkeypatch)
    upstream_error = RuntimeError("upstream unavailable")

    async def success(path, filename):
        return "识别结果"

    async def empty(path, filename):
        raise ValueError("未识别到语音内容")

    async def upstream(path, filename):
        raise upstream_error

    monkeypatch.setattr(asr, "_transcribe_openai", success)
    assert asyncio.run(asr.transcribe_audio(Path("a.wav"), "a.wav")) == "识别结果"

    monkeypatch.setattr(asr, "_transcribe_openai", empty)
    with pytest.raises(ValueError, match="未识别到语音内容"):
        asyncio.run(asr.transcribe_audio(Path("a.wav"), "a.wav"))

    monkeypatch.setattr(asr, "_transcribe_openai", upstream)
    with pytest.raises(RuntimeError) as exc_info:
        asyncio.run(asr.transcribe_audio(Path("a.wav"), "a.wav"))
    assert exc_info.value is upstream_error

    monkeypatch.setattr(settings, "ASR_API_KEY", "")
    with pytest.raises(RuntimeError, match="语音识别未配置"):
        asyncio.run(asr.transcribe_audio(Path("a.wav"), "a.wav"))

    metric = runtime_metrics_snapshot()["asr"]
    assert metric["total"] == 4
    assert metric["success"] == 1
    assert metric["failure"] == 3


def test_asr_wait_for_timeout_is_recorded_and_not_swallowed(monkeypatch):
    _enable_openai_asr(monkeypatch)

    async def slow(path, filename):
        await asyncio.sleep(60)
        return "不应返回"

    monkeypatch.setattr(asr, "_transcribe_openai", slow)

    with pytest.raises(asyncio.TimeoutError):
        asyncio.run(asyncio.wait_for(
            asr.transcribe_audio(Path("a.wav"), "a.wav"), timeout=0.01,
        ))

    metric = runtime_metrics_snapshot()["asr"]
    assert metric["total"] == 1
    assert metric["failure"] == 1


class _DoneGraph:
    async def astream(self, state, stream_mode, config=None):
        await state["stream_queue"].put(("token", "完整回答"))
        yield {"tutor": {"final_output": "完整回答"}}


class _WaitingGraph:
    async def astream(self, state, stream_mode, config=None):
        await state["stream_queue"].put(("token", "部分回答"))
        await asyncio.sleep(60)
        yield {"tutor": {"final_output": "部分回答"}}


class _DisconnectedRequest:
    async def is_disconnected(self):
        return True


@pytest.fixture()
def chat_user(monkeypatch):
    user = User(
        id=1, role="student", name="学生", email="student@example.com",
        password_hash="x", status="active",
    )
    monkeypatch.setattr(chat_api, "_answers", {})
    monkeypatch.setattr(chat_api, "_sessions", {})
    monkeypatch.setattr(chat_api, "_session_owner", {})
    monkeypatch.setattr(chat_api, "_persist_turn_sync", lambda *args: None)

    async def fake_log(*args, **kwargs):
        return None

    monkeypatch.setattr(chat_api, "_log_interaction", fake_log)
    return user


def _collect_graph(user, request=None, request_id=None):
    state = {
        "session_id": "s-metrics", "branch": "tutor", "course_id": None,
        "messages": [{"role": "user", "content": "问题"}],
    }

    async def collect():
        return [
            event async for event in chat_api._stream_graph(
                state, object(), user, request=request, request_id=request_id,
            )
        ]

    return asyncio.run(collect())


def test_sse_done_and_blocked_are_success(chat_user, monkeypatch):
    monkeypatch.setattr(chat_api, "get_graph", lambda: _DoneGraph())
    events = _collect_graph(chat_user)
    assert json.loads(events[-1][6:])["type"] == "done"

    monkeypatch.setattr(chat_api, "detect_level", lambda text: ("manual", ["敏感"]))
    monkeypatch.setattr(chat_api, "can_view", lambda user, level: False)
    events = _collect_graph(chat_user)
    assert json.loads(events[-1][6:])["data"]["blocked"] is True

    metric = runtime_metrics_snapshot()["sse"]
    assert metric["total"] == 2
    assert metric["success"] == 2
    assert metric["failure"] == 0


def test_sse_service_error_is_failure(chat_user, monkeypatch):
    error = RuntimeError("graph unavailable")

    class ErrorGraph:
        async def astream(self, state, stream_mode, config=None):
            await state["stream_queue"].put(("token", "草稿"))
            raise error
            yield  # pragma: no cover

    monkeypatch.setattr(chat_api, "get_graph", lambda: ErrorGraph())
    events = _collect_graph(chat_user)

    assert any(json.loads(event[6:])["type"] == "error" for event in events)
    metric = runtime_metrics_snapshot()["sse"]
    assert metric["total"] == 1
    assert metric["failure"] == 1


def test_sse_timeout_is_failure(chat_user, monkeypatch):
    monkeypatch.setattr(chat_api, "get_graph", lambda: _WaitingGraph())
    monkeypatch.setattr(chat_api, "MAX_STREAM_SECONDS", -1)
    events = _collect_graph(chat_user)

    assert any(json.loads(event[6:])["type"] == "error" for event in events)
    metric = runtime_metrics_snapshot()["sse"]
    assert metric["total"] == 1
    assert metric["failure"] == 1


def test_sse_disconnect_waits_for_background_terminal_only_with_request_id(
    chat_user, monkeypatch,
):
    monkeypatch.setattr(chat_api, "get_graph", lambda: _DoneGraph())

    assert _collect_graph(chat_user, request=_DisconnectedRequest()) == []
    metric = runtime_metrics_snapshot()["sse"]
    assert metric["total"] == 1
    assert metric["disconnected"] == 1

    assert _collect_graph(
        chat_user, request=_DisconnectedRequest(), request_id="req-background",
    ) == []
    assert chat_api._answers["req-background"]["status"] == "done"
    metric = runtime_metrics_snapshot()["sse"]
    assert metric["total"] == 2
    assert metric["success"] == 1
    assert metric["disconnected"] == 1


def test_sse_cache_replay_does_not_count_twice(chat_user, monkeypatch):
    monkeypatch.setattr(chat_api, "get_graph", lambda: _DoneGraph())
    _collect_graph(chat_user, request_id="req-cache")
    before = runtime_metrics_snapshot()["sse"]
    assert before["total"] == 1

    async def unexpected_stream(*args, **kwargs):
        raise AssertionError("缓存回放不应重新跑图")
        yield  # pragma: no cover

    monkeypatch.setattr(chat_api, "stream_agent_response", unexpected_stream)

    async def replay():
        response = await chat_api.chat_stream(
            ChatRequest(message="重复提问", request_id="req-cache"),
            object(), chat_user, object(),
        )
        return [frame async for frame in response.body_iterator]

    events = asyncio.run(replay())
    assert json.loads(events[-1][6:])["type"] == "done"
    assert runtime_metrics_snapshot()["sse"] == before


def test_admin_metrics_requires_admin_and_returns_snapshot():
    record_runtime_metric("asr", "success", 25)
    snapshot = runtime_metrics_snapshot()
    endpoint = getattr(admin_api, "get_runtime_metrics", None)

    assert callable(endpoint)
    assert inspect.signature(endpoint).parameters["admin"].default.dependency is require_admin
    assert any(
        route.path == "/admin/metrics"
        and "GET" in route.methods
        and route.endpoint is endpoint
        for route in admin_api.router.routes
    )
    assert endpoint(admin=SimpleNamespace(role="admin")) == {"operations": snapshot}
