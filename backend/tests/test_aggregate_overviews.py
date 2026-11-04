"""实体级聚合接口:学生课程学情 / 用户概览 / 课程概览 / 风险事件上下文

覆盖:
- 教师只能看自己课程下、且属于该课程的学生
- 学生无学情档案时返回零值结构,不报错
- 管理端用户概览聚合课程、最近操作与风控命中
- 管理端课程概览聚合素材、知识点、学生数与审核历史
- 风险事件上下文返回前后交互与处置记录
"""
from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import admin as admin_api
from app.api import teacher as teacher_api
from app.db.session import Base
from app.models.classroom import ClassMember, Classroom, CourseEnrollment
from app.models.course import Course, CourseMaterial, KnowledgePoint
from app.models.interview import InterviewRecord
from app.models.log import (
    InteractionLog, OperationLog, RiskLog, WriteAuditLog,
)
from app.models.profile import (
    MasteryRecord, ReviewPlan, StudentProfile, WrongQuestion,
)
from app.models.user import User


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
    teacher = User(id=1, role="teacher", name="张老师", email="t1@example.com",
                   password_hash="x", status="active")
    other = User(id=2, role="teacher", name="李老师", email="t2@example.com",
                 password_hash="x", status="active")
    student = User(id=3, role="student", name="小明", email="s1@example.com",
                   password_hash="x", status="active")
    outsider = User(id=4, role="student", name="小红", email="s2@example.com",
                    password_hash="x", status="active")
    fresh = User(id=6, role="student", name="新同学", email="s3@example.com",
                 password_hash="x", status="active")
    admin = User(id=5, role="admin", admin_level="super", name="管理员",
                 email="a1@example.com", password_hash="x", status="active")
    course = Course(id=10, teacher_id=1, name="软件测试", code="ST101",
                    semester="2026春", audit_status="approved")
    classroom = Classroom(id=20, teacher_id=1, course_id=10, name="测试 1 班",
                          invite_code="ABCD1234")
    db.add_all([teacher, other, student, outsider, fresh, admin, course, classroom])
    db.add(ClassMember(class_id=20, student_id=3, status="active"))
    db.add(CourseEnrollment(course_id=10, student_id=3, source="class", class_id=20))
    # 已选课但没有学情档案,用于验证零值兜底
    db.add(CourseEnrollment(course_id=10, student_id=6, source="class", class_id=20))
    db.add_all([
        KnowledgePoint(id=100, course_id=10, name="等价类"),
        KnowledgePoint(id=101, course_id=10, name="边界值"),
        CourseMaterial(course_id=10, type="courseware", title="第 1 讲",
                       file_path="/tmp/a.pdf"),
        CourseMaterial(course_id=10, type="exercise", title="练习 1",
                       file_path="/tmp/b.pdf"),
    ])
    db.flush()

    profile = StudentProfile(user_id=3, course_id=10, overall_progress=45)
    db.add(profile)
    db.flush()
    db.add_all([
        MasteryRecord(profile_id=profile.id, kp_id=100, mastery_level=30),
        MasteryRecord(profile_id=profile.id, kp_id=101, mastery_level=75),
    ])
    wrong = WrongQuestion(
        profile_id=profile.id, kp_id=100, question_content="边界值取错了",
        error_type="概念", source_type="manual", source_id="w1",
    )
    db.add(wrong)
    db.flush()
    db.add(ReviewPlan(
        wrong_question_id=wrong.id,
        next_review_at=datetime.utcnow() - timedelta(days=1),
        status="pending", interval_days=1,
    ))
    db.add(InterviewRecord(profile_id=profile.id, round=1,
                           question="自我介绍", score=80))

    risk_time = datetime(2026, 1, 1, 12, 0, 0)
    risk = RiskLog(id=1, user_id=3, request_content="帮我写作业",
                   risk_type="代写", action_taken="拦截", created_at=risk_time)
    db.add(risk)
    db.add_all([
        # InteractionLog.id 在 SQLite 下不是自增(仅 MySQL 为 BIGINT),需显式给值
        InteractionLog(id=1, user_id=3, session_id="s-1", role="student",
                       branch="tutor", content="帮我写作业",
                       created_at=risk_time - timedelta(minutes=10)),
        InteractionLog(id=2, user_id=3, session_id="s-1", role="assistant",
                       branch="tutor", content="我明白了",
                       created_at=risk_time + timedelta(minutes=10)),
        OperationLog(admin_id=5, action="approve", target_type="course",
                     target_id=10, detail="审核通过",
                     created_at=risk_time - timedelta(days=1)),
        OperationLog(admin_id=5, action="update", target_type="risk_log",
                     target_id=1, detail="已电话提醒",
                     created_at=risk_time + timedelta(hours=1)),
        WriteAuditLog(user_id=3, user_role="student", action="assignment.submit",
                      action_label="提交作业", approval_mode="auto",
                      status="executed", target_type="assignment", target_id=7,
                      detail="提交成功", created_at=risk_time),
    ])
    db.commit()


def test_teacher_student_overview_returns_learning_snapshot(db):
    teacher = db.get(User, 1)
    data = teacher_api.get_student_course_overview(10, 3, teacher, db)

    assert data["course"]["name"] == "软件测试"
    assert data["student"]["name"] == "小明"
    assert data["progress"]["overall_progress"] == 45.0
    assert [item["kp_name"] for item in data["progress"]["weak_points"]] == ["等价类"]
    assert data["wrong_questions"]["total"] == 1
    assert data["wrong_questions"]["recent"][0]["kp_name"] == "等价类"
    assert data["review_plans"]["pending"] == 1
    assert data["review_plans"]["due"] == 1
    assert data["interviews"]["total"] == 1
    assert data["interviews"]["avg_score"] == 80.0

    # 已选课但没有学情档案:返回零值结构
    empty = teacher_api.get_student_course_overview(10, 6, teacher, db)
    assert empty["progress"]["overall_progress"] == 0.0
    assert empty["wrong_questions"] == {"total": 0, "recent": []}
    assert empty["interviews"]["avg_score"] is None


def test_teacher_student_overview_permission_boundaries(db):
    teacher = db.get(User, 1)
    with pytest.raises(HTTPException) as exc:
        teacher_api.get_student_course_overview(10, 4, teacher, db)
    assert exc.value.status_code == 403

    # 非本课教师看不到该课程
    with pytest.raises(HTTPException) as exc:
        teacher_api.get_student_course_overview(10, 3, db.get(User, 2), db)
    assert exc.value.status_code == 404

    with pytest.raises(HTTPException) as exc:
        teacher_api.get_student_course_overview(10, 999, teacher, db)
    assert exc.value.status_code == 404


def test_admin_user_overview_aggregates_courses_actions_and_risk(db):
    data = admin_api.get_user_overview(3, db.get(User, 5), db)

    assert data["user"]["role"] == "student"
    assert data["courses"][0]["id"] == 10
    assert data["courses"][0]["relation"] == "enrolled"
    assert data["courses"][0]["teacher_name"] == "张老师"
    assert any(item["source"] == "write_audit" for item in data["recent_actions"])
    assert data["risk_hits"]["total"] == 1
    assert data["risk_hits"]["recent"][0]["risk_type"] == "代写"

    with pytest.raises(HTTPException) as exc:
        admin_api.get_user_overview(999, db.get(User, 5), db)
    assert exc.value.status_code == 404


def test_admin_course_overview_counts_and_audit_history(db):
    data = admin_api.get_course_overview(10, db.get(User, 5), db)

    assert data["course"]["audit_status"] == "approved"
    assert data["teacher"]["name"] == "张老师"
    assert data["materials"]["total"] == 2
    assert data["materials"]["by_type"] == {"courseware": 1, "exercise": 1}
    assert data["knowledge_points"] == 2
    assert data["classes"] == {"total": 1, "students": 1, "enrollments": 2}
    assert len(data["audit_history"]) == 1
    assert data["audit_history"][0]["admin_name"] == "管理员"

    with pytest.raises(HTTPException) as exc:
        admin_api.get_course_overview(999, db.get(User, 5), db)
    assert exc.value.status_code == 404


def test_risk_log_context_returns_surrounding_interactions(db):
    data = admin_api.get_risk_log_context(1, db.get(User, 5), db)

    assert data["risk_log"]["risk_type"] == "代写"
    assert data["user"]["name"] == "小明"
    assert [item["content"] for item in data["interaction_context"]["before"]] == ["帮我写作业"]
    assert [item["content"] for item in data["interaction_context"]["after"]] == ["我明白了"]
    assert data["handling"][0]["detail"] == "已电话提醒"
    assert data["handling"][0]["admin_name"] == "管理员"

    with pytest.raises(HTTPException) as exc:
        admin_api.get_risk_log_context(999, db.get(User, 5), db)
    assert exc.value.status_code == 404
