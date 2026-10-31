"""作业发布 / 学生可见性 / AI 建议批改与教师确认

覆盖:
- 非本课教师不能发布作业
- 草稿不可见,发布后命中班级/课程的学生可见,非目标不可见
- 截止后禁止提交,参考答案截止前不下发
- AI 批改只写 ai_* 字段,教师确认后才写正式分数
- 确认后学生不可再次提交
"""
import asyncio
from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.api.assignments as assignments_api
from app.api.assignments import (
    ai_grade_submission, confirm_grade, create_assignment, get_my_assignment,
    list_assignments, list_my_assignments, publish_assignment,
    submit_assignment,
)
from app.db.session import Base
from app.models.assignment import Assignment, Submission
from app.models.classroom import ClassMember, Classroom, CourseEnrollment
from app.models.course import Course
from app.models.user import User
from app.schemas.assignment import (
    AssignmentCreate, GradeConfirmRequest, SubmissionCreate,
)


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
    course = Course(id=10, teacher_id=1, name="软件测试", code="ST101",
                    audit_status="approved")
    classroom = Classroom(id=20, teacher_id=1, course_id=10, name="测试 1 班",
                          invite_code="ABCD1234")
    db.add_all([teacher, other, student, outsider, course, classroom])
    db.add(ClassMember(class_id=20, student_id=3, status="active"))
    db.add(CourseEnrollment(course_id=10, student_id=3, source="class", class_id=20))
    db.commit()


def _publish(db, **kwargs):
    data = create_assignment(AssignmentCreate(title=kwargs.pop("title", "第一次作业"),
                                              **kwargs), db.get(User, 1), db)
    return db.get(Assignment, data["id"])


def test_teacher_cannot_publish_to_others_course(db):
    with pytest.raises(HTTPException) as exc:
        create_assignment(
            AssignmentCreate(title="越权作业", course_id=10), db.get(User, 2), db,
        )
    assert exc.value.status_code == 403


def test_draft_invisible_until_published(db):
    assignment = _publish(db, course_id=10, publish=False)
    student = db.get(User, 3)
    assert list_my_assignments(student, db) == []

    publish_assignment(assignment.id, db.get(User, 1), db)
    rows = list_my_assignments(student, db)
    assert [r["id"] for r in rows] == [assignment.id]
    assert rows[0]["state"] == "not_submitted"

    # 非目标学生不可见,也不能查看详情
    outsider = db.get(User, 4)
    assert list_my_assignments(outsider, db) == []
    with pytest.raises(HTTPException) as exc:
        get_my_assignment(assignment.id, outsider, db)
    assert exc.value.status_code == 403


def test_reference_answer_hidden_before_due(db):
    assignment = _publish(db, course_id=10, due_days=1,
                          reference_answer="等价类、边界值")
    student = db.get(User, 3)
    detail = get_my_assignment(assignment.id, student, db)
    assert detail["due_passed"] is False
    assert detail["reference_answer"] is None

    assignment.due_at = datetime.utcnow() - timedelta(minutes=1)
    db.commit()
    detail = get_my_assignment(assignment.id, student, db)
    assert detail["due_passed"] is True
    assert detail["reference_answer"] == "等价类、边界值"


def test_submit_blocked_after_due(db):
    assignment = _publish(db, course_id=10, due_days=1)
    student = db.get(User, 3)
    result = submit_assignment(
        assignment.id, SubmissionCreate(content="我的作答"), student, db,
    )
    assert result["state"] == "pending_review"

    assignment.due_at = datetime.utcnow() - timedelta(minutes=1)
    db.commit()
    with pytest.raises(HTTPException) as exc:
        submit_assignment(
            assignment.id, SubmissionCreate(content="补交"), student, db,
        )
    assert exc.value.status_code == 400
    assert "截止" in exc.value.detail


def test_ai_grade_requires_teacher_confirmation(db, monkeypatch):
    async def fake_grade(*args, **kwargs):
        return {"score": 88, "feedback": "AI 建议评语", "source": "rule"}

    monkeypatch.setattr(assignments_api, "grade_submission", fake_grade)

    assignment = _publish(db, course_id=10, due_days=3,
                          reference_answer="等价类划分与边界值分析")
    student = db.get(User, 3)
    teacher = db.get(User, 1)
    submit_assignment(assignment.id, SubmissionCreate(content="等价类划分"), student, db)
    sub = db.query(Submission).filter_by(assignment_id=assignment.id).first()

    result = asyncio.run(ai_grade_submission(sub.id, teacher, db))
    assert result["source"] == "rule"
    assert sub.ai_score == 88
    assert sub.score is None and sub.confirmed_at is None

    # 学生此时只看到"待确认",看不到 AI 建议分
    detail = get_my_assignment(assignment.id, student, db)
    assert detail["state"] == "pending_review"
    assert detail["my_submission"]["score"] is None
    assert detail["my_submission"]["feedback"] is None

    # 非本课教师不能确认
    with pytest.raises(HTTPException) as exc:
        confirm_grade(sub.id, GradeConfirmRequest(score=90), db.get(User, 2), db)
    assert exc.value.status_code == 403

    confirm_grade(sub.id, GradeConfirmRequest(score=90), teacher, db)
    detail = get_my_assignment(assignment.id, student, db)
    assert detail["state"] == "graded"
    assert detail["my_submission"]["score"] == 90
    assert detail["my_submission"]["feedback"] == "AI 建议评语"

    # 已批改后不可再次提交
    with pytest.raises(HTTPException) as exc:
        submit_assignment(assignment.id, SubmissionCreate(content="改一下"), student, db)
    assert exc.value.status_code == 400


def test_teacher_detail_counts_pending(db):
    assignment = _publish(db, course_id=10, due_days=3)
    submit_assignment(
        assignment.id, SubmissionCreate(content="作答"), db.get(User, 3), db,
    )
    rows = list_assignments(db.get(User, 1), db)
    assert rows[0]["submission_count"] == 1
    assert rows[0]["pending_count"] == 1

    detail = assignments_api.get_assignment(assignment.id, db.get(User, 1), db)
    assert detail["submissions"][0]["student_name"] == "小明"
    assert detail["submissions"][0]["confirmed"] is False
