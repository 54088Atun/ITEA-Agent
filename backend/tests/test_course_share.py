"""课程分享码与复制课程

覆盖:
- 只有课程归属教师可生成分享码
- 凭码复制为新课程,归属复制者,保留知识点树与素材元数据
- 不复制选课关系/学情(新课程无 enrollment)
- 过期 / 撤销 / 超次 失效;不能复制自己的课程
- 生成、撤销、复制均写操作审计
"""
from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.course_share import (
    create_share, import_course, list_shares, revoke_share,
)
from app.db.session import Base
from app.models.classroom import CourseEnrollment, CourseShare
from app.models.course import Course, CourseMaterial, KnowledgePoint
from app.models.log import OperationLog
from app.models.user import User
from app.schemas.assignment import CourseImportRequest, CourseShareCreate


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
    third = User(id=3, role="teacher", name="王老师", email="t3@example.com",
                 password_hash="x", status="active")
    student = User(id=4, role="student", name="小明", email="s1@example.com",
                   password_hash="x", status="active")
    course = Course(id=10, teacher_id=1, name="软件测试", code="ST101",
                    syllabus="第一章 基础", audit_status="approved")
    parent = KnowledgePoint(id=30, course_id=10, name="等价类划分")
    child = KnowledgePoint(id=31, course_id=10, name="有效等价类", parent_id=30)
    material = CourseMaterial(id=40, course_id=10, type="courseware",
                              title="第一章课件", file_path="/tmp/ch1.pdf",
                              chunk_count=12)
    db.add_all([teacher, other, third, student, course, parent, child, material])
    # 原课程存在学生选课关系,复制时不得带过去
    db.add(CourseEnrollment(course_id=10, student_id=4, source="class"))
    db.commit()


def test_only_owner_can_create_share(db):
    with pytest.raises(HTTPException) as exc:
        create_share(10, CourseShareCreate(), db.get(User, 2), db)
    assert exc.value.status_code == 403

    with pytest.raises(HTTPException) as exc:
        create_share(10, CourseShareCreate(), db.get(User, 4), db)
    assert exc.value.status_code == 403

    share = create_share(10, CourseShareCreate(expires_days=3, max_uses=2), db.get(User, 1), db, confirm=True)
    assert share["status"] == "active"
    assert share["max_uses"] == 2
    assert len(list_shares(10, db.get(User, 1), db)) == 1
    assert db.query(OperationLog).filter_by(action="share_create").count() == 1


def test_import_copies_snapshot_without_student_data(db):
    share = create_share(10, CourseShareCreate(), db.get(User, 1), db, confirm=True)
    result = import_course(
        CourseImportRequest(code=share["code"].lower()), db.get(User, 2), db,
    )
    assert result["source_course_id"] == 10
    assert result["knowledge_points"] == 2
    assert result["materials"] == 1

    copied = db.get(Course, result["course_id"])
    assert copied.teacher_id == 2
    assert copied.code != "ST101"
    assert copied.syllabus == "第一章 基础"

    # 知识点树与素材元数据被复制,父关系保留
    copied_kps = db.query(KnowledgePoint).filter_by(course_id=copied.id).all()
    assert len(copied_kps) == 2
    child = next(k for k in copied_kps if k.name == "有效等价类")
    assert child.parent_id is not None
    assert db.query(CourseMaterial).filter_by(course_id=copied.id).count() == 1

    # 学生数据不外泄
    assert db.query(CourseEnrollment).filter_by(course_id=copied.id).count() == 0
    assert db.query(CourseEnrollment).filter_by(course_id=10).count() == 1

    db.refresh(db.get(CourseShare, share["id"]))
    assert db.get(CourseShare, share["id"]).used_count == 1
    assert db.query(OperationLog).filter_by(action="course_import").count() == 1


def test_expired_revoked_and_exhausted_codes(db):
    share = create_share(10, CourseShareCreate(max_uses=1), db.get(User, 1), db, confirm=True)
    import_course(CourseImportRequest(code=share["code"]), db.get(User, 2), db)

    # 超次
    with pytest.raises(HTTPException) as exc:
        import_course(CourseImportRequest(code=share["code"]), db.get(User, 3), db)
    assert exc.value.status_code == 400

    # 撤销
    share2 = create_share(10, CourseShareCreate(), db.get(User, 1), db, confirm=True)
    revoke_share(share2["id"], db.get(User, 1), db, confirm=True)
    with pytest.raises(HTTPException) as exc:
        import_course(CourseImportRequest(code=share2["code"]), db.get(User, 3), db)
    assert exc.value.status_code == 400
    assert "撤销" in exc.value.detail

    # 过期
    share3 = create_share(10, CourseShareCreate(), db.get(User, 1), db, confirm=True)
    record = db.get(CourseShare, share3["id"])
    record.expires_at = datetime.utcnow() - timedelta(minutes=1)
    db.commit()
    with pytest.raises(HTTPException) as exc:
        import_course(CourseImportRequest(code=share3["code"]), db.get(User, 3), db)
    assert exc.value.status_code == 400
    assert "过期" in exc.value.detail

    # 无效码
    with pytest.raises(HTTPException) as exc:
        import_course(CourseImportRequest(code="XXXX9999"), db.get(User, 3), db)
    assert exc.value.status_code == 404


def test_cannot_import_own_course_and_only_owner_can_revoke(db):
    share = create_share(10, CourseShareCreate(), db.get(User, 1), db, confirm=True)
    with pytest.raises(HTTPException) as exc:
        import_course(CourseImportRequest(code=share["code"]), db.get(User, 1), db)
    assert exc.value.status_code == 400

    with pytest.raises(HTTPException) as exc:
        revoke_share(share["id"], db.get(User, 2), db)
    assert exc.value.status_code == 403
