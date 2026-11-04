"""头像上传:格式/大小校验、落盘与旧文件替换(PC-05)"""
import asyncio
import io

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.datastructures import Headers, UploadFile

import app.api.me as me_api
from app.api.me import get_profile, upload_avatar
from app.core.config import settings
from app.db.session import Base
from app.models.user import User


@pytest.fixture()
def db(tmp_path, monkeypatch):
    engine = create_engine("sqlite:///:memory:", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    user = User(
        id=1, role="student", name="小明", email="avatar@example.com",
        password_hash="x", status="active",
    )
    session.add(user)
    session.commit()
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    yield session, user
    session.close()
    engine.dispose()


def _file(data=b"\x89PNG\r\n\x1a\n", filename="avatar.png", content_type="image/png"):
    return UploadFile(
        file=io.BytesIO(data), filename=filename,
        headers=Headers({"content-type": content_type}),
    )


def test_avatar_upload_and_replace(db):
    session, user = db

    first = asyncio.run(upload_avatar(_file(b"png-one"), user, session))
    assert first["avatar_url"].startswith("/uploads/avatar/")
    first_path = settings.upload_path / "avatar" / first["avatar_url"].rsplit("/", 1)[-1]
    assert first_path.read_bytes() == b"png-one"

    profile = get_profile(user)
    assert profile.avatar_url == first["avatar_url"]

    second = asyncio.run(upload_avatar(_file(b"png-two"), user, session))
    assert second["avatar_url"] != first["avatar_url"]
    assert not first_path.exists(), "旧头像应被删除"
    second_path = settings.upload_path / "avatar" / second["avatar_url"].rsplit("/", 1)[-1]
    assert second_path.read_bytes() == b"png-two"


def test_avatar_rejects_bad_type_and_size(db, monkeypatch):
    session, user = db

    with pytest.raises(HTTPException) as bad_type:
        asyncio.run(upload_avatar(
            _file(b"text", filename="a.txt", content_type="text/plain"), user, session,
        ))
    assert bad_type.value.status_code == 400
    assert "PNG" in bad_type.value.detail

    with pytest.raises(HTTPException) as empty:
        asyncio.run(upload_avatar(_file(b""), user, session))
    assert empty.value.status_code == 400

    monkeypatch.setattr(me_api, "AVATAR_MAX_BYTES", 4)
    with pytest.raises(HTTPException) as oversized:
        asyncio.run(upload_avatar(_file(b"12345"), user, session))
    assert oversized.value.status_code == 400
    assert "2MB" in oversized.value.detail
