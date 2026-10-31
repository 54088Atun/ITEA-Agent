"""持久化通知中心:发布触达、已读、分类偏好与免打扰"""
from datetime import datetime, timedelta
from types import SimpleNamespace
import importlib

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.api.student as student_api
from app.api.assignments import create_assignment, publish_assignment
from app.api.exams import create_exam, create_question
from app.api.teacher import create_interview_assignment
from app.db.session import Base
from app.models.classroom import ClassMember, Classroom, CourseEnrollment
from app.models.course import Course
from app.models.profile import ReviewPlan, StudentProfile, WrongQuestion
from app.models.user import User
from app.schemas.assignment import AssignmentCreate
from app.schemas.exam import ExamCreate, ExamQuestionItem, QuestionCreate
from app.schemas.teacher import InterviewAssignmentCreate
from app.services.feature_flags import seed_defaults

reminder_scheduler = importlib.import_module("app.agent.tools.reminder_scheduler")


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    seed(session)
    seed_defaults(session)
    yield session
    session.close()
    engine.dispose()


def seed(db):
    db.add_all([
        User(id=1, role="teacher", name="张老师", email="t1@example.com",
             password_hash="x", status="active"),
        User(id=3, role="student", name="小明", email="s1@example.com",
             password_hash="x", status="active"),
        User(id=4, role="student", name="小红", email="s2@example.com",
             password_hash="x", status="active"),
        Course(id=10, teacher_id=1, name="软件测试", code="ST101",
               audit_status="approved"),
        Classroom(id=20, teacher_id=1, course_id=10, name="测试 1 班",
                  invite_code="ABCD1234"),
    ])
    db.add(ClassMember(class_id=20, student_id=3, status="active"))
    db.add(CourseEnrollment(course_id=10, student_id=3, source="class", class_id=20))
    db.commit()


def _assignment(db, title="第一次作业", publish=True):
    return create_assignment(
        AssignmentCreate(title=title, course_id=10, publish=publish),
        db.get(User, 1), db,
    )


def _exam(db):
    question = create_question(QuestionCreate(
        course_id=10, type="single", stem="等价类划分的核心是？",
        options=[{"key": "A", "text": "划分等价类"}, {"key": "B", "text": "穷举"}],
        answer="A",
    ), db.get(User, 1), db)
    return create_exam(ExamCreate(
        title="第一次测验", course_id=10, class_id=20, publish=True,
        questions=[ExamQuestionItem(question_id=question["id"], score=10)],
    ), db.get(User, 1), db)


def _preferences(**overrides):
    values = {
        "assignment_enabled": True,
        "exam_enabled": True,
        "interview_enabled": True,
        "review_enabled": True,
        "quiet_start": None,
        "quiet_end": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_publish_notifies_only_targets_and_list_is_persistent(db):
    student = db.get(User, 3)
    outsider = db.get(User, 4)
    teacher = db.get(User, 1)

    assignment = _assignment(db)
    draft = _assignment(db, title="草稿作业", publish=False)
    exam = _exam(db)
    interview = create_interview_assignment(InterviewAssignmentCreate(
        title="模拟面试", course_id=10,
    ), teacher, db)

    first = student_api.get_notifications(student, db)
    second = student_api.get_notifications(student, db)
    assert first["unread_count"] == 3
    assert [n["id"] for n in second["notifications"]] == [
        n["id"] for n in first["notifications"]
    ]
    assert second["unread_count"] == 3
    # MySQL 无小数秒 DATETIME 会四舍五入,即时投递时间必须按整秒入库
    assert all(n["deliver_at"].microsecond == 0 for n in first["notifications"])
    assert {n["category"] for n in first["notifications"]} == {
        "assignment", "exam", "interview",
    }
    assert all(n["link_url"].startswith("/student/") for n in first["notifications"])
    assert student_api.get_notifications(outsider, db)["notifications"] == []

    # 草稿发布才触达;重复发布按来源去重
    assert all(n["source_id"] != str(draft["id"]) for n in first["notifications"])
    publish_assignment(draft["id"], teacher, db)
    publish_assignment(assignment["id"], teacher, db)
    publish_assignment(draft["id"], teacher, db)
    notes = student_api.get_notifications(student, db)["notifications"]
    assert len(notes) == 4
    assert len([n for n in notes if n["source_type"] == "assignment"
                and n["source_id"] == str(assignment["id"])]) == 1
    assert len([n for n in notes if n["source_type"] == "assignment"
                and n["source_id"] == str(draft["id"])]) == 1
    assert any(n["source_type"] == "exam" and n["source_id"] == str(exam["id"])
               for n in notes)
    assert any(n["source_type"] == "interview" and n["source_id"] == str(interview["id"])
               for n in notes)


def test_read_preferences_and_quiet_hours(db):
    student = db.get(User, 3)
    outsider = db.get(User, 4)
    teacher = db.get(User, 1)
    first = _assignment(db)
    note = student_api.get_notifications(student, db)["notifications"][0]

    with pytest.raises(HTTPException) as exc:
        student_api.mark_notification_read(note["id"], outsider, db)
    assert exc.value.status_code == 404

    student_api.mark_notification_read(note["id"], student, db)
    result = student_api.get_notifications(student, db)
    assert result["unread_count"] == 0
    assert len(result["notifications"]) == 1
    assert result["notifications"][0]["is_read"] is True

    _assignment(db, title="第二次作业")
    assert student_api.get_notifications(student, db)["unread_count"] == 1
    student_api.mark_all_notifications_read(student, db)
    assert student_api.get_notifications(student, db)["unread_count"] == 0

    prefs = student_api.update_notification_preferences(
        _preferences(assignment_enabled=False), student, db,
    )
    assert prefs["assignment_enabled"] is False
    _assignment(db, title="关闭分类后的作业")
    assert len(student_api.get_notifications(student, db)["notifications"]) == 2

    now = datetime.utcnow()
    quiet_start = (now - timedelta(hours=1)).strftime("%H:%M")
    quiet_end = (now + timedelta(hours=1)).strftime("%H:%M")
    student_api.update_notification_preferences(
        _preferences(quiet_start=quiet_start, quiet_end=quiet_end), student, db,
    )
    delayed = _assignment(db, title="免打扰作业")
    assert len(student_api.get_notifications(student, db)["notifications"]) == 2

    from app.models.notification import Notification
    row = db.query(Notification).filter_by(
        user_id=student.id, source_type="assignment", source_id=str(delayed["id"]),
    ).one()
    assert row.deliver_at > row.created_at
    row.deliver_at = datetime.utcnow() - timedelta(seconds=1)
    db.commit()
    delivered = student_api.get_notifications(student, db)
    assert len(delivered["notifications"]) == 3
    assert delivered["unread_count"] == 1
    assert student_api.get_notification_preferences(student, db)["quiet_start"] == quiet_start


def test_review_reminder_is_persistent_and_deduplicated(db, monkeypatch):
    student = db.get(User, 3)
    profile = StudentProfile(user_id=student.id, course_id=10, overall_progress=0)
    db.add(profile)
    db.flush()
    wrong = WrongQuestion(profile_id=profile.id, question_content="待复习错题")
    db.add(wrong)
    db.flush()
    db.add(ReviewPlan(
        wrong_question_id=wrong.id,
        next_review_at=datetime.utcnow() - timedelta(minutes=1),
        status="pending",
    ))
    db.commit()

    SchedulerSession = sessionmaker(bind=db.get_bind())
    monkeypatch.setattr("app.db.session.SessionLocal", SchedulerSession)
    reminder_scheduler._notified_plan_ids.clear()
    reminder_scheduler._scan_due_reviews()
    reminder_scheduler._scan_due_reviews()

    result = student_api.get_notifications(student, db)
    assert result["unread_count"] == 1
    assert len(result["notifications"]) == 1
    assert result["notifications"][0]["category"] == "review"
    assert result["notifications"][0]["link_url"] == "/student/review"
