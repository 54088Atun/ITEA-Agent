"""P1-3 只读 SQL 分析:安全校验、课程收口、聚合结果与教师端接入"""
import asyncio
import importlib
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.agent.nodes import teacher as teacher_module
from app.db.session import Base
from app.models.assignment import Assignment, Submission
from app.models.classroom import ClassMember, Classroom
from app.models.course import Course
from app.models.exam import Exam, ExamRecord
from app.models.interview import InterviewRecord
from app.models.profile import MasteryRecord, ReviewPlan, StudentProfile, WrongQuestion
from app.models.user import User
from app.services.sql_analytics import (
    SqlSafetyError, render_table, run_query, validate_sql,
)

NOW = datetime.utcnow()


def _db():
    engine = create_engine("sqlite:///:memory:", poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[
        User.__table__, Course.__table__, Classroom.__table__,
        ClassMember.__table__, Assignment.__table__, Submission.__table__,
        StudentProfile.__table__, MasteryRecord.__table__,
        WrongQuestion.__table__, ReviewPlan.__table__,
        Exam.__table__, ExamRecord.__table__, InterviewRecord.__table__,
    ])
    db = sessionmaker(bind=engine)()
    db.add_all([
        User(id=1, role="teacher", name="教师", email="t@example.com", password_hash="x"),
        User(id=2, role="student", name="学生", email="s@example.com", password_hash="x"),
        Course(id=10, teacher_id=1, name="软件测试", code="ST101", audit_status="approved"),
        Course(id=11, teacher_id=1, name="数据库", code="DB101", audit_status="approved"),
        Classroom(id=20, teacher_id=1, course_id=10, name="测试1班", invite_code="SQL20"),
        Classroom(id=21, teacher_id=1, course_id=11, name="数据库1班", invite_code="SQL21"),
        ClassMember(id=40, class_id=20, student_id=2, status="active"),
        ClassMember(id=41, class_id=21, student_id=2, status="active"),
        Assignment(id=80, teacher_id=1, course_id=10, class_id=20,
                   title="作业A", status="published", due_at=NOW + timedelta(days=3)),
        Assignment(id=81, teacher_id=1, course_id=11, class_id=21,
                   title="作业B", status="published", due_at=NOW + timedelta(days=3)),
        Submission(id=90, assignment_id=80, student_id=2, content="答案",
                   status="submitted", submitted_at=NOW - timedelta(days=1)),
        StudentProfile(id=50, user_id=2, course_id=10, overall_progress=60),
        MasteryRecord(id=60, profile_id=50, kp_id=1, mastery_level=30),
        WrongQuestion(id=70, profile_id=50, kp_id=1, question_content="错题", error_type="概念不清"),
        ReviewPlan(id=71, wrong_question_id=70, next_review_at=NOW, status="pending"),
        Exam(id=100, teacher_id=1, course_id=10, title="期中", status="published"),
        ExamRecord(id=110, exam_id=100, student_id=2, answers="{}",
                   total_score=88, submitted_at=NOW),
        InterviewRecord(id=120, profile_id=50, round=1, question="题", answer="答", score=80),
    ])
    db.commit()
    return engine, db


@pytest.mark.parametrize("sql", [
    "DELETE FROM v_assignments",
    "UPDATE v_assignments SET status='x'",
    "SELECT * FROM users",
    "SELECT * FROM v_assignments; DROP TABLE users",
    "SELECT * FROM v_assignments -- 注释",
    "SELECT * FROM (SELECT 1) t",
    "",
])
def test_validate_sql_rejects_unsafe_statements(sql):
    with pytest.raises(SqlSafetyError):
        validate_sql(sql)


def test_validate_sql_injects_and_caps_limit():
    assert validate_sql("SELECT * FROM v_assignments").endswith("LIMIT 200")
    assert validate_sql("SELECT * FROM v_assignments LIMIT 9999").endswith("LIMIT 200")
    assert validate_sql("SELECT * FROM v_assignments LIMIT 10").endswith("LIMIT 10")


def test_run_query_scopes_rows_to_course():
    engine, db = _db()
    try:
        result = run_query(
            db,
            "SELECT course_id, COUNT(*) AS total FROM v_assignments GROUP BY course_id",
            course_id=10,
        )
        assert result["rows"] == [{"course_id": 10, "total": 1}]
    finally:
        db.close()
        engine.dispose()


def test_run_query_returns_submission_rate_table():
    engine, db = _db()
    sql = (
        "SELECT v_classes.name AS class_name, "
        "COUNT(DISTINCT v_assignments.assignment_id) AS assignment_count, "
        "COUNT(DISTINCT v_submissions.submission_id) AS submitted_count "
        "FROM v_classes "
        "LEFT JOIN v_assignments ON v_assignments.class_id = v_classes.class_id "
        "LEFT JOIN v_submissions ON v_submissions.assignment_id = v_assignments.assignment_id "
        "GROUP BY v_classes.name"
    )
    try:
        result = run_query(db, sql, course_id=10)
        assert result["columns"] == ["class_name", "assignment_count", "submitted_count"]
        assert result["rows"][0]["class_name"] == "测试1班"
        assert result["rows"][0]["submitted_count"] == 1
        assert "| class_name |" in render_table(result)
    finally:
        db.close()
        engine.dispose()


def test_sql_query_tool_rejects_unauthorized_course(monkeypatch):
    module = importlib.import_module("app.agent.tools.sql_query")
    monkeypatch.setattr(module, "agent_course_scope_error", lambda *a, **k: "无权访问该课程")

    result = module.sql_query("SELECT * FROM v_assignments", course_id=10, user_id=2)

    assert result == {"error": "无权访问该课程"}


def test_sql_query_tool_executes_read_only_query(monkeypatch):
    engine, db = _db()
    module = importlib.import_module("app.agent.tools.sql_query")
    monkeypatch.setattr(module, "SessionLocal", lambda: db)
    monkeypatch.setattr(module, "agent_course_scope_error", lambda *a, **k: None)
    try:
        result = module.sql_query(
            "SELECT COUNT(*) AS total FROM v_assignments", course_id=10, user_id=2,
        )
        assert result["ok"] is True
        assert result["rows"] == [{"total": 1}]
        assert result["row_count"] == 1
    finally:
        engine.dispose()


def _teacher_state(message):
    return {
        "messages": [{"role": "user", "content": message}],
        "session_id": "sql-test",
        "user_id": 1,
        "user_role": "teacher",
        "admin_level": None,
        "user_name": "教师",
        "course_id": 10,
        "intent": "prepare",
        "branch": "teacher",
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


def test_teacher_node_injects_sql_result_table(monkeypatch):
    captured = {}
    called = {}

    async def fake_llm(messages, sink=None, temperature=None):
        system = messages[0]["content"]
        if "只读 SQL 分析器" in system:
            return "```sql\nSELECT class_name FROM v_classes\n```"
        captured["system"] = system
        return "分析完成"

    def fake_sql_query(**kwargs):
        called.update(kwargs)
        return {
            "ok": True,
            "columns": ["class_name", "submit_rate"],
            "rows": [{"class_name": "测试1班", "submit_rate": 0.5}],
            "row_count": 1,
        }

    monkeypatch.setattr(teacher_module, "llm_invoke", fake_llm)
    monkeypatch.setattr(teacher_module, "sql_query", fake_sql_query)
    monkeypatch.setattr(teacher_module, "fetch_course_evidence",
                        lambda *a, **k: {"context": "", "fragments": []})
    monkeypatch.setattr(teacher_module, "fetch_syllabus", lambda *a, **k: "")
    monkeypatch.setattr(teacher_module, "fetch_class_stats", lambda *a, **k: {})
    monkeypatch.setattr(
        teacher_module, "load_prompt",
        lambda name: (
            "只读 SQL 分析器 {views}" if name == "sql_query"
            else "system {rag_context}"
        ),
    )

    def fake_render(template, **kwargs):
        for key, value in kwargs.items():
            template = template.replace("{" + key + "}", str(value))
        return template

    monkeypatch.setattr(teacher_module, "render_prompt", fake_render)

    result = asyncio.run(teacher_module.teacher_node(
        _teacher_state("按班级统计近 4 周作业提交率"),
    ))

    assert called["course_id"] == 10
    assert called["sql"] == "SELECT class_name FROM v_classes"
    assert "SQL 查询结果" in captured["system"]
    assert "| class_name |" in captured["system"]
    assert "测试1班" in captured["system"]
    assert result["final_output"].startswith("分析完成")
    assert {"type": "data", "label": "SQL 分析结果"} in result["sources"]
