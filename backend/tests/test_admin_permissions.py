import inspect
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api import admin as admin_api
from app.core.deps import (
    admin_level_of,
    require_admin,
    require_admin_write,
    require_super_admin,
)
from app.models.user import User
from app.schemas.admin import (
    AdminLevelUpdate,
    PasswordReset,
    UserCreate,
    UserStatusUpdate,
    UserUpdate,
)


def _admin_dependency(endpoint):
    return inspect.signature(endpoint).parameters["admin"].default.dependency


def _user(user_id=1, role="admin", admin_level="super", status="active"):
    return User(
        id=user_id,
        role=role,
        admin_level=admin_level,
        name=f"user-{user_id}",
        email=f"user-{user_id}@example.com",
        password_hash="hash",
        status=status,
    )


@pytest.mark.parametrize(
    "endpoint",
    [
        admin_api.create_user,
        admin_api.update_user,
        admin_api.update_user_status,
        admin_api.reset_password,
        admin_api.audit_course,
        admin_api.delete_material,
        admin_api.update_config,
        admin_api.admin_create_course,
        admin_api.admin_update_course,
        admin_api.admin_delete_course,
        admin_api.admin_upload_material,
        admin_api.admin_export,
        admin_api.admin_interview_start,
        admin_api.batch_update_user_status,
        admin_api.batch_audit_courses,
    ],
)
def test_business_writes_require_admin_write(endpoint):
    assert _admin_dependency(endpoint) is require_admin_write


def test_read_only_generation_keeps_admin_permission():
    assert _admin_dependency(admin_api.admin_lesson_plan) is require_admin


def test_admin_level_update_route_exists_and_is_super_only():
    endpoint = getattr(admin_api, "update_admin_level", None)
    assert callable(endpoint)
    assert _admin_dependency(endpoint) is require_super_admin
    assert any(
        route.path == "/admin/users/{user_id}/admin-level"
        and "PATCH" in route.methods
        and route.endpoint is endpoint
        for route in admin_api.router.routes
    )


def test_admin_level_dependencies():
    assert admin_level_of(SimpleNamespace(admin_level=None)) == "super"
    with pytest.raises(HTTPException) as exc_info:
        require_admin_write(_user(admin_level="observer"))
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "观察者仅可查看"
    assert require_admin_write(_user(admin_level="normal")).admin_level == "normal"
    with pytest.raises(HTTPException) as exc_info:
        require_super_admin(_user(admin_level="normal"))
    assert exc_info.value.status_code == 403


def test_admin_level_update_rejects_non_admin_before_commit():
    endpoint = getattr(admin_api, "update_admin_level", None)
    assert callable(endpoint)
    target = _user(user_id=2, role="teacher", admin_level=None)
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = target

    with pytest.raises(HTTPException) as exc_info:
        endpoint(2, AdminLevelUpdate(admin_level="normal"), MagicMock(), _user(), db)

    assert exc_info.value.status_code == 400
    db.commit.assert_not_called()


def test_admin_level_update_rejects_self_demotion_before_commit():
    endpoint = getattr(admin_api, "update_admin_level", None)
    assert callable(endpoint)
    current = _user(user_id=1, admin_level="super")
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = current

    with pytest.raises(HTTPException) as exc_info:
        endpoint(1, AdminLevelUpdate(admin_level="normal"), MagicMock(), current, db)

    assert exc_info.value.status_code == 400
    db.commit.assert_not_called()


def test_admin_level_update_preserves_another_active_super():
    endpoint = getattr(admin_api, "update_admin_level", None)
    assert callable(endpoint)
    target = _user(user_id=2, admin_level="super")
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = target
    db.query.return_value.filter.return_value.order_by.return_value.with_for_update.return_value.all.return_value = [target]

    with pytest.raises(HTTPException) as exc_info:
        endpoint(2, AdminLevelUpdate(admin_level="observer"), MagicMock(), _user(), db)

    assert exc_info.value.status_code == 400
    db.commit.assert_not_called()


def test_admin_level_update_persists_and_audits(monkeypatch):
    endpoint = getattr(admin_api, "update_admin_level", None)
    assert callable(endpoint)
    current = _user(user_id=1, admin_level="super")
    target = _user(user_id=2, admin_level="normal")
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = target
    audit = MagicMock()
    monkeypatch.setattr(admin_api, "_audit", audit)

    result = endpoint(
        2, AdminLevelUpdate(admin_level="observer"), MagicMock(), current, db
    )

    assert target.admin_level == "observer"
    assert result.admin_level == "observer"
    db.commit.assert_called_once_with()
    assert audit.call_args.args[3] == "update_admin_level"


@pytest.mark.parametrize("role", ["teacher", "student"])
def test_normal_admin_can_create_regular_users(role, monkeypatch):
    current = _user(admin_level="normal")
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None
    db.refresh.side_effect = lambda user: setattr(user, "id", 100)
    monkeypatch.setattr(admin_api, "hash_password", lambda _: "hash")
    monkeypatch.setattr(admin_api, "_audit", MagicMock())

    result = admin_api.create_user(
        UserCreate(
            role=role,
            name="普通用户",
            email="regular@example.com",
            password="secret123",
        ),
        MagicMock(),
        current,
        db,
    )

    assert result.role == role
    assert result.admin_level is None
    db.commit.assert_called_once_with()


def test_normal_admin_cannot_create_admin_before_commit():
    current = _user(admin_level="normal")
    db = MagicMock()

    with pytest.raises(HTTPException) as exc_info:
        admin_api.create_user(
            UserCreate(
                role="admin",
                name="越权管理员",
                email="new-admin@example.com",
                password="secret123",
            ),
            MagicMock(),
            current,
            db,
        )

    assert exc_info.value.status_code == 403
    db.commit.assert_not_called()


@pytest.mark.parametrize("role", ["teacher", "student"])
def test_normal_admin_can_edit_regular_users(role, monkeypatch):
    current = _user(admin_level="normal")
    target = _user(user_id=2, role=role, admin_level=None)
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = target
    monkeypatch.setattr(admin_api, "_audit", MagicMock())

    result = admin_api.update_user(
        2, UserUpdate(name="已编辑"), MagicMock(), current, db
    )

    assert result.name == "已编辑"
    db.commit.assert_called_once_with()


@pytest.mark.parametrize("role", ["teacher", "student"])
def test_normal_admin_can_update_regular_user_status(role, monkeypatch):
    current = _user(admin_level="normal")
    target = _user(user_id=2, role=role, admin_level=None)
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = target
    monkeypatch.setattr(admin_api, "_audit", MagicMock())

    result = admin_api.update_user_status(
        2, UserStatusUpdate(status="disabled"), MagicMock(), current, db
    )

    assert result.status == "disabled"
    db.commit.assert_called_once_with()


@pytest.mark.parametrize("role", ["teacher", "student"])
def test_normal_admin_can_reset_regular_user_password(role, monkeypatch):
    current = _user(admin_level="normal")
    target = _user(user_id=2, role=role, admin_level=None)
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = target
    monkeypatch.setattr(admin_api, "hash_password", lambda _: "new-hash")
    monkeypatch.setattr(admin_api, "_audit", MagicMock())

    admin_api.reset_password(
        2, PasswordReset(new_password="new-secret"), MagicMock(), current, db
    )

    assert target.password_hash == "new-hash"
    db.commit.assert_called_once_with()


@pytest.mark.parametrize(
    "endpoint, req",
    [
        (admin_api.update_user, UserUpdate(name="越权编辑")),
        (admin_api.update_user_status, UserStatusUpdate(status="disabled")),
        (admin_api.reset_password, PasswordReset(new_password="new-secret")),
    ],
)
def test_normal_admin_cannot_manage_admin_accounts_before_commit(endpoint, req):
    current = _user(admin_level="normal")
    target = _user(user_id=2, admin_level="normal")
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = target

    with pytest.raises(HTTPException) as exc_info:
        endpoint(2, req, MagicMock(), current, db)

    assert exc_info.value.status_code == 403
    db.commit.assert_not_called()


def test_update_user_rejects_own_role_change_before_commit():
    current = _user(user_id=1, admin_level="super")
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = current

    with pytest.raises(HTTPException) as exc_info:
        admin_api.update_user(
            1, UserUpdate(role="teacher"), MagicMock(), current, db
        )

    assert exc_info.value.status_code == 400
    db.commit.assert_not_called()


def test_update_user_promotion_defaults_to_normal_admin(monkeypatch):
    current = _user(user_id=1, admin_level="super")
    target = _user(user_id=2, role="teacher", admin_level=None)
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = target
    monkeypatch.setattr(admin_api, "_audit", MagicMock())

    result = admin_api.update_user(
        2, UserUpdate(role="admin"), MagicMock(), current, db
    )

    assert result.role == "admin"
    assert result.admin_level == "normal"
    db.commit.assert_called_once_with()


def test_update_user_demotion_clears_admin_level(monkeypatch):
    current = _user(user_id=1, admin_level="super")
    target = _user(user_id=2, admin_level="normal")
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = target
    monkeypatch.setattr(admin_api, "_audit", MagicMock())

    result = admin_api.update_user(
        2, UserUpdate(role="teacher"), MagicMock(), current, db
    )

    assert result.role == "teacher"
    assert result.admin_level is None
    db.commit.assert_called_once_with()


def test_update_user_rejects_demoting_last_active_super_before_commit():
    current = _user(user_id=1, admin_level="super")
    target = _user(user_id=2, admin_level="super")
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = target
    db.query.return_value.filter.return_value.order_by.return_value.with_for_update.return_value.all.return_value = [target]

    with pytest.raises(HTTPException) as exc_info:
        admin_api.update_user(
            2, UserUpdate(role="teacher"), MagicMock(), current, db
        )

    assert exc_info.value.status_code == 400
    db.commit.assert_not_called()


def test_update_user_status_rejects_disabling_last_active_super_before_commit():
    current = _user(user_id=1, admin_level="super")
    target = _user(user_id=2, admin_level="super")
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = target
    db.query.return_value.filter.return_value.order_by.return_value.with_for_update.return_value.all.return_value = [target]

    with pytest.raises(HTTPException) as exc_info:
        admin_api.update_user_status(
            2, UserStatusUpdate(status="disabled"), MagicMock(), current, db
        )

    assert exc_info.value.status_code == 400
    db.commit.assert_not_called()


@pytest.mark.parametrize(
    "endpoint, req",
    [
        (admin_api.update_user, UserUpdate(role="teacher")),
        (admin_api.update_user_status, UserStatusUpdate(status="disabled")),
        (admin_api.update_admin_level, AdminLevelUpdate(admin_level="normal")),
    ],
)
def test_super_survival_locks_all_admins_in_id_order(endpoint, req):
    current = _user(user_id=1, admin_level="super")
    target = _user(user_id=2, admin_level="super")
    db = MagicMock()
    filtered = db.query.return_value.filter.return_value
    filtered.first.return_value = target
    filtered.order_by.return_value.with_for_update.return_value.all.return_value = [target]

    with pytest.raises(HTTPException) as exc_info:
        endpoint(2, req, MagicMock(), current, db)

    assert exc_info.value.status_code == 400
    filtered.order_by.assert_called_once_with(User.id)
    filtered.order_by.return_value.with_for_update.assert_called_once_with()
    db.commit.assert_not_called()


@pytest.mark.parametrize(
    "endpoint, req, target",
    [
        (admin_api.update_user, UserUpdate(name="审计失败"), _user(user_id=2, role="teacher", admin_level=None)),
        (admin_api.update_user_status, UserStatusUpdate(status="disabled"), _user(user_id=2, role="teacher", admin_level=None)),
        (admin_api.reset_password, PasswordReset(new_password="new-secret"), _user(user_id=2, role="teacher", admin_level=None)),
        (admin_api.update_admin_level, AdminLevelUpdate(admin_level="observer"), _user(user_id=2, admin_level="normal")),
    ],
)
def test_account_change_audit_failure_rolls_back_before_commit(
    endpoint, req, target, monkeypatch
):
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = target
    monkeypatch.setattr(admin_api, "hash_password", lambda _: "new-hash")
    monkeypatch.setattr(admin_api, "_audit", MagicMock(return_value=None))

    with pytest.raises(HTTPException) as exc_info:
        endpoint(2, req, MagicMock(), _user(), db)

    assert exc_info.value.status_code == 500
    db.commit.assert_not_called()
    db.rollback.assert_called_once_with()


def test_create_user_audit_failure_rolls_back_real_transaction(monkeypatch):
    engine = create_engine(
        "sqlite:///:memory:",
        poolclass=StaticPool,
    )
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql(
                "CREATE TABLE users ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "role VARCHAR(20) NOT NULL, admin_level VARCHAR(20), "
                "name VARCHAR(50) NOT NULL, email VARCHAR(100) NOT NULL UNIQUE, "
                "avatar_url VARCHAR(255), "
                "password_hash VARCHAR(255) NOT NULL, "
                "status VARCHAR(20) NOT NULL, "
                "token_version INTEGER NOT NULL DEFAULT 0, "
                "email_verified_at DATETIME, created_at DATETIME)"
            )
        monkeypatch.setattr(admin_api, "hash_password", lambda _: "hash")
        monkeypatch.setattr(admin_api, "_audit", MagicMock(return_value=None))

        with Session(bind=engine) as db:
            with pytest.raises(HTTPException) as exc_info:
                admin_api.create_user(
                    UserCreate(
                        role="teacher",
                        name="审计回滚",
                        email="audit-rollback@example.com",
                        password="secret123",
                    ),
                    MagicMock(),
                    _user(),
                    db,
                )
            assert exc_info.value.status_code == 500

        with Session(bind=engine) as db:
            assert db.query(User).count() == 0
    finally:
        engine.dispose()


def test_create_user_flushes_and_audits_before_commit(monkeypatch):
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None

    def assign_id():
        db.add.call_args.args[0].id = 100

    def audit(*args, **kwargs):
        db.commit.assert_not_called()
        assert args[5] == 100
        assert kwargs["commit"] is False
        return MagicMock()

    db.flush.side_effect = assign_id
    monkeypatch.setattr(admin_api, "hash_password", lambda _: "hash")
    monkeypatch.setattr(admin_api, "_audit", audit)

    admin_api.create_user(
        UserCreate(
            role="teacher",
            name="同事务审计",
            email="audit-transaction@example.com",
            password="secret123",
        ),
        MagicMock(),
        _user(),
        db,
    )

    db.flush.assert_called_once_with()
    db.commit.assert_called_once_with()
