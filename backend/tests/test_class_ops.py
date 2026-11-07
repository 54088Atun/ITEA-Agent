"""CL-06 班级运营:容量、批量导入、转班"""
import asyncio
import io

import pytest
from fastapi import HTTPException, UploadFile
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.classroom import (
    create_class, import_members, invite_member, transfer_member, update_class,
)
from app.db.session import Base
from app.models.classroom import ClassMember, Classroom, CourseEnrollment
from app.models.course import Course
from app.models.user import User
from app.schemas.classroom import (
    ClassCreate, ClassInviteRequest, ClassTransferRequest, ClassUpdate,
)


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
        User(id=2, role="teacher", name="其他老师", email="other@example.com",
             password_hash="x", status="active"),
        User(id=11, role="student", name="学生一", email="s1@example.com",
             password_hash="x", status="active"),
        User(id=12, role="student", name="学生二", email="s2@example.com",
             password_hash="x", status="active"),
        User(id=13, role="student", name="学生三", email="s3@example.com",
             password_hash="x", status="active"),
        Course(id=10, teacher_id=1, name="课程A", code="A101", audit_status="approved"),
        Course(id=11, teacher_id=1, name="课程B", code="B101", audit_status="approved"),
    ])
    db.commit()


def _class(db, name="班级", course_id=10, max_students=100):
    return create_class(
        ClassCreate(name=name, course_id=course_id, max_students=max_students),
        db.get(User, 1), db,
    )


def _upload(content: bytes, filename="students.csv"):
    return UploadFile(filename=filename, file=io.BytesIO(content))


def test_capacity_blocks_invite_and_join(db):
    classroom = _class(db, max_students=2)
    head = db.get(User, 1)

    invite_member(classroom.id, ClassInviteRequest(email="s1@example.com"), head, db)
    invite_member(classroom.id, ClassInviteRequest(email="s2@example.com"), head, db)

    with pytest.raises(HTTPException) as exc:
        invite_member(classroom.id, ClassInviteRequest(email="s3@example.com"), head, db)
    assert exc.value.status_code == 400
    assert "上限" in exc.value.detail

    # 学生凭码加入同样受限
    from app.api.classroom import join_class
    from app.schemas.classroom import JoinClassRequest
    with pytest.raises(HTTPException) as exc:
        join_class(JoinClassRequest(invite_code=classroom.invite_code), db.get(User, 13), db)
    assert exc.value.status_code == 400

    # 容量不能低于现有学生数
    with pytest.raises(HTTPException) as exc:
        update_class(classroom.id, ClassUpdate(max_students=1), head, db)
    assert exc.value.status_code == 400

    updated = update_class(classroom.id, ClassUpdate(max_students=3), head, db)
    assert updated.max_students == 3


def test_capacity_ignores_teacher_members(db):
    classroom = _class(db, max_students=1)
    head = db.get(User, 1)
    invite_member(
        classroom.id,
        ClassInviteRequest(email="other@example.com", role="teacher"),
        head, db,
    )
    # 任课教师不占学生容量
    invite_member(classroom.id, ClassInviteRequest(email="s1@example.com"), head, db)
    with pytest.raises(HTTPException) as exc:
        invite_member(classroom.id, ClassInviteRequest(email="s2@example.com"), head, db)
    assert exc.value.status_code == 400


def test_bulk_import_csv(db):
    classroom = _class(db, max_students=10)
    head = db.get(User, 1)
    invite_member(classroom.id, ClassInviteRequest(email="s1@example.com"), head, db)

    content = (
        "email,student_id\n"
        "s1@example.com,11\n"
        "s2@example.com,12\n"
        "missing@example.com,99\n"
        "s3@example.com,13\n"
    ).encode("utf-8")
    result = asyncio.run(import_members(classroom.id, _upload(content), head, db))
    assert result["total"] == 4
    assert result["skipped"] == 1
    assert result["imported"] == 2
    assert result["failed"] == 1
    statuses = [item["status"] for item in result["items"]]
    assert statuses == ["skipped", "imported", "failed", "imported"]


def test_bulk_import_respects_capacity(db):
    classroom = _class(db, max_students=1)
    head = db.get(User, 1)
    content = "email\ns1@example.com\ns2@example.com\n".encode("utf-8")
    result = asyncio.run(import_members(classroom.id, _upload(content), head, db))
    assert result["imported"] == 1
    assert result["failed"] == 1
    assert "上限" in result["items"][1]["message"]


def test_bulk_import_rejects_bad_file(db):
    classroom = _class(db)
    head = db.get(User, 1)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(import_members(classroom.id, _upload(b"a,b\n1,2\n", "x.txt"), head, db))
    assert exc.value.status_code == 400
    with pytest.raises(HTTPException) as exc:
        asyncio.run(import_members(classroom.id, _upload(b"name\nabc\n", "x.csv"), head, db))
    assert "缺少" in exc.value.detail


@pytest.mark.parametrize("delta,status", [(0, 200), (-1, 413)])
def test_bulk_import_enforces_actual_byte_limit(db, monkeypatch, delta, status):
    from app.core.config import settings

    classroom = _class(db)
    head = db.get(User, 1)
    content = "email,student_id\ns1@example.com,11\n".encode("utf-8")
    # 上限恰好卡在文件实际字节;比实际字节少 1 时必须拒绝且不写成员记录
    monkeypatch.setattr(settings, "CLASS_IMPORT_MAX_BYTES", len(content) + delta)

    if status == 413:
        with pytest.raises(HTTPException) as exc:
            asyncio.run(import_members(classroom.id, _upload(content), head, db))
        assert exc.value.status_code == 413
        assert db.query(ClassMember).filter_by(class_id=classroom.id).count() == 0
        return

    result = asyncio.run(import_members(classroom.id, _upload(content), head, db))
    assert result["imported"] == 1


def test_xlsx_parser(db):
    from openpyxl import Workbook
    from app.services.class_import import parse_student_rows

    wb = Workbook()
    ws = wb.active
    ws.append(["邮箱", "学号"])
    ws.append(["s1@example.com", "11"])
    buffer = io.BytesIO()
    wb.save(buffer)
    rows = parse_student_rows(buffer.getvalue(), "students.xlsx")
    assert rows == [{"row": 2, "email": "s1@example.com", "student_id": "11"}]


def test_transfer_student_between_classes(db):
    source = _class(db, name="源班", course_id=10)
    target = _class(db, name="目标班", course_id=11)
    head = db.get(User, 1)
    invite_member(source.id, ClassInviteRequest(email="s1@example.com"), head, db)

    result = transfer_member(
        source.id, 11, ClassTransferRequest(target_class_id=target.id), head, db,
    )
    assert result["status"] == "transferred"

    source_member = db.query(ClassMember).filter_by(
        class_id=source.id, student_id=11).first()
    target_member = db.query(ClassMember).filter_by(
        class_id=target.id, student_id=11).first()
    assert source_member.status == "left"
    assert target_member.status == "active"

    assert db.query(CourseEnrollment).filter_by(course_id=10, student_id=11).first() is None
    assert db.query(CourseEnrollment).filter_by(course_id=11, student_id=11).first() is not None


def test_transfer_capacity_and_ownership(db):
    source = _class(db, name="源班", course_id=10)
    full = _class(db, name="满班", course_id=11, max_students=1)
    other = _class(db, name="他人班", course_id=None)
    db.get(Classroom, other.id).teacher_id = 2
    db.commit()

    head = db.get(User, 1)
    invite_member(source.id, ClassInviteRequest(email="s1@example.com"), head, db)
    invite_member(full.id, ClassInviteRequest(email="s2@example.com"), head, db)

    with pytest.raises(HTTPException) as exc:
        transfer_member(
            source.id, 11, ClassTransferRequest(target_class_id=full.id), head, db,
        )
    assert exc.value.status_code == 400
    assert db.query(ClassMember).filter_by(
        class_id=source.id, student_id=11).first().status == "active"

    with pytest.raises(HTTPException) as exc:
        transfer_member(
            source.id, 11, ClassTransferRequest(target_class_id=other.id), head, db,
        )
    assert exc.value.status_code == 403
