"""隐私设置:默认值、可见范围判定与教师侧脱敏(PC-07)"""
import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.classroom import list_members
from app.db.session import Base
from app.models.classroom import ClassMember, Classroom
from app.models.course import Course, KnowledgePoint
from app.models.privacy import PrivacySetting
from app.models.profile import MasteryRecord, StudentProfile
from app.models.user import User
from app.schemas.privacy import PrivacyUpdate
from app.services import privacy as privacy_service
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
        User(id=1, role="teacher", name="张老师", email="t@example.com",
             password_hash="x", status="active"),
        User(id=2, role="student", name="小明", email="m@example.com",
             password_hash="x", status="active"),
        User(id=3, role="student", name="小红", email="h@example.com",
             password_hash="x", status="active"),
        Course(id=10, teacher_id=1, name="软件测试", code="ST101",
               audit_status="approved"),
        Classroom(id=20, teacher_id=1, course_id=10, name="测试 1 班",
                  invite_code="ABCD1234"),
        KnowledgePoint(id=30, course_id=10, name="等价类划分"),
        ClassMember(class_id=20, student_id=2, status="active"),
        ClassMember(class_id=20, student_id=3, status="active"),
        StudentProfile(id=100, user_id=2, course_id=10, overall_progress=80),
        StudentProfile(id=101, user_id=3, course_id=10, overall_progress=60),
        MasteryRecord(profile_id=100, kp_id=30, mastery_level=30),
        MasteryRecord(profile_id=101, kp_id=30, mastery_level=70),
        PrivacySetting(
            user_id=2, name_visibility="private",
            email_visibility="private", learning_visibility="private",
        ),
        PrivacySetting(
            user_id=3, name_visibility="classmates",
            email_visibility="teachers", learning_visibility="teachers",
        ),
    ])
    db.commit()


def test_visibility_matrix_and_defaults(db):
    assert privacy_service.allowed("private", "self")
    assert not privacy_service.allowed("private", "teacher")
    assert privacy_service.allowed("teachers", "teacher")
    assert not privacy_service.allowed("teachers", "classmate")
    assert privacy_service.allowed("classmates", "classmate")

    newcomer = privacy_service.get_or_create(db, 1)
    assert newcomer.name_visibility == "classmates"
    assert newcomer.email_visibility == "private"
    assert newcomer.learning_visibility == "teachers"

    with pytest.raises(ValidationError):
        PrivacyUpdate(name_visibility="everyone")


def test_teacher_member_list_is_masked(db):
    teacher = db.get(User, 1)
    result = list_members(20, teacher, db)
    by_id = {item.student_id: item for item in result.items}

    assert by_id[2].name == "匿名同学"
    assert by_id[2].email == ""
    assert by_id[3].name == "小红"
    assert by_id[3].email == "h@example.com"


def test_class_stats_excludes_private_learning(db):
    classroom = db.get(Classroom, 20)
    result = build_class_stats(db, classroom)

    # 学生总数仍反映班级规模,但明细只保留允许教师查看的记录
    assert result["student_count"] == 2
    assert [s["user_id"] for s in result["students"]] == [3]
    assert result["avg_progress"] == 60.0
    assert [w["avg_mastery"] for w in result["weak_points"]] == [70.0]
