"""图形验证码:生成、一次性校验、过期与登录/注册接入"""
import time

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.responses import Response

from app.api import auth as auth_api
from app.core.config import settings
from app.core.security import hash_password
from app.db.session import Base
from app.models.user import User
from app.schemas.auth import LoginRequest, RegisterRequest
from app.services import captcha as captcha_service


@pytest.fixture(autouse=True)
def _clean_captcha_store():
    captcha_service._store.clear()
    captcha_service._generate_count = 0
    yield
    captcha_service._store.clear()
    captcha_service._generate_count = 0


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add(User(
        id=1, role="student", name="验证码用户", email="captcha@example.com",
        password_hash=hash_password("Abcd1234"), status="active",
    ))
    session.commit()
    yield session
    session.close()
    engine.dispose()


def test_generate_and_verify_once():
    data = captcha_service.generate_captcha()

    assert data["captcha_id"]
    assert data["image"].startswith("data:image/png;base64,")
    assert data["expires_in"] == settings.CAPTCHA_TTL_SECONDS

    code = captcha_service._store[data["captcha_id"]][0]
    assert captcha_service.verify_captcha(data["captcha_id"], code.lower()) is True
    # 一次性:同一 ID 不能再次通过
    assert captcha_service.verify_captcha(data["captcha_id"], code) is False


def test_wrong_code_and_unknown_id_fail():
    data = captcha_service.generate_captcha()
    code = captcha_service._store[data["captcha_id"]][0]
    wrong = "AAAA" if code != "AAAA" else "BBBB"

    assert captcha_service.verify_captcha(data["captcha_id"], wrong) is False
    assert captcha_service.verify_captcha("missing-id", "ABCD") is False


def test_expired_captcha_fails():
    data = captcha_service.generate_captcha()
    code = captcha_service._store[data["captcha_id"]][0]
    # 直接把有效期改到过去,避免 patch 全局 time 模块
    captcha_service._store[data["captcha_id"]] = (code, time.time() - 1)

    assert captcha_service.verify_captcha(data["captcha_id"], code) is False


def test_file_store_shared_once(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "CAPTCHA_STORE", "file")
    monkeypatch.setattr(settings, "CAPTCHA_STORE_DIR", str(tmp_path))

    data = captcha_service.generate_captcha()
    entries = list(tmp_path.iterdir())
    assert len(entries) == 1
    assert captcha_service._store == {}

    code = entries[0].read_text(encoding="utf-8").splitlines()[0]
    # 另一个进程/实例读同一目录即可校验
    assert captcha_service.verify_captcha(data["captcha_id"], code.lower()) is True
    assert list(tmp_path.iterdir()) == []
    assert captcha_service.verify_captcha(data["captcha_id"], code) is False


def test_file_store_expired_entry_fails(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "CAPTCHA_STORE", "file")
    monkeypatch.setattr(settings, "CAPTCHA_STORE_DIR", str(tmp_path))

    data = captcha_service.generate_captcha()
    entry = list(tmp_path.iterdir())[0]
    code = entry.read_text(encoding="utf-8").splitlines()[0]
    entry.write_text(f"{code}\n{int(time.time()) - 1}", encoding="utf-8")

    assert captcha_service.verify_captcha(data["captcha_id"], code) is False


def test_captcha_endpoint_reports_required(monkeypatch):
    monkeypatch.setattr(auth_api, "captcha_required", lambda: True)
    enabled = auth_api.get_captcha()
    assert enabled["required"] is True
    assert enabled["captcha_id"]
    assert enabled["image"].startswith("data:image/png;base64,")

    monkeypatch.setattr(auth_api, "captcha_required", lambda: False)
    disabled = auth_api.get_captcha()
    assert disabled == {
        "required": False, "captcha_id": "", "image": "", "expires_in": 0,
    }


def test_login_requires_valid_captcha(db, monkeypatch):
    monkeypatch.setattr(auth_api, "captcha_required", lambda: True)

    with pytest.raises(HTTPException) as exc:
        auth_api.login(
            LoginRequest(email="captcha@example.com", password="Abcd1234"),
            Response(), db,
        )
    assert exc.value.status_code == 400

    with pytest.raises(HTTPException) as exc:
        auth_api.login(
            LoginRequest(
                email="captcha@example.com", password="Abcd1234",
                captcha_id="bad-id", captcha_code="ABCD",
            ),
            Response(), db,
        )
    assert exc.value.status_code == 400

    data = captcha_service.generate_captcha()
    code = captcha_service._store[data["captcha_id"]][0]
    payload = auth_api.login(
        LoginRequest(
            email="captcha@example.com", password="Abcd1234",
            captcha_id=data["captcha_id"], captcha_code=code,
        ),
        Response(), db,
    )
    assert payload.role == "student"


def test_register_requires_captcha(db, monkeypatch):
    monkeypatch.setattr(auth_api, "captcha_required", lambda: True)

    with pytest.raises(HTTPException) as exc:
        auth_api.register(RegisterRequest(
            role="student", name="新同学", email="new@example.com",
            password="Abcd1234",
        ), Response(), db)
    assert exc.value.status_code == 400
