# -*- coding: utf-8 -*-
"""邮箱验证:发码、注册、激活、找回密码、限流与安全约束"""
from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.responses import Response

from app.api import auth as auth_api
from app.core.config import Settings, settings
from app.core.security import hash_password, verify_password
from app.db import session as db_session
from app.db.session import Base
from app import models  # noqa: F401 - 注册全部表,供迁移用例建库
from app.models.email_verification import EmailVerificationCode
from app.models.user import User
from app.schemas.auth import (
    EmailCodeRequest, EmailVerifyRequest, LoginRequest, PasswordResetRequest,
    RegisterRequest,
)
from app.services import email_verification as ev
from app.services.mailer import MailSendError

PASSWORD = "Abcd1234"
NEW_PASSWORD = "Newpass123"
VERIFIED_EMAIL = "verified@example.com"
UNVERIFIED_EMAIL = "unverified@example.com"


@pytest.fixture(autouse=True)
def _enable_email_verification(monkeypatch):
    """本模块显式开启邮箱验证(conftest 默认关闭)"""
    monkeypatch.setattr(auth_api, "email_verification_required", lambda: True)
    ev._dev_codes.clear()
    yield
    ev._dev_codes.clear()


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    pwd = hash_password(PASSWORD)
    session.add_all([
        User(id=1, role="student", name="已验证", email=VERIFIED_EMAIL,
             password_hash=pwd, status="active", email_verified_at=None),
        User(id=2, role="student", name="未验证", email=UNVERIFIED_EMAIL,
             password_hash=pwd, status="active", email_verified_at=None),
    ])
    # 1 号用户视为历史已验证账号
    session.query(User).filter(User.id == 1).update(
        {User.email_verified_at: datetime.utcnow()},
    )
    session.commit()
    yield session
    session.close()
    engine.dispose()


def _send(db, email: str, purpose: str):
    return auth_api.send_email_code(
        EmailCodeRequest(email=email, purpose=purpose), db,
    )


# ---------- 发码 ----------

def test_send_code_rejects_verified_email(db):
    with pytest.raises(HTTPException) as exc:
        _send(db, VERIFIED_EMAIL, "register")
    assert exc.value.status_code == 409


def test_send_code_enforces_register_domain(db, monkeypatch):
    monkeypatch.setattr(settings, "REGISTER_EMAIL_DOMAINS", "campus.edu.cn")
    with pytest.raises(HTTPException) as exc:
        _send(db, "someone@other.com", "register")
    assert exc.value.status_code == 403


def test_send_code_has_cooldown_and_hourly_limit(db, monkeypatch):
    monkeypatch.setattr(settings, "EMAIL_CODE_RESEND_SECONDS", 0)
    monkeypatch.setattr(settings, "EMAIL_CODE_MAX_PER_HOUR_EMAIL", 1)
    monkeypatch.setattr(settings, "EMAIL_CODE_MAX_PER_HOUR_IP", 0)

    _send(db, "quota@example.com", "register")
    with pytest.raises(HTTPException) as exc:
        _send(db, "quota@example.com", "register")
    assert exc.value.status_code == 429


def test_send_code_mail_failure_returns_502(db, monkeypatch):
    def _boom(*args, **kwargs):
        raise MailSendError("gateway")

    monkeypatch.setattr(ev, "send_verification_code", _boom)
    with pytest.raises(HTTPException) as exc:
        _send(db, "mailfail@example.com", "register")
    assert exc.value.status_code == 502
    # 发信失败必须作废该码,避免占用冷却时间
    row = db.query(EmailVerificationCode).one()
    assert row.consumed_at is not None


def test_code_is_hashed_and_not_returned(db):
    response = _send(db, "hash@example.com", "register")
    code = ev.latest_dev_code("hash@example.com", "register")
    assert code and len(code) == 6
    assert code not in str(response)

    row = db.query(EmailVerificationCode).one()
    assert row.code_hash != code
    assert len(row.code_hash) == 64


# ---------- 注册 ----------

def _register(db, email: str, code: str):
    return auth_api.register(
        RegisterRequest(
            role="student", name="新同学", email=email,
            password=PASSWORD, email_code=code,
        ),
        Response(), db,
    )


def test_register_requires_email_code(db):
    with pytest.raises(HTTPException) as exc:
        _register(db, "nocode@example.com", "")
    assert exc.value.status_code == 400
    assert "邮箱验证码" in exc.value.detail


def test_register_rejects_wrong_and_replayed_code(db):
    _send(db, "new@example.com", "register")
    code = ev.latest_dev_code("new@example.com", "register")

    with pytest.raises(HTTPException) as exc:
        _register(db, "new@example.com", "000000" if code != "000000" else "111111")
    assert exc.value.status_code == 400

    payload = _register(db, "new@example.com", code)
    assert payload.access_token
    user = db.query(User).filter(User.email == "new@example.com").one()
    assert user.email_verified_at is not None

    # 已消费的码不可重放
    with pytest.raises(HTTPException) as exc:
        ev.consume_code(db, "new@example.com", "register", code)
    assert exc.value.status_code == 400


def test_expired_code_is_rejected(db, monkeypatch):
    _send(db, "expired@example.com", "register")
    code = ev.latest_dev_code("expired@example.com", "register")

    db.query(EmailVerificationCode).update(
        {EmailVerificationCode.expires_at: datetime.utcnow() - timedelta(seconds=1)},
    )
    db.commit()

    with pytest.raises(HTTPException) as exc:
        _register(db, "expired@example.com", code)
    assert exc.value.status_code == 400


def test_code_attempts_are_limited(db, monkeypatch):
    monkeypatch.setattr(settings, "EMAIL_CODE_MAX_ATTEMPTS", 2)
    _send(db, "brute@example.com", "register")
    code = ev.latest_dev_code("brute@example.com", "register")
    wrong = "000000" if code != "000000" else "111111"

    for _ in range(2):
        with pytest.raises(HTTPException):
            ev.consume_code(db, "brute@example.com", "register", wrong)

    # 错误次数达到上限后,正确码也一并作废
    with pytest.raises(HTTPException):
        ev.consume_code(db, "brute@example.com", "register", code)


# ---------- 登录拦截与激活 ----------

def test_login_blocks_unverified_email(db):
    with pytest.raises(HTTPException) as exc:
        auth_api.login(
            LoginRequest(email=UNVERIFIED_EMAIL, password=PASSWORD), Response(), db,
        )
    assert exc.value.status_code == 403
    assert exc.value.headers.get("X-Error-Code") == "email_unverified"


def test_verify_email_activates_and_logs_in(db):
    _send(db, UNVERIFIED_EMAIL, "register")
    code = ev.latest_dev_code(UNVERIFIED_EMAIL, "register")

    payload = auth_api.verify_email(
        EmailVerifyRequest(email=UNVERIFIED_EMAIL, code=code), Response(), db,
    )
    assert payload.access_token

    db.expire_all()
    user = db.query(User).filter(User.email == UNVERIFIED_EMAIL).one()
    assert user.email_verified_at is not None

    login_payload = auth_api.login(
        LoginRequest(email=UNVERIFIED_EMAIL, password=PASSWORD), Response(), db,
    )
    assert login_payload.access_token


# ---------- 找回密码 ----------

def test_reset_password_invalidates_old_sessions(db):
    _send(db, VERIFIED_EMAIL, "reset_password")
    code = ev.latest_dev_code(VERIFIED_EMAIL, "reset_password")

    assert auth_api.reset_password(
        PasswordResetRequest(
            email=VERIFIED_EMAIL, code=code, new_password=NEW_PASSWORD,
        ),
        db,
    ) == {"ok": True}

    db.expire_all()
    user = db.query(User).filter(User.email == VERIFIED_EMAIL).one()
    assert verify_password(NEW_PASSWORD, user.password_hash)
    assert int(user.token_version or 0) >= 1

    with pytest.raises(HTTPException) as exc:
        auth_api.login(
            LoginRequest(email=VERIFIED_EMAIL, password=PASSWORD), Response(), db,
        )
    assert exc.value.status_code == 401

    assert auth_api.login(
        LoginRequest(email=VERIFIED_EMAIL, password=NEW_PASSWORD), Response(), db,
    ).access_token


def test_reset_password_wrong_code_rejected(db):
    _send(db, VERIFIED_EMAIL, "reset_password")
    code = ev.latest_dev_code(VERIFIED_EMAIL, "reset_password")
    wrong = "000000" if code != "000000" else "111111"
    with pytest.raises(HTTPException) as exc:
        auth_api.reset_password(
            PasswordResetRequest(
                email=VERIFIED_EMAIL, code=wrong, new_password=NEW_PASSWORD,
            ),
            db,
        )
    assert exc.value.status_code == 400


def test_reset_password_does_not_leak_unknown_email(db):
    response = _send(db, "missing@example.com", "reset_password")
    assert response["ok"] is True
    assert db.query(EmailVerificationCode).count() == 0


# ---------- 存量兼容 ----------

def test_sqlite_migration_backfills_existing_users(monkeypatch, tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'migrate.db'}")
    Base.metadata.create_all(engine)
    try:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE users DROP COLUMN email_verified_at"))
    except Exception:  # noqa: BLE001 - 旧版 SQLite 不支持 DROP COLUMN 时跳过
        engine.dispose()
        pytest.skip("当前 SQLite 不支持 DROP COLUMN")

    # 列已被删除,只能用原生 SQL 造一条存量用户
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO users (role, name, email, password_hash, status, token_version)"
            " VALUES ('student', '老用户', 'legacy@example.com', :pwd, 'active', 0)"
        ), {"pwd": hash_password(PASSWORD)})

    monkeypatch.setattr(db_session, "engine", engine)
    db_session._migrate_sqlite_columns()

    Session = sessionmaker(bind=engine)
    session = Session()
    legacy = session.query(User).filter(User.email == "legacy@example.com").one()
    assert legacy.email_verified_at is not None
    session.close()
    engine.dispose()


# ---------- 生产配置校验 ----------

def test_production_requires_mail_configuration():
    with pytest.raises(RuntimeError) as exc:
        Settings(
            _env_file=None,
            ENVIRONMENT="production",
            SECRET_KEY="prod-only-secret-key-for-mail-check",
            DATABASE_URL="mysql+pymysql://itea:pass@db.internal:3306/itea",
            REQUIRE_EMAIL_VERIFICATION=True,
            MAIL_PROVIDER="none",
        )
    assert "MAIL_PROVIDER" in str(exc.value)
