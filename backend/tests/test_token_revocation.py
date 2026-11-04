"""令牌版本:改密、退出全部设备、管理员重置/禁用后旧 JWT 立即失效

对应需求 NF-01(权限变更即时生效)与 PC-08(改密后旧 token 失效)
"""
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.admin import reset_password, update_user_status
from app.api.me import PasswordChange, change_password, logout_all_devices
from app.core.deps import get_current_user
from app.core.security import create_access_token, hash_password
from app.db.session import Base
from app.models.user import User
from app.schemas.admin import PasswordReset, UserStatusUpdate

PASSWORD = "Test@123456"
NEW_PASSWORD = "New@123456"


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    pwd = hash_password(PASSWORD)
    session.add_all([
        User(id=1, role="teacher", name="张老师", email="t1@example.com",
             password_hash=pwd, status="active"),
        User(id=3, role="student", name="小明", email="s1@example.com",
             password_hash=pwd, status="active"),
        User(id=5, role="admin", name="管理员", email="a@example.com",
             password_hash=pwd, status="active", admin_level="super"),
    ])
    session.commit()
    yield session
    session.close()
    engine.dispose()


def _token(user: User) -> str:
    return create_access_token(user.id, user.role, int(user.token_version or 0))


def _request():
    return SimpleNamespace(
        headers={}, client=SimpleNamespace(host="127.0.0.1"),
    )


def test_change_password_revokes_old_token(db):
    user = db.get(User, 3)
    token = _token(user)
    assert get_current_user(token, db).id == user.id

    change_password(
        PasswordChange(old_password=PASSWORD, new_password=NEW_PASSWORD), user, db,
    )

    with pytest.raises(HTTPException) as exc:
        get_current_user(token, db)
    assert exc.value.status_code == 401
    assert "重新登录" in exc.value.detail

    fresh = db.get(User, 3)
    assert get_current_user(_token(fresh), db).id == user.id


def test_logout_all_devices_revokes_old_token(db):
    user = db.get(User, 3)
    token = _token(user)

    logout_all_devices(user, db)

    with pytest.raises(HTTPException) as exc:
        get_current_user(token, db)
    assert exc.value.status_code == 401


def test_admin_password_reset_revokes_target_token(db):
    admin = db.get(User, 5)
    target = db.get(User, 3)
    token = _token(target)

    reset_password(
        target.id, PasswordReset(new_password=NEW_PASSWORD), _request(), admin, db,
    )

    with pytest.raises(HTTPException) as exc:
        get_current_user(token, db)
    assert exc.value.status_code == 401


def test_disable_account_revokes_old_token(db):
    admin = db.get(User, 5)
    target = db.get(User, 3)
    token = _token(target)

    update_user_status(
        target.id, UserStatusUpdate(status="disabled"), _request(), admin, db,
    )

    with pytest.raises(HTTPException) as exc:
        get_current_user(token, db)
    assert exc.value.status_code in (401, 403)
