"""班级维度学情与作业/考试统计(CL-05)"""
from datetime import datetime

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.classroom import get_class_report
from app.db.session import Base
from app.models.assignment import Assignment, Submission
from app.models.classroom import ClassMember, Classroom
from app.models.course import Course, KnowledgePoint
from app.models.exam import Exam, ExamQuestion, ExamRecord
from app.models.profile import MasteryRecord, StudentProfile, WrongQuestion
from app.models.question import Question
from app.models.user import User
from app.services.class_stats import build_class_stats


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
        User(id=1, role="teacher", name="张老师", email="t1@example.com",
             password_hash="x", status="active"),
        User(id=2, role="teacher", name="李老师", email="t2@example.com",
             password_hash="x", status="active"),
        User(id=3, role="student", name="小明", email="s1@example.com",
             password_hash="x", status="active"),
        User(id=4, role="student", name="小红", email="s2@example.com",
             password_hash="x", status="active"),
        User(id=5, role="student", name="小刚", email="s3@example.com",
             password_hash="x", status="active"),
        Course(id=10, teacher_id=1, name="软件测试", code="ST101",
               audit_status="approved"),
        Classroom(id=20, teacher_id=1, course_id=10, name="测试 1 班",
                  invite_code="ABCD1234"),
        KnowledgePoint(id=30, course_id=10, name="等价类划分"),
        KnowledgePoint(id=31, course_id=10, name="边界值分析"),
    ])
    db.add_all([
        ClassMember(class_id=20, student_id=3, status="active"),
        ClassMember(class_id=20, student_id=4, status="active"),
        ClassMember(class_id=20, student_id=5, status="left"),
        StudentProfile(id=100, user_id=3, course_id=10, overall_progress=80),
        StudentProfile(id=101, user_id=4, course_id=10, overall_progress=40),
        StudentProfile(id=102, user_id=5, course_id=10, overall_progress=100),
        MasteryRecord(profile_id=100, kp_id=30, mastery_level=50),
        MasteryRecord(profile_id=101, kp_id=30, mastery_level=70),
        MasteryRecord(profile_id=100, kp_id=31, mastery_level=90),
        WrongQuestion(profile_id=100, kp_id=30, question_content="错题一"),
        Assignment(id=40, teacher_id=1, course_id=10, class_id=20,
                   title="第一次作业", status="published"),
        Submission(id=200, assignment_id=40, student_id=3, content="答案",
                   score=80, confirmed_at=datetime.utcnow()),
        Submission(id=201, assignment_id=40, student_id=4, content="答案"),
        Exam(id=50, teacher_id=1, course_id=10, class_id=20,
             title="第一次测验", total_score=10, status="published"),
        Question(id=60, teacher_id=1, course_id=10, type="short",
                 stem="简述等价类", answer="参考答案"),
        ExamQuestion(exam_id=50, question_id=60, score=10, sort=0),
        ExamRecord(exam_id=50, student_id=3, answers="{}", total_score=15,
                   correct_count=1, question_count=2),
        ExamRecord(exam_id=50, student_id=4, answers="{}", total_score=20,
                   correct_count=2, question_count=2, graded_at=datetime.utcnow()),
    ])
    db.commit()


def test_class_stats_by_class_dimension(db):
    classroom = db.get(Classroom, 20)
    result = build_class_stats(db, classroom)

    assert result["class_name"] == "测试 1 班"
    assert result["course_id"] == 10
    assert result["course_name"] == "软件测试"
    # 已退出成员不参与统计
    assert result["student_count"] == 2
    assert result["avg_progress"] == 60.0
    assert [s["name"] for s in result["students"]] == ["小红", "小明"]
    assert result["students"][0]["overall_progress"] == 40.0
    assert result["students"][1]["weak_count"] == 1

    weak = {item["kp_name"]: item for item in result["weak_points"]}
    assert weak["等价类划分"]["avg_mastery"] == 60.0
    assert weak["等价类划分"]["wrong_count"] == 1
    assert weak["边界值分析"]["avg_mastery"] == 90.0

    assignment = result["assignments"][0]
    assert assignment["submitted"] == 2
    assert assignment["confirmed"] == 1
    assert assignment["pending"] == 1
    assert assignment["avg_score"] == 80.0

    exam = result["exams"][0]
    assert exam["submitted"] == 2
    assert exam["pending_manual"] == 1
    assert exam["avg_score"] == 17.5


def test_class_report_rejects_other_teacher(db):
    with pytest.raises(HTTPException) as exc:
        get_class_report(20, db.get(User, 2), db)
    assert exc.value.status_code == 403
