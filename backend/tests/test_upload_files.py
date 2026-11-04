"""识图图片自助管理:仅能列出与删除本人的图片(决策 #6 / #14)"""
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import uploads as uploads_api
from app.core.config import settings
from app.db.session import Base
from app.models.user import User


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add_all([
        User(id=1, role="student", name="甲", email="a@example.com",
             password_hash="x", status="active"),
        User(id=2, role="student", name="乙", email="b@example.com",
             password_hash="x", status="active"),
    ])
    session.commit()
    yield session
    session.close()
    engine.dispose()


def _seed(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    own = tmp_path / "vision" / "1"
    other = tmp_path / "vision" / "2"
    own.mkdir(parents=True)
    other.mkdir(parents=True)
    (own / "mine.png").write_bytes(b"png-data")
    (own / "notes.txt").write_bytes(b"not-an-image")
    (other / "theirs.png").write_bytes(b"png-data")
    return own, other


def test_list_only_own_images(db, tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)

    result = uploads_api.list_my_images(db.get(User, 1))

    assert [item["filename"] for item in result["items"]] == ["mine.png"]
    assert result["items"][0]["path"] == "/uploads/vision/1/mine.png"
    assert result["items"][0]["size"] == 8


def test_delete_own_image(db, tmp_path, monkeypatch):
    own, _ = _seed(tmp_path, monkeypatch)

    result = uploads_api.delete_my_image("mine.png", db.get(User, 1))

    assert result["deleted"] == "mine.png"
    assert not (own / "mine.png").exists()


def test_cannot_delete_others_or_escape_dir(db, tmp_path, monkeypatch):
    _, other = _seed(tmp_path, monkeypatch)
    user = db.get(User, 1)

    with pytest.raises(HTTPException) as exc:
        uploads_api.delete_my_image("theirs.png", user)
    assert exc.value.status_code == 404
    assert (other / "theirs.png").exists()

    with pytest.raises(HTTPException) as exc:
        uploads_api.delete_my_image("../2/theirs.png", user)
    assert exc.value.status_code == 404
    assert (other / "theirs.png").exists()

    with pytest.raises(HTTPException) as exc:
        uploads_api.delete_my_image("notes.txt", user)
    assert exc.value.status_code == 404
