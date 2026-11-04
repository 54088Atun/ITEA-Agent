"""决策 #7:学情统计按班级独立,不跨班合并"""
import importlib

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.session import Base
from app.models.classroom import ClassMember, Classroom
from app.models.course import Course, KnowledgePoint
from app.models.profile import MasteryRecord, StudentProfile
from app.models.user import User
from app.services import course_access


stats_module = importlib.import_module("app.agent.tools.stats_analyzer")


@pytest.fixture()
def db(monkeypatch):
    engine = create_engine("sqlite:///:memory:", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    session.add_all([
        User(id=1, role="teacher", name="张老师", email="t1@example.com",
             password_hash="x", status="active"),
        User(id=3, role="student", name="一班组员", email="s1@example.com",
             password_hash="x", status="active"),
        User(id=4, role="student", name="二班组员", email="s2@example.com",
             password_hash="x", status="active"),
        Course(id=10, teacher_id=1, name="软件测试", code="ST101",
               audit_status="approved"),
        Classroom(id=20, teacher_id=1, course_id=10, name="一班",
                  invite_code="AAA11111"),
        Classroom(id=21, teacher_id=1, course_id=10, name="二班",
                  invite_code="BBB22222"),
        KnowledgePoint(id=30, course_id=10, name="等价类划分"),
        ClassMember(class_id=20, student_id=3, status="active"),
        ClassMember(class_id=21, student_id=4, status="active"),
        StudentProfile(id=100, user_id=3, course_id=10, overall_progress=80),
        StudentProfile(id=101, user_id=4, course_id=10, overall_progress=40),
        MasteryRecord(profile_id=100, kp_id=30, mastery_level=90),
        MasteryRecord(profile_id=101, kp_id=30, mastery_level=50),
    ])
    session.commit()

    monkeypatch.setattr(stats_module, "SessionLocal", Session)
    monkeypatch.setattr(course_access, "SessionLocal", Session)
    yield session
    session.close()
    engine.dispose()


def test_distribution_can_scope_to_single_class(db):
    result = stats_module.stats_analyzer(
        10, "distribution", user_id=1, class_id=20,
    )

    assert result["total_students"] == 1
    assert result["distribution"]["优秀(≥80)"] == 1
    assert result["distribution"]["薄弱(<40)"] == 0


def test_weakness_can_scope_to_single_class(db):
    result = stats_module.stats_analyzer(
        10, "weakness", user_id=1, class_id=21,
    )

    assert len(result["weak_points"]) == 1
    assert result["weak_points"][0]["avg_mastery"] == 50.0
    assert result["weak_points"][0]["student_count"] == 1


def test_course_level_stats_remain_aggregated(db):
    result = stats_module.stats_analyzer(10, "distribution", user_id=1)

    assert result["total_students"] == 2


def test_class_must_belong_to_selected_course(db):
    from fastapi import HTTPException

    from app.api.teacher import _owned_class_in_course
    from app.models.course import Course

    db.add(Course(id=11, teacher_id=1, name="另一门课", code="ST102",
                  audit_status="approved"))
    db.commit()

    with pytest.raises(HTTPException) as exc:
        _owned_class_in_course(db, 20, 11, db.get(User, 1))

    assert exc.value.status_code == 400
