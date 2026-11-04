"""课程模板与复制(自身历史课程)测试

覆盖:
- 复制课程信息、知识点树、素材元数据
- 不复制选课关系、学情
- 自定义名称/代码/学期;代码冲突拒绝
- 只能复制自己的课程;写操作审计
"""
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.teacher import duplicate_my_course, list_course_templates
from app.db.session import Base
from app.models.classroom import CourseEnrollment
from app.models.course import Course, CourseMaterial, KnowledgePoint
from app.models.log import OperationLog
from app.models.profile import StudentProfile
from app.models.user import User
from app.schemas.course import CourseDuplicateRequest


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
    source = Course(id=10, teacher_id=1, name="软件测试", code="ST101",
                    syllabus="第一章 基础", semester="2026春",
                    audit_status="approved")
    parent = KnowledgePoint(id=30, course_id=10, name="等价类划分",
                            description="按输入域划分")
    child = KnowledgePoint(id=31, course_id=10, name="有效等价类", parent_id=30)
    material = CourseMaterial(id=40, course_id=10, type="courseware",
                              title="第一章课件", file_path="/tmp/ch1.pdf",
                              chunk_count=12)
    db.add_all([teacher, other, student, admin, source, parent, child, material])
    db.add_all([
        CourseEnrollment(course_id=10, student_id=3, source="class"),
        StudentProfile(user_id=3, course_id=10, overall_progress=30),
    ])
    db.commit()


def test_duplicate_copies_structure_without_student_data(db):
    teacher = db.get(User, 1)
    result = duplicate_my_course(10, CourseDuplicateRequest(), teacher, db)

    assert result.id != 10
    assert result.teacher_id == 1
    assert result.name == "软件测试（副本）"
    assert result.code == "ST101-C1"
    assert result.syllabus == "第一章 基础"
    assert result.semester == "2026春"
    assert result.audit_status == "approved"

    kps = db.query(KnowledgePoint).filter(KnowledgePoint.course_id == result.id).all()
    assert len(kps) == 2
    copied_parent = next(k for k in kps if k.name == "等价类划分")
    copied_child = next(k for k in kps if k.name == "有效等价类")
    assert copied_child.parent_id == copied_parent.id
    assert copied_parent.description == "按输入域划分"

    materials = db.query(CourseMaterial).filter(
        CourseMaterial.course_id == result.id).all()
    assert len(materials) == 1
    assert materials[0].file_path == "/tmp/ch1.pdf"
    assert materials[0].chunk_count == 0

    # 学生数据不复制
    assert db.query(CourseEnrollment).filter_by(course_id=result.id).count() == 0
    assert db.query(StudentProfile).filter_by(course_id=result.id).count() == 0
    # 源课程不受影响
    assert db.query(KnowledgePoint).filter_by(course_id=10).count() == 2
    assert db.query(CourseMaterial).filter_by(course_id=10).count() == 1

    log = db.query(OperationLog).filter_by(
        action="course_duplicate", target_id=result.id).first()
    assert log is not None
    assert '"source_course_id": 10' in log.detail


def test_duplicate_allows_overrides(db):
    teacher = db.get(User, 1)
    result = duplicate_my_course(
        10,
        CourseDuplicateRequest(name="软件测试 2027", code="ST101-2027", semester="2027春"),
        teacher, db,
    )
    assert result.name == "软件测试 2027"
    assert result.code == "ST101-2027"
    assert result.semester == "2027春"


def test_duplicate_rejects_existing_code(db):
    teacher = db.get(User, 1)
    db.add(Course(id=11, teacher_id=1, name="已有课程", code="COPY1",
                  audit_status="approved"))
    db.commit()
    with pytest.raises(HTTPException) as exc:
        duplicate_my_course(10, CourseDuplicateRequest(code="COPY1"), teacher, db)
    assert exc.value.status_code == 400
    assert "课程代码已存在" in exc.value.detail


def test_duplicate_only_own_course(db):
    other = db.get(User, 2)
    with pytest.raises(HTTPException) as exc:
        duplicate_my_course(10, CourseDuplicateRequest(), other, db)
    # 不泄露他人课程是否存在
    assert exc.value.status_code == 404


def test_course_templates_counts_and_isolation(db):
    teacher = db.get(User, 1)
    items = list_course_templates(teacher, db)["items"]
    assert len(items) == 1
    assert items[0]["id"] == 10
    assert items[0]["knowledge_points"] == 2
    assert items[0]["materials"] == 1

    other = db.get(User, 2)
    assert list_course_templates(other, db)["items"] == []

    admin = db.get(User, 5)
    assert {t["id"] for t in list_course_templates(admin, db)["items"]} == {10}


def test_duplicate_unapproved_source_needs_reaudit(db):
    teacher = db.get(User, 1)
    db.add(Course(id=11, teacher_id=1, name="被驳回课程", code="REJ1",
                  audit_status="rejected"))
    db.commit()

    result = duplicate_my_course(11, CourseDuplicateRequest(), teacher, db)
    assert result.audit_status == "pending"
