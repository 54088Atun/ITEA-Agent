"""课程私有化与班级邀请测试

覆盖:
- 学生只能看到/访问已选课程
- 未加入课程时详情、知识点、素材均 403
- 班级邀请码加入后获得可见性,退出后回收
- 邀请码过期/超次/无效
- 教师不能把他人课程绑定到自己的班级
"""
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import course as course_api
from app.api.classroom import create_class, join_class, leave_class
from app.api.course import get_course, list_courses, list_knowledge_points, list_materials
from app.api.student import enroll_course
from app.services import course_access
from app.db.session import Base
from app.models.classroom import Classroom, ClassMember, CourseEnrollment
from app.models.course import Course, CourseMaterial, KnowledgePoint
from app.models.user import User
from app.schemas.classroom import ClassCreate, JoinClassRequest


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
    admin = User(id=5, role="admin", name="管理员", email="admin@example.com",
                 password_hash="x", status="active")
    course = Course(id=10, teacher_id=1, name="软件测试", code="ST101",
                    audit_status="approved")
    other_course = Course(id=11, teacher_id=2, name="Web 开发", code="WEB101",
                          audit_status="approved")
    material = CourseMaterial(id=20, course_id=10, type="courseware", title="第一章",
                              file_path="/tmp/ch1.pdf")
    kp = KnowledgePoint(id=30, course_id=10, name="等价类划分")
    db.add_all([teacher, other, student, outsider, admin, course, other_course, material, kp])
    db.commit()


def test_student_only_sees_enrolled_courses(db):
    student = db.get(User, 3)
    assert list_courses(student, db) == []

    db.add(CourseEnrollment(course_id=10, student_id=3, source="class"))
    db.commit()
    visible = list_courses(student, db)
    assert [c.id for c in visible] == [10]


def test_course_detail_blocks_non_member(db):
    student = db.get(User, 3)
    with pytest.raises(HTTPException) as exc:
        get_course(10, student, db)
    assert exc.value.status_code == 403
    assert get_course(10, db.get(User, 1), db).id == 10


def test_knowledge_points_and_materials_blocked(db):
    student = db.get(User, 3)
    with pytest.raises(HTTPException) as exc:
        list_knowledge_points(10, student, db)
    assert exc.value.status_code == 403
    with pytest.raises(HTTPException) as exc:
        list_materials(10, student, db)
    assert exc.value.status_code == 403


def test_self_enroll_requires_enrollment(db):
    student = db.get(User, 3)
    with pytest.raises(HTTPException) as exc:
        enroll_course(10, student, db)
    assert exc.value.status_code == 403

    db.add(CourseEnrollment(course_id=10, student_id=3, source="class"))
    db.commit()
    result = enroll_course(10, student, db)
    assert result.joined is True


def test_join_by_code_grants_then_leave_revokes(db):
    teacher = db.get(User, 1)
    student = db.get(User, 3)
    classroom = create_class(ClassCreate(name="测试 1 班", course_id=10), teacher, db)

    join_class(JoinClassRequest(invite_code=classroom.invite_code), student, db)
    assert [c.id for c in list_courses(student, db)] == [10]
    assert db.query(CourseEnrollment).filter_by(student_id=3, course_id=10).first()

    leave_class(classroom.id, student, db)
    assert list_courses(student, db) == []
    assert db.query(CourseEnrollment).filter_by(student_id=3, course_id=10).first() is None


def test_invalid_expired_and_exhausted_codes(db):
    teacher = db.get(User, 1)
    student = db.get(User, 3)
    classroom = create_class(
        ClassCreate(name="测试 2 班", course_id=10, invite_days=1, invite_max_uses=1),
        teacher, db,
    )

    with pytest.raises(HTTPException) as exc:
        join_class(JoinClassRequest(invite_code="BADCODE1"), student, db)
    assert exc.value.status_code == 404

    join_class(JoinClassRequest(invite_code=classroom.invite_code), student, db)

    # 同一学生重复加入不消耗次数;换一个学生则超次
    join_class(JoinClassRequest(invite_code=classroom.invite_code), student, db)
    outsider = db.get(User, 4)
    with pytest.raises(HTTPException) as exc:
        join_class(JoinClassRequest(invite_code=classroom.invite_code), outsider, db)
    assert exc.value.status_code == 400

    record = db.query(Classroom).filter_by(id=classroom.id).first()
    record.invite_expires_at = datetime.utcnow() - timedelta(minutes=1)
    record.invite_used = 0
    db.commit()
    with pytest.raises(HTTPException) as exc:
        join_class(JoinClassRequest(invite_code=classroom.invite_code), outsider, db)
    assert exc.value.status_code == 400
    assert "过期" in exc.value.detail


def test_teacher_cannot_bind_others_course(db):
    other_teacher = db.get(User, 2)
    with pytest.raises(HTTPException) as exc:
        create_class(ClassCreate(name="越权班级", course_id=10), other_teacher, db)
    assert exc.value.status_code == 403


def test_multiple_classes_keep_visibility_until_last(db):
    teacher = db.get(User, 1)
    student = db.get(User, 3)
    c1 = create_class(ClassCreate(name="A 班", course_id=10), teacher, db)
    c2 = create_class(ClassCreate(name="B 班", course_id=10), teacher, db)

    join_class(JoinClassRequest(invite_code=c1.invite_code), student, db)
    join_class(JoinClassRequest(invite_code=c2.invite_code), student, db)

    leave_class(c1.id, student, db)
    assert [c.id for c in list_courses(student, db)] == [10]

    leave_class(c2.id, student, db)
    assert list_courses(student, db) == []
    assert db.query(ClassMember).filter_by(student_id=3).count() == 2
    assert db.query(Classroom).count() == 2


def test_course_collaborator_management_requires_owner_or_admin(db):
    owner = db.get(User, 1)
    collaborator = db.get(User, 2)
    admin = db.get(User, 5)
    req = SimpleNamespace(teacher_id=collaborator.id)

    with pytest.raises(HTTPException) as exc:
        course_api.add_collaborator(10, req, collaborator, db)
    assert exc.value.status_code == 403

    created = course_api.add_collaborator(10, req, owner, db)
    assert created["teacher_id"] == collaborator.id
    assert [row["teacher_id"] for row in course_api.list_collaborators(10, owner, db)] == [2]

    with pytest.raises(HTTPException) as exc:
        course_api.remove_collaborator(10, collaborator.id, collaborator, db)
    assert exc.value.status_code == 403

    course_api.remove_collaborator(10, collaborator.id, admin, db)
    assert course_api.list_collaborators(10, admin, db) == []
    assert course_api.add_collaborator(10, req, admin, db)["teacher_id"] == 2


def test_collaborator_target_is_teacher_and_grant_is_idempotent(db):
    owner = db.get(User, 1)

    with pytest.raises(HTTPException) as exc:
        course_api.add_collaborator(10, SimpleNamespace(teacher_id=3), owner, db)
    assert exc.value.status_code == 400
    with pytest.raises(HTTPException) as exc:
        course_api.add_collaborator(10, SimpleNamespace(teacher_id=1), owner, db)
    assert exc.value.status_code == 400

    req = SimpleNamespace(teacher_id=2)
    first = course_api.add_collaborator(10, req, owner, db)
    second = course_api.add_collaborator(10, req, owner, db)
    assert second["id"] == first["id"]
    assert len(course_api.list_collaborators(10, owner, db)) == 1


def test_collaborator_visibility_is_revoked_with_grant(db):
    owner = db.get(User, 1)
    collaborator = db.get(User, 2)
    assert {course.id for course in list_courses(collaborator, db)} == {11}

    course_api.add_collaborator(10, SimpleNamespace(teacher_id=2), owner, db)
    assert {course.id for course in list_courses(collaborator, db)} == {10, 11}
    assert get_course(10, collaborator, db).id == 10

    course_api.remove_collaborator(10, collaborator.id, owner, db)
    assert {course.id for course in list_courses(collaborator, db)} == {11}
    with pytest.raises(HTTPException) as exc:
        get_course(10, collaborator, db)
    assert exc.value.status_code == 403


def test_collaborator_can_maintain_course_and_use_agent_scope(db, monkeypatch):
    owner = db.get(User, 1)
    collaborator = db.get(User, 2)
    TestingSession = sessionmaker(bind=db.get_bind())
    monkeypatch.setattr(course_access, "SessionLocal", TestingSession)
    assert course_access.agent_course_scope_error(collaborator.id, 10) == "无权访问该课程"

    course_api.add_collaborator(10, SimpleNamespace(teacher_id=2), owner, db)
    assert course_access.agent_course_scope_error(collaborator.id, 10) is None
    kp = course_api.add_knowledge_point(
        10, name="协作知识点", description="联合维护", parent_id=None,
        teacher=collaborator, db=db,
    )
    assert kp["name"] == "协作知识点"

    course_api.remove_collaborator(10, collaborator.id, owner, db)
    assert course_access.agent_course_scope_error(collaborator.id, 10) == "无权访问该课程"
