"""P0-5 管理端只读工具与 admin 节点工具循环"""
import asyncio
import importlib

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.agent.llm import ToolPlan
from app.agent.nodes import admin as admin_module
from app.agent.nodes import tool_executor
from app.agent.tools import TOOL_REGISTRY
from app.db.session import Base
from app.models.course import Course, CourseMaterial, KnowledgePoint
from app.models.log import SystemConfig
from app.models.user import User


def _state(**overrides):
    state = {
        "messages": [{"role": "user", "content": "找出 3 门待审核且素材最少的课程"}],
        "session_id": "admin-tools-test",
        "user_id": 99,
        "user_role": "admin",
        "user_name": "管理员",
        "admin_level": "super",
        "course_id": None,
        "reflection_notes": "",
        "stream_queue": None,
    }
    state.update(overrides)
    return state


def _seed(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    tools_module = importlib.import_module("app.agent.tools.admin_tools")
    monkeypatch.setattr(tools_module, "SessionLocal", TestingSession)

    db = TestingSession()
    try:
        db.add_all([
            User(id=1, role="teacher", name="张老师", email="t1@x.com",
                 password_hash="x", status="active"),
            User(id=2, role="student", name="李同学", email="s1@x.com",
                 password_hash="x", status="active"),
            Course(id=10, teacher_id=1, name="数据结构", code="CS101",
                   audit_status="pending"),
            Course(id=11, teacher_id=1, name="操作系统", code="CS102",
                   audit_status="pending"),
            Course(id=12, teacher_id=1, name="编译原理", code="CS103",
                   audit_status="approved"),
        ])
        db.commit()
        db.add_all([
            CourseMaterial(course_id=10, type="pdf", title="讲义", file_path="/a.pdf"),
            CourseMaterial(course_id=11, type="pdf", title="讲义", file_path="/b.pdf"),
            CourseMaterial(course_id=11, type="pdf", title="实验", file_path="/c.pdf"),
            KnowledgePoint(course_id=10, name="二叉树"),
            SystemConfig(config_key="site_notice", config_value="欢迎"),
            SystemConfig(config_key="llm_api_token", config_value="sk-real-secret"),
        ])
        db.commit()
    finally:
        db.close()
    return engine, tools_module


def test_course_list_filters_and_counts(monkeypatch):
    engine, tools_module = _seed(monkeypatch)
    try:
        result = tools_module.admin_course_list(audit_status="pending")
        assert result["total"] == 2
        by_id = {item["course_id"]: item for item in result["items"]}
        assert by_id[10]["materials"] == 1
        assert by_id[11]["materials"] == 2
        assert by_id[10]["knowledge_points"] == 1
        assert by_id[10]["teacher_name"] == "张老师"
    finally:
        engine.dispose()


def test_material_stats_sorted_by_materials(monkeypatch):
    engine, tools_module = _seed(monkeypatch)
    try:
        result = tools_module.admin_material_stats(course_ids=[10, 11])
        assert [item["course_id"] for item in result["items"]] == [10, 11]
        assert result["items"][0]["materials"] == 1
    finally:
        engine.dispose()


def test_user_lookup_hides_private_fields(monkeypatch):
    engine, tools_module = _seed(monkeypatch)
    try:
        result = tools_module.admin_user_lookup(role="teacher")
        assert result["total"] == 1
        item = result["items"][0]
        assert item["name"] == "张老师"
        assert "email" not in item
        assert "password_hash" not in item
    finally:
        engine.dispose()


def test_config_get_masks_sensitive_values(monkeypatch):
    engine, tools_module = _seed(monkeypatch)
    try:
        result = tools_module.admin_config_get()
        by_key = {item["key"]: item for item in result["items"]}
        assert by_key["site_notice"]["value"] == "欢迎"
        assert by_key["llm_api_token"]["value"] == "***"
        assert by_key["llm_api_token"]["sensitive"] is True
    finally:
        engine.dispose()


def test_admin_tools_denied_for_non_admin():
    result = tool_executor._execute_single(
        {"name": "admin.course_list", "arguments": {}},
        {"user_role": "teacher", "user_id": 1, "course_id": 7},
    )
    assert "无权" in result["error"]


def test_admin_node_composes_two_tools(monkeypatch):
    """验收:待审核 + 素材最少需要 course_list 与 material_stats 两次调用"""
    calls = []

    monkeypatch.setitem(
        TOOL_REGISTRY, "admin.course_list",
        lambda **kw: calls.append(("course_list", kw)) or {
            "total": 2,
            "items": [
                {"course_id": 10, "name": "数据结构", "audit_status": "pending"},
                {"course_id": 11, "name": "操作系统", "audit_status": "pending"},
            ],
        },
    )
    monkeypatch.setitem(
        TOOL_REGISTRY, "admin.material_stats",
        lambda **kw: calls.append(("material_stats", kw)) or {
            "total": 2,
            "items": [
                {"course_id": 10, "name": "数据结构", "materials": 1},
                {"course_id": 11, "name": "操作系统", "materials": 2},
            ],
        },
    )

    rounds = {"n": 0}

    async def fake_llm(messages, sink=None, tools=None):
        # 动作识别调用不带 tools,返回非 JSON 表示本轮不是写任务
        if tools is None:
            return "none"
        rounds["n"] += 1
        if rounds["n"] == 1:
            return ToolPlan(tool_calls=[{
                "id": "c1", "name": "admin.course_list",
                "arguments": {"audit_status": "pending"},
            }])
        if rounds["n"] == 2:
            return ToolPlan(tool_calls=[{
                "id": "c2", "name": "admin.material_stats",
                "arguments": {"course_ids": [10, 11]},
            }])
        assert any(message.get("role") == "tool" for message in messages)
        return "待审核且素材最少:课程 10 数据结构(1 份素材)"

    monkeypatch.setattr(admin_module, "llm_invoke", fake_llm)
    result = asyncio.run(admin_module.admin_node(_state()))

    assert [name for name, _ in calls] == ["course_list", "material_stats"]
    assert [item["name"] for item in result["tool_trace"]] == [
        "admin.course_list", "admin.material_stats",
    ]
    assert "课程 10" in result["final_output"]
    assert "数据结构" in result["final_output"]
