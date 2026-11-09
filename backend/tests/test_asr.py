"""语音识别:本地 faster-whisper 与 OpenAI 兼容接口分流"""
import asyncio
import io
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, UploadFile
from starlette.datastructures import Headers
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import uploads as uploads_api
from app.core.config import settings
from app.db.session import Base
from app.models.user import User
from app.services import asr


class _Seg:
    def __init__(self, text):
        self.text = text


class _FakeModel:
    def transcribe(self, path, **kwargs):
        return iter([_Seg("你好"), _Seg("，世界")]), SimpleNamespace(language="zh")


class _EmptyModel:
    def transcribe(self, path, **kwargs):
        return iter([]), SimpleNamespace(language="zh")


def _set_local(monkeypatch, model="tiny"):
    monkeypatch.setattr(settings, "ASR_PROVIDER", "local")
    monkeypatch.setattr(settings, "ASR_LOCAL_MODEL", model)


def test_asr_enabled_local_and_openai(monkeypatch):
    _set_local(monkeypatch)
    assert asr.asr_enabled() is True

    monkeypatch.setattr(settings, "ASR_LOCAL_MODEL", "")
    assert asr.asr_enabled() is False

    monkeypatch.setattr(settings, "ASR_PROVIDER", "openai")
    monkeypatch.setattr(settings, "ASR_MODEL", "whisper-1")
    monkeypatch.setattr(settings, "ASR_API_KEY", "key")
    assert asr.asr_enabled() is True

    monkeypatch.setattr(settings, "ASR_API_KEY", "")
    assert asr.asr_enabled() is False


def test_local_transcription(monkeypatch):
    _set_local(monkeypatch)
    monkeypatch.setattr(asr, "_get_local_model", lambda: _FakeModel())

    text = asyncio.run(asr.transcribe_audio(Path("dummy.wav"), "dummy.wav"))

    assert text == "你好，世界"


def test_local_empty_result_raises(monkeypatch):
    _set_local(monkeypatch)
    monkeypatch.setattr(asr, "_get_local_model", lambda: _EmptyModel())

    with pytest.raises(ValueError, match="未识别到语音内容"):
        asyncio.run(asr.transcribe_audio(Path("dummy.wav"), "dummy.wav"))


def test_openai_provider_dispatch(monkeypatch):
    monkeypatch.setattr(settings, "ASR_PROVIDER", "openai")
    monkeypatch.setattr(settings, "ASR_MODEL", "whisper-1")
    monkeypatch.setattr(settings, "ASR_API_KEY", "key")

    async def fake_openai(path, filename):
        return "云端识别结果"

    monkeypatch.setattr(asr, "_transcribe_openai", fake_openai)

    text = asyncio.run(asr.transcribe_audio(Path("dummy.wav"), "dummy.wav"))
    assert text == "云端识别结果"


def test_disabled_raises(monkeypatch):
    monkeypatch.setattr(settings, "ASR_PROVIDER", "local")
    monkeypatch.setattr(settings, "ASR_LOCAL_MODEL", "")

    with pytest.raises(RuntimeError, match="语音识别未配置"):
        asyncio.run(asr.transcribe_audio(Path("dummy.wav"), "dummy.wav"))


def test_openai_transcription_uses_configured_language(monkeypatch, tmp_path):
    captured = {}

    class _Transcriptions:
        async def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(text="hello")

    class _Audio:
        transcriptions = _Transcriptions()

    class _Client:
        def __init__(self, **kwargs):
            self.audio = _Audio()

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(AsyncOpenAI=_Client))
    monkeypatch.setattr(settings, "ASR_PROVIDER", "openai")
    monkeypatch.setattr(settings, "ASR_API_KEY", "key")
    monkeypatch.setattr(settings, "ASR_MODEL", "whisper-1")
    monkeypatch.setattr(settings, "ASR_LANGUAGE", "en")

    path = tmp_path / "a.webm"
    path.write_bytes(b"fake")
    assert asyncio.run(asr._transcribe_openai(path, "a.webm")) == "hello"
    assert captured["language"] == "en"

    # 留空时不传 language,交由服务端自动识别
    monkeypatch.setattr(settings, "ASR_LANGUAGE", "")
    captured.clear()
    asyncio.run(asr._transcribe_openai(path, "a.webm"))
    assert "language" not in captured


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add(User(id=1, role="student", name="学生", email="s@example.com",
                     password_hash="x", status="active"))
    session.commit()
    yield session
    session.close()
    engine.dispose()


def _audio_file() -> UploadFile:
    return UploadFile(
        file=io.BytesIO(b"fake-webm-silence"),
        filename="voice.webm",
        headers=Headers({"content-type": "audio/webm"}),
    )


def _patch_audio_io(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(uploads_api, "asr_enabled", lambda: True)
    monkeypatch.setattr(uploads_api, "assert_audio_upload_allowed",
                        lambda *args, **kwargs: None)
    monkeypatch.setattr(uploads_api, "record_audio_upload",
                        lambda *args, **kwargs: None)


def test_silent_audio_returns_actionable_hint(monkeypatch, db, tmp_path):
    """录到静音时应提示检查麦克风,而不是报服务不可用"""
    _patch_audio_io(monkeypatch, tmp_path)

    async def silent_asr(path, filename):
        raise ValueError("未识别到语音内容")

    monkeypatch.setattr(uploads_api, "transcribe_audio", silent_asr)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(uploads_api.upload_audio(_audio_file(), db.get(User, 1), db))

    assert exc.value.status_code == 422
    assert "麦克风" in exc.value.detail
    assert list((tmp_path / "audio" / "1").glob("*")) == []


def test_asr_service_failure_still_reports_502(monkeypatch, db, tmp_path):
    _patch_audio_io(monkeypatch, tmp_path)

    async def broken_asr(path, filename):
        raise RuntimeError("connection reset")

    monkeypatch.setattr(uploads_api, "transcribe_audio", broken_asr)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(uploads_api.upload_audio(_audio_file(), db.get(User, 1), db))

    assert exc.value.status_code == 502
    assert list((tmp_path / "audio" / "1").glob("*")) == []


def test_successful_transcription_deletes_recording(monkeypatch, db, tmp_path):
    """录音只在识别时临时使用,识别完成即删除,不落库留存"""
    _patch_audio_io(monkeypatch, tmp_path)

    async def ok_asr(path, filename):
        assert path.exists()
        return "识别出来的文字"

    monkeypatch.setattr(uploads_api, "transcribe_audio", ok_asr)

    result = asyncio.run(uploads_api.upload_audio(_audio_file(), db.get(User, 1), db))

    assert result["text"] == "识别出来的文字"
    assert list((tmp_path / "audio" / "1").glob("*")) == []
