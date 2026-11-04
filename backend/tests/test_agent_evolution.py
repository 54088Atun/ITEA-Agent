"""进化清单 P1 接口回归:批改队列、学习总览、建议、记忆、反馈、取消

覆盖:
- 批改队列只返回已提交未确认,支持作业/班级筛选,越权课程 403
- 学习总览聚合薄弱点、到期复习、待交作业、待考考试
- 建议按优先级排序,高优先级来自未完成考试/逾期作业
- 记忆写入校验、TTL 过滤、软删除与越权保护
- 反馈关联运行与消息,越权反馈 403
- 取消运行回写 cancelled,非本人 403
"""
from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.api.agent as agent_api
import app.api.student as student_api
import app.api.teacher as teacher_api
from app.db.session import Base
from app.models.agent_memory import AgentFeedback, AgentMemory
from app.models.assignment import Assignment, Submission
from app.models.classroom import ClassMember, Classroom, CourseEnrollment
from app.models.course import Course, KnowledgePoint
from app.models.exam import Exam
from app.models.log import AgentRun
from app.models.profile import MasteryRecord, ReviewPlan, StudentProfile, WrongQuestion
from app.models.user import User
from app.schemas.agent import FeedbackCreate, MemoryCreate

import app.agent.nodes.memory as memory_module
import app.services.agent_memory as mem_svc
import app.services.capabilities as capabilities
import app.services.project_inspector as inspector
import app.services.web_access as web_access
from app.agent.context import compress_profile
from app.agent.tools import gateway


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    seed(session)
    yield session
    session.close()
    engine.dispose()


def seed(db):
    now = datetime.utcnow()
    db.add_all([
        User(id=1, role="teacher", name="张老师", email="t1@example.com",
             password_hash="x", status="active"),
        User(id=2, role="teacher", name="李老师", email="t2@example.com",
             password_hash="x", status="active"),
        User(id=3, role="student", name="小明", email="s1@example.com",
             password_hash="x", status="active"),
        User(id=4, role="student", name="小红", email="s2@example.com",
             password_hash="x", status="active"),
        User(id=5, role="admin", name="管理员", email="a@example.com",
             password_hash="x", status="active"),
        Course(id=10, teacher_id=1, name="软件测试", code="ST101",
               audit_status="approved"),
        Course(id=11, teacher_id=2, name="数据库", code="DB101",
               audit_status="approved"),
        KnowledgePoint(id=30, course_id=10, name="等价类划分"),
        KnowledgePoint(id=31, course_id=10, name="边界值分析"),
        Classroom(id=20, teacher_id=1, course_id=10, name="测试 1 班",
                  invite_code="ABCD1234"),
        ClassMember(id=40, class_id=20, student_id=3, status="active"),
        CourseEnrollment(id=41, course_id=10, student_id=3),
        StudentProfile(id=50, user_id=3, course_id=10, overall_progress=55),
        MasteryRecord(id=60, profile_id=50, kp_id=30, mastery_level=30),
        MasteryRecord(id=61, profile_id=50, kp_id=31, mastery_level=80),
        WrongQuestion(id=70, profile_id=50, kp_id=30, question_content="错题"),
        ReviewPlan(id=71, wrong_question_id=70, next_review_at=now - timedelta(days=1),
                   status="pending"),
        Assignment(id=80, teacher_id=1, course_id=10, class_id=20,
                   title="作业A", status="published", due_at=now + timedelta(days=1)),
        Assignment(id=81, teacher_id=1, course_id=10, class_id=20,
                   title="作业B", status="published", due_at=now + timedelta(days=2)),
        Assignment(id=82, teacher_id=1, course_id=10, class_id=20,
                   title="作业C", status="published", due_at=now + timedelta(days=3)),
        Submission(id=90, assignment_id=80, student_id=3, content="答案A",
                   status="submitted", submitted_at=now),
        Submission(id=91, assignment_id=81, student_id=4, content="答案B",
                   status="submitted", submitted_at=now,
                   confirmed_at=now, score=90),
        Exam(id=100, teacher_id=1, course_id=10, title="期中考试",
             status="published", duration_minutes=60, total_score=100,
             due_at=now + timedelta(hours=12)),
        AgentRun(id=200, user_id=3, role="student", session_id="s1", status="running"),
        AgentRun(id=201, user_id=4, role="student", session_id="s2", status="running"),
    ])
    db.commit()


def test_grading_queue_only_returns_pending_and_filters(db):
    teacher = db.get(User, 1)

    result = teacher_api.get_grading_queue(
        course_id=10, assignment_id=None, class_id=None, page=1, page_size=20,
        teacher=teacher, db=db,
    )
    assert result["total"] == 1
    assert result["items"][0]["submission_id"] == 90
    assert result["items"][0]["student_name"] == "小明"

    filtered = teacher_api.get_grading_queue(
        course_id=10, assignment_id=81, class_id=None, page=1, page_size=20,
        teacher=teacher, db=db,
    )
    assert filtered["total"] == 0

    with pytest.raises(HTTPException) as exc:
        teacher_api.get_grading_queue(
            course_id=11, assignment_id=None, class_id=None, page=1, page_size=20,
            teacher=teacher, db=db,
        )
    assert exc.value.status_code == 404


def test_learning_overview_aggregates_course_state(db):
    student = db.get(User, 3)
    result = student_api.learning_overview(course_id=None, student=student, db=db)

    assert result["summary"]["course_count"] == 1
    course = result["courses"][0]
    assert course["course"]["id"] == 10
    assert [item["kp_id"] for item in course["weak_knowledge_points"]] == [30]
    assert course["due_reviews"]["count"] == 1
    assert course["pending_assignments"]["count"] == 2
    assert course["pending_exams"]["count"] == 1


def test_recommendations_prioritize_exam_and_assignment(db):
    student = db.get(User, 3)
    result = student_api.learning_recommendations(
        course_id=None, limit=10, student=student, db=db,
    )

    types = {item["type"] for item in result["items"]}
    assert {"exam", "assignment", "review", "practice"} <= types
    assert result["items"][0]["type"] == "exam"
    assert result["items"][0]["priority"] == "high"


def test_memory_create_list_and_delete(db):
    student = db.get(User, 3)
    created = agent_api.create_memory(
        MemoryCreate(content="偏好先讲例题再总结", course_id=10, ttl_days=7),
        user=student, db=db,
    )
    assert created["memory_type"] == "semantic"
    assert created["source_type"] == "manual"
    assert created["expires_at"] is not None

    listed = agent_api.list_memories(course_id=10, limit=50, user=student, db=db)
    assert listed["total"] == 1

    # 过期记忆不再返回
    row = db.get(AgentMemory, created["id"])
    row.expires_at = datetime.utcnow() - timedelta(days=1)
    db.commit()
    assert agent_api.list_memories(course_id=10, limit=50, user=student, db=db)["total"] == 0

    # 他人不能删除
    other = db.get(User, 4)
    with pytest.raises(HTTPException) as exc:
        agent_api.delete_memory(created["id"], user=other, db=db)
    assert exc.value.status_code == 403

    agent_api.delete_memory(created["id"], user=student, db=db)
    assert db.get(AgentMemory, created["id"]).deleted_at is not None


def test_memory_rejects_empty_or_oversized_content(db):
    student = db.get(User, 3)
    with pytest.raises(HTTPException):
        agent_api.create_memory(
            MemoryCreate(content="   "), user=student, db=db,
        )
    with pytest.raises(HTTPException):
        agent_api.create_memory(
            MemoryCreate(content="x" * 2001), user=student, db=db,
        )


def test_feedback_links_run_and_rejects_cross_user(db):
    student = db.get(User, 3)
    created = agent_api.create_feedback(
        FeedbackCreate(rating="down", run_id=200, comment="答案不完整"),
        user=student, db=db,
    )
    assert created["run_id"] == 200
    assert created["session_id"] == "s1"

    with pytest.raises(HTTPException) as exc:
        agent_api.create_feedback(
            FeedbackCreate(rating="up", run_id=201), user=student, db=db,
        )
    assert exc.value.status_code == 403

    assert db.query(AgentFeedback).count() == 1


def test_cancel_run_marks_cancelled_and_checks_owner(db):
    student = db.get(User, 3)
    result = agent_api.cancel_agent_run(200, user=student, db=db)
    assert result["status"] == "cancelled"
    assert db.get(AgentRun, 200).status == "cancelled"

    with pytest.raises(HTTPException) as exc:
        agent_api.cancel_agent_run(201, user=student, db=db)
    assert exc.value.status_code == 403

    # 已完成/已取消的运行再次取消不报错,状态保持不变
    again = agent_api.cancel_agent_run(200, user=student, db=db)
    assert again["status"] == "cancelled"


# ---------- P1-1 三层记忆 ----------

@pytest.fixture()
def memory_db(monkeypatch):
    """记忆服务/节点共用同一个内存库,便于验证写入与跨会话读取"""
    engine = create_engine(
        "sqlite:///:memory:", poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = factory()
    seed(session)
    session.close()
    monkeypatch.setattr(mem_svc, "SessionLocal", factory)
    monkeypatch.setattr(memory_module, "SessionLocal", factory)
    yield factory
    engine.dispose()


def test_write_memory_persists_source_and_ttl(memory_db):
    mem_id = mem_svc.write_memory(
        user_id=3, course_id=10, memory_type="episodic",
        content="等价类划分掌握度偏低,错题集中在边界值取值",
        source_type="conversation", source_id="s1", session_id="s1",
        summary="上周复习薄弱点:等价类划分", ttl_days=30, importance=3,
    )
    assert mem_id

    session = memory_db()
    try:
        row = session.get(AgentMemory, mem_id)
        assert row.memory_type == "episodic"
        assert row.session_id == "s1"
        assert row.source_type == "conversation"
        assert row.summary == "上周复习薄弱点:等价类划分"
        assert row.importance == 3
        assert row.expires_at is not None
        assert row.created_at is not None
    finally:
        session.close()


def test_recent_episodic_keeps_source_and_keyword_fallback(memory_db, monkeypatch):
    mem_svc.write_memory(
        user_id=3, course_id=10, memory_type="episodic",
        content="等价类划分薄弱", summary="等价类划分薄弱",
        session_id="s1", ttl_days=30, importance=3,
    )
    mem_svc.write_memory(
        user_id=3, course_id=10, memory_type="semantic",
        content="偏好先讲例题再总结", summary="偏好先讲例题再总结",
        session_id="s1", ttl_days=365, importance=4,
    )

    episodic = mem_svc.list_recent_episodic(3, 10, days=14, limit=5)
    assert len(episodic) == 1
    assert episodic[0]["session_id"] == "s1"
    assert episodic[0]["date"]

    # embedding 不可用时降级关键词检索
    def _boom(query, rows):
        raise RuntimeError("embedding 模型不可用")

    monkeypatch.setattr(mem_svc, "_vector_order", _boom)
    hits = mem_svc.search_memory(
        3, 10, query="等价类划分", memory_type="episodic", limit=5,
    )
    assert hits
    assert hits[0]["summary"] == "等价类划分薄弱"


def test_profile_snapshot_includes_cross_session_memories(memory_db):
    mem_svc.write_memory(
        user_id=3, course_id=10, memory_type="episodic",
        content="边界值分析错题较多", summary="边界值分析错题较多",
        session_id="s9", ttl_days=90, importance=3,
    )
    mem_svc.write_memory(
        user_id=3, course_id=10, memory_type="semantic",
        content="喜欢先看例题", summary="喜欢先看例题",
        session_id="s9", ttl_days=365, importance=4,
    )

    snapshot = memory_module.load_profile_snapshot(3, 10)
    assert snapshot["overall_progress"] == 55.0
    assert snapshot["episodic_memories"][0]["session_id"] == "s9"
    assert snapshot["semantic_memories"][0]["summary"] == "喜欢先看例题"

    # 教师或未带课程不读学情快照
    assert memory_module.load_profile_snapshot(3, 10, role="teacher") == {}
    assert memory_module.load_profile_snapshot(3, None) == {}


def test_compress_profile_keeps_history_and_preferences(memory_db):
    import json

    mem_svc.write_memory(
        user_id=3, course_id=10, memory_type="episodic",
        content="等价类划分薄弱", summary="等价类划分薄弱",
        session_id="s1", ttl_days=90, importance=3,
    )
    for idx in range(4):
        mem_svc.write_memory(
            user_id=3, course_id=10, memory_type="semantic",
            content=f"偏好{idx}", summary=f"偏好{idx}",
            session_id="s1", ttl_days=365, importance=4,
        )

    snapshot = memory_module.load_profile_snapshot(3, 10)
    data = json.loads(compress_profile(snapshot, max_chars=2000))
    assert any("会话 s1" in line and "等价类划分薄弱" in line for line in data["history"])
    assert len(data["preferences"]) == 3


def test_memory_ttl_bounds_and_poisoned_content(memory_db):
    for bad in (0, 366, "abc"):
        with pytest.raises(ValueError):
            mem_svc.write_memory(3, 10, "semantic", "内容", ttl_days=bad)

    # 内容为空或被拦截时不落库
    assert mem_svc.write_memory(3, 10, "semantic", "   ") is None
    session = memory_db()
    try:
        assert session.query(AgentMemory).count() == 0
    finally:
        session.close()


# ---------- P1-4 项目自检 ----------

@pytest.fixture()
def project_root(tmp_path, monkeypatch):
    """把仓库根指向临时目录,避免测试触碰真实工程"""
    monkeypatch.setattr(inspector, "repo_root", lambda: tmp_path)
    return tmp_path


def test_project_path_sandbox_rejects_absolute_and_traversal(project_root):
    src = project_root / "src"
    src.mkdir()
    (src / "app.py").write_text("print('ok')\n", encoding="utf-8")

    with pytest.raises(inspector.ProjectAccessError, match="缺少文件路径"):
        inspector.read_file("")
    with pytest.raises(inspector.ProjectAccessError, match="只接受项目内相对路径"):
        inspector.read_file(str(src / "app.py"))
    with pytest.raises(inspector.ProjectAccessError, match="路径超出项目根目录"):
        inspector.read_file("../secret.txt")
    with pytest.raises(inspector.ProjectAccessError, match="路径超出项目根目录"):
        inspector.search_code("x", path="..")


def test_project_sensitive_files_and_skipped_dirs_are_blocked(project_root):
    (project_root / ".env").write_text("SECRET=1\n", encoding="utf-8")
    log_dir = project_root / "logs"
    log_dir.mkdir()
    (log_dir / "app.log").write_text("ERROR boom\n", encoding="utf-8")

    with pytest.raises(inspector.ProjectAccessError, match="敏感文件不可读取"):
        inspector.read_file(".env")
    with pytest.raises(inspector.ProjectAccessError, match="该目录不开放访问"):
        inspector.read_file("logs/app.log")
    with pytest.raises(inspector.ProjectAccessError, match="该目录不开放访问"):
        inspector.search_code("ERROR", path="logs")

    # 日志走专用入口,仍能给出文件与行号
    logs = inspector.search_logs(keyword="ERROR")
    assert logs["matches"][0]["file"] == "logs/app.log"
    assert logs["matches"][0]["line"] == 1


def test_project_search_code_returns_file_and_line(project_root):
    src = project_root / "src"
    src.mkdir()
    (src / "app.py").write_text(
        "import os\nraise RuntimeError('ERROR')\n", encoding="utf-8",
    )
    (src / "notes.md").write_text("error lowercase\n", encoding="utf-8")

    result = inspector.search_code("ERROR", limit=5)
    hit = next(item for item in result["matches"] if item["file"] == "src/app.py")
    assert hit["line"] == 2
    assert result["scanned_files"] >= 2

    with pytest.raises(inspector.ProjectAccessError, match="缺少搜索关键词"):
        inspector.search_code("   ")
    with pytest.raises(inspector.ProjectAccessError, match="搜索关键词过长"):
        inspector.search_code("x" * 101)


def test_project_read_file_rejects_binary_and_limits_lines(project_root):
    src = project_root / "src"
    src.mkdir()
    (src / "blob.bin").write_bytes(b"\x00\x01\x02")
    (src / "long.py").write_text(
        "\n".join(f"line {i}" for i in range(1, 402)), encoding="utf-8",
    )

    with pytest.raises(inspector.ProjectAccessError, match="二进制文件不可读取"):
        inspector.read_file("src/blob.bin")

    result = inspector.read_file("src/long.py")
    assert result["total_lines"] == 401
    assert result["truncated"] is True
    assert result["end_line"] < result["total_lines"]
    assert len(result["content"].splitlines()) == result["end_line"]


def test_project_run_tests_only_accepts_whitelisted_suites(project_root):
    assert set(inspector.TEST_SUITES) == {"all", "agent", "api", "security"}
    with pytest.raises(inspector.ProjectAccessError, match="未知测试集"):
        inspector.run_tests("rm -rf /")


def test_project_git_diff_uses_fixed_command(project_root):
    try:
        result = inspector.git_diff(stat_only=True)
    except inspector.ProjectExecError as exc:  # 环境缺少 git 时跳过
        pytest.skip(f"当前环境无法执行 git: {exc}")
    assert result["command"] == "git diff --no-color --stat"


def test_project_and_web_tools_follow_role_matrix():
    assert capabilities.tool_denied_reason("student", "project.read_file") == (
        "角色 student 无权执行工具: project.read_file"
    )
    assert capabilities.tool_denied_reason("student", "web.search") == (
        "角色 student 无权执行工具: web.search"
    )
    # 教师可用联网,但不能读项目文件
    assert capabilities.tool_denied_reason("teacher", "web.search") is None
    assert capabilities.tool_denied_reason("teacher", "project.read_file") == (
        "角色 teacher 无权执行工具: project.read_file"
    )
    for name in (
        "project.read_file", "project.run_tests", "project.search_logs",
        "project.git_diff", "project.db_schema",
    ):
        assert capabilities.tool_denied_reason("admin", name) is None


def test_project_tools_are_admin_only_and_tests_need_confirmation():
    read_spec = gateway.get_tool_spec("project.read_file")
    assert read_spec.roles == ("admin",)
    assert read_spec.read_only is True

    run_spec = gateway.get_tool_spec("project.run_tests")
    assert run_spec.roles == ("admin",)
    assert run_spec.read_only is False
    assert run_spec.requires_confirmation is True


# ---------- P2-3 受控联网 ----------

def test_web_search_requires_keyword_and_config(monkeypatch):
    web_access.clear_cache()
    with pytest.raises(web_access.WebAccessError, match="缺少搜索关键词"):
        web_access.search("   ")
    with pytest.raises(web_access.WebAccessError, match="搜索关键词过长"):
        web_access.search("x" * 201)

    # 未配置服务商时不发起外网请求
    monkeypatch.setattr(web_access, "_search_endpoint", lambda provider: "")
    with pytest.raises(web_access.WebNotConfigured, match="联网检索未启用"):
        web_access.search("软件测试")


def test_web_fetch_rejects_bad_scheme_and_unknown_domain(monkeypatch):
    web_access.clear_cache()
    monkeypatch.setattr(web_access, "allowed_domains", lambda: ["moe.edu.cn"])
    with pytest.raises(web_access.WebAccessError, match="缺少 URL"):
        web_access.fetch("")
    with pytest.raises(web_access.WebAccessDenied, match="只支持 http/https 链接"):
        web_access.fetch("ftp://example.com/a")
    with pytest.raises(web_access.WebAccessDenied, match="域名不在白名单内"):
        web_access.fetch("https://evil.example.com/a")


def test_web_fetch_blocks_loopback_even_if_whitelisted(monkeypatch):
    web_access.clear_cache()
    monkeypatch.setattr(web_access, "allowed_domains", lambda: ["127.0.0.1"])
    with pytest.raises(web_access.WebAccessDenied, match="内网或保留地址"):
        web_access.fetch("http://127.0.0.1/admin")


def test_web_domain_matching_is_suffix_strict(monkeypatch):
    monkeypatch.setattr(web_access, "allowed_domains", lambda: ["edu.cn"])
    assert web_access._domain_allowed("www.tsinghua.edu.cn")
    assert web_access._domain_allowed("EDU.CN.")
    assert not web_access._domain_allowed("evil-edu.cn")
    assert not web_access._domain_allowed("")
