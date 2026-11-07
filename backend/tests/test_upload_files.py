"""识图图片自助管理 + 素材上传实际字节限制(决策 #6 / #14)"""
import io
from types import SimpleNamespace

import pytest
from fastapi import BackgroundTasks, HTTPException, UploadFile
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import admin as admin_api
from app.api import course as course_api
from app.api import teacher as teacher_api
from app.api import uploads as uploads_api
from app.core.config import settings
from app.db.session import Base
from app.models.course import Course, CourseMaterial
from app.models.user import User
from app.services.uploads import UploadTooLarge, save_upload_limited


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
        User(id=3, role="teacher", name="张老师", email="t@example.com",
             password_hash="x", status="active"),
        Course(id=10, teacher_id=3, name="软件测试", code="ST101",
               audit_status="approved"),
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


# ---------- 素材上传:实际字节限制 ----------

def _upload(data: bytes, filename="material.pdf", declared_size=None):
    return UploadFile(
        filename=filename, file=io.BytesIO(data), size=declared_size,
    )


@pytest.mark.parametrize("delta", [-1, 0, 1])
def test_save_upload_limited_counts_actual_bytes(tmp_path, delta):
    limit = 1024
    dest = tmp_path / "material.pdf"
    data = b"x" * (limit + delta)

    if delta > 0:
        with pytest.raises(UploadTooLarge):
            save_upload_limited(_upload(data), dest, limit)
        assert not dest.exists()
        assert list(tmp_path.glob("*.part*")) == []
    else:
        assert save_upload_limited(_upload(data), dest, limit) == limit + delta
        assert dest.exists()
        assert dest.stat().st_size == limit + delta


def test_save_upload_limited_ignores_declared_size(tmp_path):
    limit = 512
    dest = tmp_path / "forged.pdf"
    data = b"x" * (limit + 1)

    with pytest.raises(UploadTooLarge):
        save_upload_limited(
            _upload(data, declared_size=1), dest, limit,
        )
    assert not dest.exists()


def test_teacher_material_upload_rejects_over_limit(db, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "MATERIAL_MAX_BYTES", 1024)

    with pytest.raises(HTTPException) as exc:
        teacher_api.save_material(
            db, 10, "courseware", "超限素材",
            _upload(b"x" * 1025, declared_size=1),
        )

    assert exc.value.status_code == 413
    assert db.query(CourseMaterial).count() == 0
    assert list(tmp_path.rglob("*.part*")) == []


def test_teacher_material_upload_accepts_exact_limit(db, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "MATERIAL_MAX_BYTES", 1024)

    material = teacher_api.save_material(
        db, 10, "courseware", "刚好达标", _upload(b"x" * 1024),
    )

    assert db.query(CourseMaterial).count() == 1
    assert (tmp_path / "10").is_dir()
    saved = list((tmp_path / "10").iterdir())
    assert len(saved) == 1 and saved[0].stat().st_size == 1024
    assert material.chunk_count == 0


def test_course_material_upload_enforces_actual_bytes(db, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "MATERIAL_MAX_BYTES", 1024)
    monkeypatch.setattr(course_api, "assert_course_visible", lambda *a, **kw: None)

    with pytest.raises(HTTPException) as exc:
        course_api.upload_material(
            10, BackgroundTasks(), "courseware", "超限素材",
            _upload(b"x" * 1025), db.get(User, 3), db,
        )
    assert exc.value.status_code == 413
    assert db.query(CourseMaterial).count() == 0

    monkeypatch.setattr(
        course_api, "enqueue_parse",
        lambda session, material: SimpleNamespace(id=99),
    )
    monkeypatch.setattr(
        course_api, "material_out",
        lambda material, job: {"id": material.id, "chunk_count": 0},
    )
    result = course_api.upload_material(
        10, BackgroundTasks(), "courseware", "刚好达标",
        _upload(b"x" * 1024), db.get(User, 3), db,
    )
    assert result["id"]
    assert db.query(CourseMaterial).count() == 1


def test_admin_material_upload_uses_same_limit(db, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "MATERIAL_MAX_BYTES", 1024)
    monkeypatch.setattr(admin_api, "_audit", lambda *a, **kw: None)

    with pytest.raises(HTTPException) as exc:
        admin_api.admin_upload_material(
            SimpleNamespace(), 10, "courseware", "代传超限",
            _upload(b"x" * 1025), db.get(User, 3), db,
        )

    assert exc.value.status_code == 413
    assert db.query(CourseMaterial).count() == 0
