"""多图上传与识图注入隔离(AG-02)"""
import asyncio
import io

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.datastructures import Headers, UploadFile

import app.api.uploads as uploads_api
from app.api.uploads import MAX_BATCH_IMAGES, upload_images
from app.core.config import settings
from app.db.session import Base
from app.models.log import SystemConfig
from app.models.upload_event import UploadEvent
from app.models.user import User
from app.services.feature_flags import seed_defaults
from app.services.vision import EXTRACT_PROMPT, clean_text


def _file(data: bytes = b"\x89PNG\r\n\x1a\nfake", filename: str = "q.png") -> UploadFile:
    return UploadFile(
        file=io.BytesIO(data),
        filename=filename,
        headers=Headers({"content-type": "image/png"}),
    )


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    session.add(User(id=3, role="student", name="学生", email="s@example.com",
                     password_hash="x", status="active"))
    session.commit()
    seed_defaults(session)
    yield session
    session.close()
    engine.dispose()


def _use_tmp_uploads(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    # 关掉本地 VLM 语义描述,避免单测触发真实模型下载
    monkeypatch.setattr(uploads_api, "vlm_enabled", lambda: False)


def test_batch_upload_two_images(monkeypatch, db, tmp_path):
    _use_tmp_uploads(monkeypatch, tmp_path)
    monkeypatch.setattr(uploads_api, "vision_enabled", lambda: True)

    async def fake_describe(path, mime):
        return f"题目文本:{path.name[:4]}"

    monkeypatch.setattr(uploads_api, "describe_image", fake_describe)
    user = db.get(User, 3)

    result = asyncio.run(upload_images([_file(), _file(filename="q2.png")], user, db))

    assert result["count"] == 2
    assert result["vision_enabled"] is True
    assert all(item["text"].startswith("题目文本:") for item in result["items"])
    assert all(item["path"].startswith("/uploads/vision/3/") for item in result["items"])
    assert db.query(UploadEvent).filter(UploadEvent.kind == "image").count() == 2
    assert len(list((tmp_path / "vision" / "3").iterdir())) == 2


def test_batch_rejects_too_many_images(db):
    files = [_file(filename=f"q{i}.png") for i in range(MAX_BATCH_IMAGES + 1)]
    with pytest.raises(HTTPException) as exc:
        asyncio.run(upload_images(files, db.get(User, 3), db))
    assert exc.value.status_code == 400
    assert "最多" in exc.value.detail


def test_batch_partial_quota_keeps_first(monkeypatch, db, tmp_path):
    _use_tmp_uploads(monkeypatch, tmp_path)
    monkeypatch.setattr(uploads_api, "vision_enabled", lambda: True)

    async def fake_describe(path, mime):
        return "识别成功"

    monkeypatch.setattr(uploads_api, "describe_image", fake_describe)
    cfg = db.query(SystemConfig).filter_by(config_key="vision_daily_limit").first()
    cfg.config_value = "1"
    db.commit()

    result = asyncio.run(upload_images([_file(), _file(filename="q2.png")], db.get(User, 3), db))

    assert result["items"][0]["text"] == "识别成功"
    assert "上限" in result["items"][1]["error"]
    assert db.query(UploadEvent).filter(UploadEvent.kind == "image").count() == 1


def test_batch_without_vision_returns_empty_text(monkeypatch, db, tmp_path):
    _use_tmp_uploads(monkeypatch, tmp_path)
    monkeypatch.setattr(uploads_api, "vision_enabled", lambda: False)

    result = asyncio.run(upload_images([_file()], db.get(User, 3), db))

    assert result["vision_enabled"] is False
    assert result["items"][0]["text"] == ""
    assert result["items"][0]["error"] is None


def test_vision_prompt_treats_image_as_untrusted():
    assert "不可信" in EXTRACT_PROMPT
    assert "忽略" in EXTRACT_PROMPT
    assert "系统提示" in EXTRACT_PROMPT


def test_clean_text_strips_controls_and_truncates():
    assert clean_text("题目\x00\x01文本\n\n\n\n第二行") == "题目文本\n\n第二行"
    assert len(clean_text("字" * 5000)) == 4000
    assert clean_text(None) == ""
