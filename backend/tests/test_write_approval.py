"""写操作审批与审计(AG-07)

覆盖:
- 写操作目录覆盖三级审批,且每个操作声明目标类型与可用角色
- manual 操作未确认:返回 428,状态不变,写入 blocked 审计
- manual 操作确认后执行:写入 executed 审计
- auto/full 操作无需二次确认但必须留痕
- 非授权角色被拒绝
- 审计查询按用户隔离,管理员可查看全部
"""
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.approvals import list_logs
from app.api.assignments import create_assignment, publish_assignment
from app.db.session import Base
from app.models.assignment import Assignment
from app.models.course import Course
from app.models.log import WriteAuditLog
from app.models.user import User
from app.schemas.assignment import AssignmentCreate
from app.services.write_approval import (
    ACTIONS, action_catalog, authorize_write, record_executed,
)


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add_all([
        User(id=1, role="teacher", name="张老师", email="t1@example.com",
             password_hash="x", status="active"),
        User(id=2, role="student", name="小明", email="s1@example.com",
             password_hash="x", status="active"),
        User(id=3, role="admin", name="管理员", email="a1@example.com",
             password_hash="x", status="active"),
        Course(id=10, teacher_id=1, name="软件测试", code="ST101",
               audit_status="approved"),
    ])
    session.commit()
    yield session
    session.close()
    engine.dispose()


def _draft(db) -> Assignment:
    data = create_assignment(
        AssignmentCreate(title="审批测试作业", course_id=10, publish=False),
        db.get(User, 1), db,
    )
    return db.get(Assignment, data["id"])


def test_catalog_covers_three_levels():
    catalog = action_catalog()
    levels = {item["level"] for item in catalog}
    assert levels == {"full", "auto", "manual"}
    assert len(catalog) == len(ACTIONS)
    manual = next(item for item in catalog if item["key"] == "assignment.publish")
    assert manual["level"] == "manual"
    assert manual["level_label"] == "敏感"
    assert manual["roles"] == ["teacher", "admin"]


def test_manual_action_requires_confirmation_and_logs_blocked(db):
    assignment = _draft(db)
    with pytest.raises(HTTPException) as exc:
        publish_assignment(assignment.id, db.get(User, 1), db)
    assert exc.value.status_code == 428
    assert exc.value.detail["code"] == "confirmation_required"
    assert exc.value.detail["action"] == "assignment.publish"

    db.refresh(assignment)
    assert assignment.status == "draft"
    record = db.query(WriteAuditLog).filter_by(status="blocked").one()
    assert record.user_id == 1
    assert record.approval_mode == "manual"
    assert record.action == "assignment.publish"


def test_confirmed_manual_action_executes_and_logs(db):
    assignment = _draft(db)
    result = publish_assignment(assignment.id, db.get(User, 1), db, confirm=True)
    assert result["status"] == "published"

    record = db.query(WriteAuditLog).filter_by(status="executed").one()
    assert record.user_id == 1
    assert record.action == "assignment.publish"
    assert record.target_type == "assignment"
    assert record.target_id == assignment.id
    assert record.detail and "published" in record.detail


def test_auto_and_full_actions_need_no_confirmation_but_are_logged(db):
    teacher = db.get(User, 1)
    auto = authorize_write(
        db, teacher, "exam.question_adopt", target_id=9, detail={"selected": 2},
    )
    assert auto.level == "auto"
    record_executed(db, teacher, auto, target_id=9, detail={"created": 2})
    db.commit()

    full = authorize_write(
        db, teacher, "assignment.ai_grade", target_id=88,
    )
    assert full.level == "full"
    record_executed(db, teacher, full, target_id=88, detail={"ai_score": 80})
    db.commit()

    rows = db.query(WriteAuditLog).all()
    assert {r.approval_mode for r in rows} == {"auto", "full"}
    assert all(r.status == "executed" for r in rows)


def test_role_without_permission_is_rejected(db):
    with pytest.raises(HTTPException) as exc:
        authorize_write(db, db.get(User, 2), "assignment.publish", confirmed=True)
    assert exc.value.status_code == 403
    assert db.query(WriteAuditLog).count() == 0


def test_audit_logs_scoped_to_owner_and_admin(db):
    assignment = _draft(db)
    publish_assignment(assignment.id, db.get(User, 1), db, confirm=True)

    mine = list_logs(page=1, size=20, scope="me", user=db.get(User, 1), db=db)
    assert mine["total"] == 1
    assert mine["items"][0]["action_label"] == "发布作业"

    with pytest.raises(HTTPException) as exc:
        list_logs(page=1, size=20, scope="all", user=db.get(User, 2), db=db)
    assert exc.value.status_code == 403

    everything = list_logs(
        page=1, size=20, scope="all", user=db.get(User, 3), db=db,
    )
    assert everything["total"] == 1
    assert everything["items"][0]["user_name"] == "张老师"
