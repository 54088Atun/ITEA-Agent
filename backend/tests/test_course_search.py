"""TC-10 课程搜索与筛选测试

覆盖:
- 教师按课程名/代码搜索、按学期与审核状态筛选
- 教师只能搜到自己的课程;管理员可跨教师搜索
- 学生课程列表仍受审核可见性约束,搜索不会越权
- 空关键词/无匹配/首尾空格处理
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.admin import list_courses as admin_list_courses
from app.api.course import list_courses
from app.api.student import my_courses
from app.api.teacher import list_my_courses
from app.db.session import Base
from app.models.classroom import CourseEnrollment
from app.models.course import Course
from app.models.profile import StudentProfile
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
    admin = User(id=5, role="admin", name="管理员", email="admin@example.com",
                 password_hash="x", status="active", admin_level="super")
    db.add_all([teacher, other, student, admin])
    db.add_all([
        Course(id=10, teacher_id=1, name="数据结构", code="CS201",
               semester="2026春", audit_status="approved"),
        Course(id=11, teacher_id=1, name="数据库原理", code="DB301",
               semester="2026春", audit_status="rejected"),
        Course(id=12, teacher_id=1, name="Web 开发", code="WEB101",
               semester="2026秋", audit_status="approved"),
        Course(id=13, teacher_id=2, name="操作系统", code="OS201",
               semester="2026秋", audit_status="approved"),
    ])
    db.add_all([
        CourseEnrollment(course_id=10, student_id=3, source="class"),
        CourseEnrollment(course_id=11, student_id=3, source="class"),
        CourseEnrollment(course_id=12, student_id=3, source="class"),
        StudentProfile(user_id=3, course_id=10, overall_progress=10),
        StudentProfile(user_id=3, course_id=11, overall_progress=20),
        StudentProfile(user_id=3, course_id=12, overall_progress=30),
    ])
    db.commit()


def ids(rows):
    return {c.id for c in rows}


def test_teacher_search_by_name_and_code(db):
    teacher = db.get(User, 1)
    assert ids(list_my_courses(teacher, db, keyword="数据")) == {10, 11}
    assert ids(list_my_courses(teacher, db, keyword="WEB")) == {12}
    assert ids(list_my_courses(teacher, db, keyword="  WEB  ")) == {12}


def test_teacher_filter_by_semester_and_audit_status(db):
    teacher = db.get(User, 1)
    assert ids(list_my_courses(teacher, db, semester="2026春")) == {10, 11}
    assert ids(list_my_courses(teacher, db, audit_status="approved")) == {10, 12}
    assert ids(list_my_courses(
        teacher, db, semester="2026春", audit_status="rejected")) == {11}


def test_teacher_cannot_search_others_courses(db):
    other = db.get(User, 2)
    assert ids(list_my_courses(other, db)) == {13}
    assert list_my_courses(other, db, keyword="数据") == []


def test_admin_searches_across_teachers(db):
    admin = db.get(User, 5)
    assert ids(list_my_courses(admin, db, semester="2026秋")) == {12, 13}
    assert ids(list_my_courses(admin, db, keyword="操作")) == {13}


def test_generic_course_list_filters_for_teacher(db):
    teacher = db.get(User, 1)
    assert ids(list_courses(teacher, db, keyword="数据")) == {10, 11}
    assert ids(list_courses(teacher, db, audit_status="rejected")) == {11}


def test_student_search_never_escapes_audit_visibility(db):
    student = db.get(User, 3)
    assert ids(list_courses(student, db, keyword="数据")) == {10}
    assert list_courses(student, db, audit_status="rejected") == []
    assert list_courses(student, db, keyword="不存在的课程") == []


def test_empty_and_no_match(db):
    teacher = db.get(User, 1)
    # 纯空格视为未搜索,返回全部
    assert ids(list_my_courses(teacher, db, keyword="   ")) == {10, 11, 12}
    assert list_my_courses(teacher, db, semester="2025秋") == []
    assert list_my_courses(teacher, db, keyword="zzz") == []


def test_student_my_courses_search_and_semester(db):
    student = db.get(User, 3)
    assert {c["id"] for c in my_courses(student, db, keyword="数据")} == {10}
    assert {c["id"] for c in my_courses(student, db, semester="2026春")} == {10}
    assert {c["id"] for c in my_courses(student, db, keyword="Web")} == {12}
    assert my_courses(student, db, keyword="zzz") == []


def test_admin_course_list_filters_by_semester(db):
    admin = db.get(User, 5)
    result = admin_list_courses(
        page=1, size=20, audit_status=None, semester="2026春",
        keyword=None, admin=admin, db=db,
    )
    assert {c.id for c in result["items"]} == {10, 11}

    result = admin_list_courses(
        page=1, size=20, audit_status=None, semester="2026春",
        keyword="数据", admin=admin, db=db,
    )
    assert {c.id for c in result["items"]} == {10, 11}

    result = admin_list_courses(
        page=1, size=20, audit_status="approved", semester="2026春",
        keyword=None, admin=admin, db=db,
    )
    assert {c.id for c in result["items"]} == {10}
