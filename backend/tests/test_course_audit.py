"""TC-09 课程审核口径测试

口径:
- 私有课程保留平台审核,新建默认 approved;只有 approved 对学生开放
- pending/rejected 时学生列表不出现,详情/知识点/素材/学情一律 403
- 已加入的选课关系保留,重新 approved 后自动恢复
- 教师始终可见自己的课程,管理员可见全部
"""
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.requests import Request

from app.api import teacher as teacher_api
from app.api.admin import admin_delete_course, audit_course
from app.api.classroom import create_class, join_class
from app.api.course import (
    create_course, get_course, list_courses, list_knowledge_points, list_materials,
)
from app.api.course_share import create_share
from app.api.student import enroll_course, get_progress_by_path, my_courses
from app.api.teacher import create_my_course
from app.db.session import Base
from app.models.assignment import Assignment
from app.models.classroom import Classroom, CourseEnrollment
from app.models.course import Course, CourseMaterial, KnowledgePoint
from app.models.log import OperationLog
from app.models.profile import StudentProfile
from app.models.user import User
from app.schemas.admin import CourseAuditRequest
from app.schemas.assignment import CourseShareCreate
from app.schemas.classroom import ClassCreate, JoinClassRequest
from app.schemas.course import CourseCreate


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
    student = User(id=3, role="student", name="小明", email="s1@example.com",
                   password_hash="x", status="active")
    outsider = User(id=4, role="student", name="小红", email="s2@example.com",
                    password_hash="x", status="active")
    admin = User(id=5, role="admin", name="管理员", email="admin@example.com",
                 password_hash="x", status="active", admin_level="super")
    approved = Course(id=10, teacher_id=1, name="已通过", code="A101",
                      audit_status="approved")
    rejected = Course(id=11, teacher_id=1, name="已驳回", code="R101",
                      audit_status="rejected")
    pending = Course(id=12, teacher_id=1, name="审核中", code="P101",
                     audit_status="pending")
    db.add_all([teacher, student, outsider, admin, approved, rejected, pending])
    db.add_all([
        CourseEnrollment(course_id=10, student_id=3, source="class"),
        CourseEnrollment(course_id=11, student_id=3, source="class"),
        StudentProfile(user_id=3, course_id=10, overall_progress=10),
        StudentProfile(user_id=3, course_id=11, overall_progress=20),
        CourseMaterial(course_id=11, type="courseware", title="被驳回的课件",
                       file_path="/tmp/r.pdf"),
        KnowledgePoint(course_id=11, name="越权知识点"),
    ])
    db.commit()


def _request() -> Request:
    return Request({
        "type": "http", "method": "PATCH", "path": "/",
        "headers": [], "query_string": b"",
        "client": ("127.0.0.1", 1234), "server": ("testserver", 80),
        "scheme": "http",
    })


def test_student_only_sees_approved_courses(db):
    student = db.get(User, 3)
    assert [c.id for c in list_courses(student, db)] == [10]
    assert [c["id"] for c in my_courses(student, db)] == [10]


def test_student_blocked_from_unapproved_course_content(db):
    student = db.get(User, 3)
    for course_id in (11, 12):
        with pytest.raises(HTTPException) as exc:
            get_course(course_id, student, db)
        assert exc.value.status_code == 403

    with pytest.raises(HTTPException) as exc:
        list_knowledge_points(11, student, db)
    assert exc.value.status_code == 403
    with pytest.raises(HTTPException) as exc:
        list_materials(11, student, db)
    assert exc.value.status_code == 403


def test_enroll_and_progress_reject_unapproved_course(db):
    student = db.get(User, 3)
    with pytest.raises(HTTPException) as exc:
        enroll_course(11, student, db)
    assert exc.value.status_code == 403
    assert "审核" in exc.value.detail

    with pytest.raises(HTTPException) as exc:
        get_progress_by_path(11, student, db)
    assert exc.value.status_code == 403
    assert "审核" in exc.value.detail


def test_teacher_and_admin_see_unapproved_courses(db):
    teacher = db.get(User, 1)
    admin = db.get(User, 5)
    assert {c.id for c in list_courses(teacher, db)} == {10, 11, 12}
    assert {c.id for c in list_courses(admin, db)} == {10, 11, 12}
    assert get_course(11, teacher, db).audit_status == "rejected"


def test_rejected_course_cannot_be_shared(db):
    teacher = db.get(User, 1)
    with pytest.raises(HTTPException) as exc:
        create_share(11, CourseShareCreate(), teacher, db)
    assert exc.value.status_code == 400
    assert "审核" in exc.value.detail


def test_join_class_blocked_then_restored_after_approval(db):
    teacher = db.get(User, 1)
    admin = db.get(User, 5)
    outsider = db.get(User, 4)
    classroom = create_class(ClassCreate(name="审核班", course_id=11), teacher, db)

    with pytest.raises(HTTPException) as exc:
        join_class(JoinClassRequest(invite_code=classroom.invite_code), outsider, db)
    assert exc.value.status_code == 403
    assert "审核" in exc.value.detail

    audit_course(11, CourseAuditRequest(audit_status="approved"), _request(), admin, db)

    join_class(JoinClassRequest(invite_code=classroom.invite_code), outsider, db)
    assert [c.id for c in list_courses(outsider, db)] == [11]

    # 再次驳回:已选学生立即不可见,但选课关系保留
    audit_course(11, CourseAuditRequest(audit_status="rejected"), _request(), admin, db)
    assert list_courses(outsider, db) == []
    assert db.query(CourseEnrollment).filter_by(course_id=11, student_id=4).first()

    # 重新通过后自动恢复
    audit_course(11, CourseAuditRequest(audit_status="approved"), _request(), admin, db)
    assert [c.id for c in list_courses(outsider, db)] == [11]


def test_new_courses_default_pending(db):
    teacher = db.get(User, 1)
    student = db.get(User, 3)

    created = create_course(CourseCreate(name="新课程 A", code="NEWA"), teacher, db)
    assert created.audit_status == "pending"

    created2 = create_my_course(CourseCreate(name="新课程 B", code="NEWB"), teacher, db)
    assert created2.audit_status == "pending"

    # 待审核课程不对学生开放
    assert {c.id for c in list_courses(student, db)} == {10}


def test_archive_restore_lifecycle_and_template_visibility(db):
    teacher = db.get(User, 1)
    student = db.get(User, 3)

    archived = teacher_api.archive_my_course(10, teacher, db)
    assert archived.archived_at is not None
    assert archived.deleted_at is None
    assert {c.id for c in teacher_api.list_my_courses(teacher, db)} == {11, 12}
    assert {c.id for c in teacher_api.list_my_courses(
        teacher, db, lifecycle="archived")} == {10}
    assert teacher_api.list_my_courses(teacher, db, lifecycle="deleted") == []
    assert {c["id"] for c in teacher_api.list_course_templates(
        teacher, db)["items"]} == {11, 12}

    # 归档不切断已选学生的历史学习数据
    assert get_course(10, student, db).id == 10
    assert [c["id"] for c in my_courses(student, db)] == [10]

    restored = teacher_api.restore_my_course(10, teacher, db)
    assert restored.archived_at is None
    assert restored.deleted_at is None
    assert 10 in {c.id for c in teacher_api.list_my_courses(teacher, db)}


def test_soft_delete_retains_related_data_and_restore(db):
    teacher = db.get(User, 1)
    student = db.get(User, 3)
    material = CourseMaterial(
        course_id=10, type="courseware", title="保留课件", file_path="/tmp/keep.pdf",
    )
    kp = KnowledgePoint(course_id=10, name="保留知识点")
    classroom = Classroom(
        id=100, teacher_id=1, course_id=10, name="保留班级", invite_code="KEEP100",
    )
    assignment = Assignment(id=100, teacher_id=1, course_id=10, title="保留作业")
    db.add_all([material, kp, classroom, assignment])
    db.commit()

    teacher_api.archive_my_course(10, teacher, db)
    result = teacher_api.delete_my_course(10, teacher, db)
    assert result == {"id": 10, "deleted": True}
    course = db.get(Course, 10)
    assert course is not None
    assert course.deleted_at is not None
    assert teacher_api.list_my_courses(teacher, db) == [] or all(
        c.id != 10 for c in teacher_api.list_my_courses(teacher, db)
    )
    assert teacher_api.list_my_courses(teacher, db, lifecycle="archived") == []
    assert {c.id for c in teacher_api.list_my_courses(
        teacher, db, lifecycle="deleted")} == {10}
    assert all(c["id"] != 10 for c in teacher_api.list_course_templates(
        teacher, db)["items"])

    # 回收站课程不对普通课程列表和详情开放
    assert list_courses(student, db) == []
    assert my_courses(student, db) == []
    with pytest.raises(HTTPException) as exc:
        get_course(10, student, db)
    assert exc.value.status_code in (403, 404)

    # 软删除只改生命周期字段，课程及关联数据全部保留
    assert db.get(CourseMaterial, material.id) is not None
    assert db.get(KnowledgePoint, kp.id) is not None
    assert db.get(Classroom, 100) is not None
    assert db.get(Assignment, 100) is not None
    assert db.query(CourseEnrollment).filter_by(course_id=10, student_id=3).one()
    assert db.query(StudentProfile).filter_by(course_id=10, user_id=3).one()

    restored = teacher_api.restore_my_course(10, teacher, db)
    assert restored.archived_at is None
    assert restored.deleted_at is None
    assert [c.id for c in list_courses(student, db)] == [10]


def test_archive_deleted_course_returns_400(db):
    teacher = db.get(User, 1)
    teacher_api.delete_my_course(10, teacher, db)
    with pytest.raises(HTTPException) as exc:
        teacher_api.archive_my_course(10, teacher, db)
    assert exc.value.status_code == 400


def test_lifecycle_actions_require_owner_or_admin(db):
    other = User(
        id=2, role="teacher", name="李老师", email="t2@example.com",
        password_hash="x", status="active",
    )
    db.add(other)
    db.commit()
    for action in (
        teacher_api.archive_my_course,
        teacher_api.delete_my_course,
        teacher_api.restore_my_course,
    ):
        with pytest.raises(HTTPException) as exc:
            action(10, other, db)
        assert exc.value.status_code == 404

    admin = db.get(User, 5)
    assert teacher_api.archive_my_course(10, admin, db).archived_at is not None
    restored = teacher_api.restore_my_course(10, admin, db)
    assert restored.archived_at is None and restored.deleted_at is None


def test_admin_soft_delete_preserves_data_and_audit(db):
    admin = db.get(User, 5)
    result = admin_delete_course(11, _request(), admin, db)

    assert result == {"id": 11, "deleted": True}
    assert db.get(Course, 11).deleted_at is not None
    assert db.query(CourseEnrollment).filter_by(course_id=11, student_id=3).one()
    assert db.query(StudentProfile).filter_by(course_id=11, user_id=3).one()
    assert db.query(CourseMaterial).filter_by(course_id=11).one()
    assert db.query(KnowledgePoint).filter_by(course_id=11).one()
    log = db.query(OperationLog).filter_by(
        action="delete", target_type="course", target_id=11,
    ).one()
    assert log.admin_id == admin.id
