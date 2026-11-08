"""AG-09 多模态配额:图片/语音的大小、次数、时长与角色倍数

覆盖:
- 语音单次大小/时长上限
- 语音每日次数上限
- 语音每日总时长上限(按已用时长累加)
- 教师角色配额倍数(2x)
- 语音开关关闭时拒绝
- 音频时长探测(本地 WAV)
"""
import wave

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.uploads import _probe_duration
from app.db.session import Base
from app.models.log import SystemConfig
from app.models.upload_event import UploadEvent
from app.models.user import User
from app.services.quotas import (
    assert_audio_upload_allowed, assert_image_upload_allowed,
    record_audio_upload, record_image_upload,
)


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add_all([
        User(id=1, role="student", name="学生", email="s@example.com",
             password_hash="x", status="active"),
        User(id=2, role="teacher", name="教师", email="t@example.com",
             password_hash="x", status="active"),
    ])
    session.commit()
    yield session
    session.close()
    engine.dispose()


def _set(db, key, value):
    row = db.query(SystemConfig).filter_by(config_key=key).first()
    if row:
        row.config_value = str(value)
    else:
        db.add(SystemConfig(config_key=key, config_value=str(value)))
    db.commit()


def test_audio_size_and_single_duration_limits(db):
    student = db.get(User, 1)
    _set(db, "asr_max_mb", 1)
    with pytest.raises(HTTPException) as exc:
        assert_audio_upload_allowed(db, student, 2 * 1024 * 1024, 10)
    assert exc.value.status_code == 400
    assert "1MB" in exc.value.detail

    _set(db, "asr_max_mb", 10)
    _set(db, "asr_max_seconds", 60)
    with pytest.raises(HTTPException) as exc:
        assert_audio_upload_allowed(db, student, 1024, 61)
    assert exc.value.status_code == 400
    assert "60 秒" in exc.value.detail

    assert_audio_upload_allowed(db, student, 1024, 60)


def test_audio_daily_count_limit(db):
    student = db.get(User, 1)
    _set(db, "asr_daily_limit", 2)
    assert_audio_upload_allowed(db, student, 1024, 5)
    record_audio_upload(db, student, 1024, 5)
    assert_audio_upload_allowed(db, student, 1024, 5)
    record_audio_upload(db, student, 1024, 5)

    with pytest.raises(HTTPException) as exc:
        assert_audio_upload_allowed(db, student, 1024, 5)
    assert exc.value.status_code == 429
    assert "次数" in exc.value.detail


def test_audio_daily_seconds_limit(db):
    student = db.get(User, 1)
    _set(db, "asr_daily_seconds", 10)
    record_audio_upload(db, student, 1024, 6)

    with pytest.raises(HTTPException) as exc:
        assert_audio_upload_allowed(db, student, 1024, 5)
    assert exc.value.status_code == 429
    assert "时长" in exc.value.detail

    assert_audio_upload_allowed(db, student, 1024, 4)
    record_audio_upload(db, student, 1024, 4)
    with pytest.raises(HTTPException):
        assert_audio_upload_allowed(db, student, 1024, 1)


def test_role_multiplier_for_image_quota(db):
    student = db.get(User, 1)
    teacher = db.get(User, 2)
    _set(db, "vision_daily_limit", 30)

    for _ in range(30):
        db.add(UploadEvent(user_id=student.id, kind="image", size=100))
        db.add(UploadEvent(user_id=teacher.id, kind="image", size=100))
    db.commit()

    with pytest.raises(HTTPException) as exc:
        assert_image_upload_allowed(db, student, 100)
    assert exc.value.status_code == 429

    # 教师 2x:已用 30 次,仍可继续
    assert_image_upload_allowed(db, teacher, 100)
    record_image_upload(db, teacher, 100)


def test_audio_feature_switch_off(db):
    student = db.get(User, 1)
    _set(db, "feature_asr", "off")
    with pytest.raises(HTTPException) as exc:
        assert_audio_upload_allowed(db, student, 1024, 1)
    assert exc.value.status_code == 403


def test_probe_duration_reads_wav(tmp_path):
    # av 属 requirements-asr.txt 可选依赖,未安装时时长探测按 0 降级
    pytest.importorskip("av")
    path = tmp_path / "one_second.wav"
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(b"\x00\x00" * 16000)

    duration = _probe_duration(path)
    assert 0.9 <= duration <= 1.1
