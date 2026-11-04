"""CL-07 统一课程码测试

一个入口按角色分流:
- 学生用班级课程码 → 加入班级
- 教师用班级课程码 → 复制该班绑定课程
- 教师用教师课程码 → 复制课程快照
- 学生用教师课程码 → 403
"""
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.classroom import create_class
from app.api.course_codes import preview_code, redeem_code
from app.api.course_share import create_share
from app.db.session import Base
from app.models.classroom import Classroom, CodeRedemption, CourseEnrollment
from app.models.course import Course
from app.models.user import User
from app.schemas.assignment import CourseShareCreate
from app.schemas.classroom import ClassCreate, CourseCodeRedeemRequest


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
        User(id=1, role="teacher", name="班主任", email="head@example.com",
             password_hash="x", status="active"),
        User(id=2, role="teacher", name="任课老师", email="t2@example.com",
             password_hash="x", status="active"),
        User(id=3, role="student", name="学生甲", email="s1@example.com",
             password_hash="x", status="active"),
        Course(id=10, teacher_id=1, name="软件测试", code="ST101",
               audit_status="approved"),
    ])
    db.commit()


def _class(db, course_id=10):
    return create_class(ClassCreate(name="测试班", course_id=course_id), db.get(User, 1), db)


def test_preview_routes_by_role(db):
    classroom = _class(db)
    share = create_share(10, CourseShareCreate(expires_days=7, max_uses=3),
                         db.get(User, 1), db, confirm=True)

    teacher_view = preview_code(classroom.invite_code, db.get(User, 2), db)
    assert teacher_view["scope"] == "class"
    assert teacher_view["can_redeem"] is True
    assert teacher_view["usable_for"] == ["teacher", "student"]
    assert teacher_view["remaining_uses"] == classroom.invite_max_uses

    student_view = preview_code(classroom.invite_code, db.get(User, 3), db)
    assert student_view["can_redeem"] is True

    share_view = preview_code(share["code"], db.get(User, 2), db)
    assert share_view["scope"] == "course"
    assert share_view["usable_for"] == ["teacher"]
    assert share_view["can_redeem"] is True

    student_share = preview_code(share["code"], db.get(User, 3), db)
    assert student_share["can_redeem"] is False

    with pytest.raises(HTTPException) as exc:
        preview_code("NOPE1234", db.get(User, 1), db)
    assert exc.value.status_code == 404


def test_student_redeems_class_code(db):
    classroom = _class(db)
    student = db.get(User, 3)
    result = redeem_code(
        CourseCodeRedeemRequest(code=classroom.invite_code), student, db,
    )
    assert result["scope"] == "class"
    assert result["action"] == "class_join"
    assert result["class_id"] == classroom.id

    assert db.query(CourseEnrollment).filter_by(
        course_id=10, student_id=3).first() is not None
    audit = db.query(CodeRedemption).filter_by(
        code=classroom.invite_code, user_id=3).first()
    assert audit and audit.action == "class_join"

    # 重复加入幂等,不重复计次
    used = db.get(Classroom, classroom.id).invite_used
    redeem_code(CourseCodeRedeemRequest(code=classroom.invite_code), student, db)
    assert db.get(Classroom, classroom.id).invite_used == used


def test_teacher_redeems_class_code_copies_course(db):
    classroom = _class(db)
    teacher2 = db.get(User, 2)
    result = redeem_code(
        CourseCodeRedeemRequest(code=classroom.invite_code), teacher2, db,
    )
    assert result["scope"] == "class"
    assert result["action"] == "course_copy"
    assert result["name"].endswith("（副本）")

    copied = db.query(Course).filter(Course.id == result["course_id"]).first()
    assert copied and copied.teacher_id == teacher2.id
    assert copied.audit_status == "approved"
    # 教师使用班级码不消耗学生加入次数
    assert db.get(Classroom, classroom.id).invite_used == 0
    assert db.query(CodeRedemption).filter_by(
        code=classroom.invite_code, user_id=teacher2.id,
        action="course_copy",
    ).first()


def test_teacher_redeems_share_code(db):
    share = create_share(10, CourseShareCreate(expires_days=7, max_uses=3),
                         db.get(User, 1), db, confirm=True)
    teacher2 = db.get(User, 2)
    result = redeem_code(
        CourseCodeRedeemRequest(code=share["code"]), teacher2, db,
    )
    assert result["scope"] == "course"
    assert result["course_id"]
    assert db.query(CodeRedemption).filter_by(
        code=share["code"], user_id=teacher2.id, action="course_copy",
    ).first()


def test_student_cannot_use_teacher_share_code(db):
    share = create_share(10, CourseShareCreate(expires_days=7, max_uses=3),
                         db.get(User, 1), db, confirm=True)
    with pytest.raises(HTTPException) as exc:
        redeem_code(CourseCodeRedeemRequest(code=share["code"]), db.get(User, 3), db)
    assert exc.value.status_code == 403


def test_class_without_course_student_only(db):
    classroom = _class(db, course_id=None)
    view = preview_code(classroom.invite_code, db.get(User, 2), db)
    assert view["usable_for"] == ["student"]
    with pytest.raises(HTTPException) as exc:
        redeem_code(
            CourseCodeRedeemRequest(code=classroom.invite_code), db.get(User, 2), db,
        )
    assert exc.value.status_code == 400

    result = redeem_code(
        CourseCodeRedeemRequest(code=classroom.invite_code), db.get(User, 3), db,
    )
    assert result["action"] == "class_join"


def test_own_class_code_cannot_be_copied_by_head(db):
    classroom = _class(db)
    with pytest.raises(HTTPException) as exc:
        redeem_code(
            CourseCodeRedeemRequest(code=classroom.invite_code), db.get(User, 1), db,
        )
    assert exc.value.status_code == 400
