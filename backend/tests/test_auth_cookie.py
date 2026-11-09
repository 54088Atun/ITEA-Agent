# -*- coding: utf-8 -*-
"""静态文件鉴权:登录写入 HttpOnly Cookie,verify 供 nginx auth_request 校验"""
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.responses import Response

from app.api.auth import AUTH_COOKIE, login, logout, register, verify
from app.core.security import create_access_token, hash_password
from app.db.session import Base
from app.models.user import User
from app.schemas.auth import LoginRequest, RegisterRequest

PASSWORD = "Test@123456"


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
        User(id=2, role="student", name="小明", email="s1@example.com",
             password_hash=pwd, status="active"),
        User(id=3, role="student", name="停用", email="s2@example.com",
             password_hash=pwd, status="disabled"),
    ])
    session.commit()
    yield session
    session.close()
    engine.dispose()


def _request(cookie: str | None = None, authorization: str | None = None):
    headers = {}
    if authorization:
        headers["authorization"] = authorization
    cookies = {AUTH_COOKIE: cookie} if cookie else {}
    return SimpleNamespace(cookies=cookies, headers=headers)


def test_login_sets_auth_cookie(db):
    response = Response()
    payload = login(
        LoginRequest(email="s1@example.com", password=PASSWORD), response, db,
    )
    cookie = response.headers.get("set-cookie", "")
    assert payload.access_token
    assert AUTH_COOKIE in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie
    assert "Path=/" in cookie


def test_register_sets_auth_cookie(db):
    response = Response()
    payload = register(
        RegisterRequest(
            email="new@example.com", password=PASSWORD, name="新同学", role="student",
        ),
        response, db,
    )
    assert payload.access_token
    assert AUTH_COOKIE in response.headers.get("set-cookie", "")


def test_register_rejects_teacher_self_signup(db):
    response = Response()
    with pytest.raises(HTTPException) as exc:
        register(
            RegisterRequest(
                email="teacher2@example.com", password=PASSWORD,
                name="张老师", role="teacher",
            ),
            response, db,
        )
    assert exc.value.status_code == 403
    assert "管理员开通" in exc.value.detail


def test_logout_clears_auth_cookie():
    response = Response()
    assert logout(response) == {"ok": True}
    cookie = response.headers.get("set-cookie", "")
    assert AUTH_COOKIE in cookie
    assert "Max-Age=0" in cookie


def test_verify_accepts_cookie_and_bearer(db):
    user = db.get(User, 2)
    token = create_access_token(user.id, user.role, int(user.token_version or 0))
    assert verify(_request(cookie=token), db)["ok"] is True
    assert verify(_request(authorization=f"Bearer {token}"), db)["ok"] is True


def test_verify_rejects_missing_or_invalid_token(db):
    with pytest.raises(HTTPException) as exc:
        verify(_request(), db)
    assert exc.value.status_code == 401

    with pytest.raises(HTTPException) as exc:
        verify(_request(cookie="not-a-jwt"), db)
    assert exc.value.status_code == 401


def test_verify_rejects_stale_version_and_disabled_user(db):
    user = db.get(User, 2)
    stale = create_access_token(user.id, user.role, int(user.token_version or 0) + 1)
    with pytest.raises(HTTPException) as exc:
        verify(_request(cookie=stale), db)
    assert exc.value.status_code == 401

    disabled = db.get(User, 3)
    token = create_access_token(
        disabled.id, disabled.role, int(disabled.token_version or 0),
    )
    with pytest.raises(HTTPException) as exc:
        verify(_request(cookie=token), db)
    assert exc.value.status_code == 403
