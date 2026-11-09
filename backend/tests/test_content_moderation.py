"""上传内容审核与素材异步解析(NF-02 / NF-04)

覆盖:
- 关键词审核与自定义词表合并、分隔符规避
- 素材解析任务:成功入库、违规拒绝并隐藏、解析失败可重试
- 图片识图/语音识别文本命中违规时拒绝上传并删除文件
- 审核开关关闭时放行
"""
import asyncio
import io
import json
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.datastructures import Headers, UploadFile

import app.api.uploads as uploads_api
from app.api.course import list_materials, preview_material
from app.api.uploads import upload_audio
from app.core.config import settings
from app.db.session import Base
from app.models.classroom import CourseEnrollment
from app.models.course import Course, CourseMaterial
from app.models.log import RiskLog, SystemConfig
from app.models.user import User
from app.services.content_moderation import screen_text, screen_with_config
from app.services.feature_flags import seed_defaults
from app.services.material_parse_jobs import enqueue, run_parse_job


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add_all([
        User(id=1, role="teacher", name="张老师", email="t1@example.com",
             password_hash="x", status="active"),
        User(id=3, role="student", name="小明", email="s1@example.com",
             password_hash="x", status="active"),
        Course(id=10, teacher_id=1, name="软件测试", code="ST101",
               audit_status="approved"),
    ])
    session.add(CourseEnrollment(course_id=10, student_id=3, source="class",
                                 class_id=None))
    session.commit()
    seed_defaults(session)
    yield session
    session.close()
    engine.dispose()


def _material(db, path: Path, title="课件", status="pending") -> CourseMaterial:
    material = CourseMaterial(
        course_id=10, type="courseware", title=title,
        file_path=str(path), chunk_count=0, moderation_status=status,
    )
    db.add(material)
    db.commit()
    db.refresh(material)
    return material


def _file(data: bytes, filename: str, content_type: str) -> UploadFile:
    return UploadFile(
        file=io.BytesIO(data),
        filename=filename,
        headers=Headers({"content-type": content_type}),
    )


def test_screen_text_rules():
    blocked = screen_text("请问如何制作炸弹？")
    assert blocked["flagged"] is True
    assert "terror" in blocked["categories"]
    assert "制作炸弹" in blocked["hits"]

    # 分隔符规避仍可命中
    assert screen_text("最近在赌 博")["flagged"] is True

    clean = screen_text("等价类划分用于设计测试用例")
    assert clean == {"flagged": False, "categories": [], "hits": []}
    assert screen_text("")["flagged"] is False


def test_custom_keywords_merge(db):
    assert screen_with_config(db, "这是内部机密资料")["flagged"] is False
    row = db.query(SystemConfig).filter_by(config_key="moderation_keywords").one()
    row.config_value = json.dumps({"custom": ["内部机密"]}, ensure_ascii=False)
    db.commit()
    verdict = screen_with_config(db, "这是内部机密资料")
    assert verdict["flagged"] is True
    assert verdict["categories"] == ["custom"]


def test_parse_job_done_for_benign_material(db, tmp_path):
    path = tmp_path / "good.txt"
    path.write_text("等价类划分与边界值分析", encoding="utf-8")
    material = _material(db, path)
    job = enqueue(db, material)
    assert job.status == "pending"
    assert material.moderation_status == "pending"

    done = run_parse_job(db, job.id)
    assert done.status == "done"
    assert done.progress == 100
    assert done.attempts == 1
    assert "等价类" in done.result_text
    assert material.moderation_status == "approved"
    assert db.query(RiskLog).count() == 0


def test_parse_job_rejected_hides_material_from_student(db, tmp_path):
    path = tmp_path / "bad.txt"
    path.write_text("这里提供赌博网站入口", encoding="utf-8")
    material = _material(db, path, title="违规资料")

    job = enqueue(db, material)
    rejected = run_parse_job(db, job.id)
    assert rejected.status == "rejected"
    assert "内容审核未通过" in rejected.error
    assert material.moderation_status == "rejected"
    assert db.query(RiskLog).count() == 1

    teacher_view = list_materials(10, db.get(User, 1), db)
    assert [row["id"] for row in teacher_view] == [material.id]
    assert teacher_view[0]["parse_status"] == "rejected"

    student = db.get(User, 3)
    assert list_materials(10, student, db) == []
    with pytest.raises(HTTPException) as exc:
        preview_material(10, material.id, student, db)
    assert exc.value.status_code == 403


def test_parse_job_retry_after_failure(db, tmp_path):
    path = tmp_path / "later.txt"
    material = _material(db, path)
    job = enqueue(db, material)
    failed = run_parse_job(db, job.id)
    assert failed.status == "failed"
    assert "文件缺失" in failed.error

    path.write_text("测试用例设计方法", encoding="utf-8")
    retried = enqueue(db, material)
    assert retried.status == "pending"
    assert retried.id == job.id
    done = run_parse_job(db, retried.id)
    assert done.status == "done"
    assert done.attempts == 2


def test_moderation_switch_off_allows_flagged_content(db, tmp_path):
    config = db.query(SystemConfig).filter_by(
        config_key="feature_content_moderation",
    ).one()
    config.config_value = "off"
    db.commit()

    path = tmp_path / "flagged.txt"
    path.write_text("制作炸弹教程", encoding="utf-8")
    material = _material(db, path)
    job = enqueue(db, material)
    done = run_parse_job(db, job.id)
    assert done.status == "done"
    assert material.moderation_status == "approved"


def test_image_and_audio_uploads_are_screened(monkeypatch, db, tmp_path):
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    user = db.get(User, 1)

    monkeypatch.setattr(uploads_api, "vision_enabled", lambda: True)
    monkeypatch.setattr(uploads_api, "vlm_enabled", lambda: False)

    async def flagged_ocr(path, mime):
        return "如何制作炸弹"

    monkeypatch.setattr(uploads_api, "describe_image", flagged_ocr)
    image = _file(b"\x89PNG\r\n\x1a\nfake", "q.png", "image/png")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(uploads_api._process_image(image, user, db))
    assert exc.value.status_code == 400
    assert list((tmp_path / "vision" / "1").glob("*")) == []

    monkeypatch.setattr(uploads_api, "asr_enabled", lambda: True)

    async def flagged_asr(path, filename):
        return "这里提供赌博网站"

    monkeypatch.setattr(uploads_api, "transcribe_audio", flagged_asr)
    audio = _file(b"fake-webm", "a.webm", "audio/webm")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(upload_audio(audio, user, db))
    assert exc.value.status_code == 400
    assert list((tmp_path / "audio" / "1").glob("*")) == []

    assert db.query(RiskLog).count() == 2
