"""AG-14：自然 AI 语音合成与无留存返回"""
import asyncio
import importlib
import inspect
import logging
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api import api_router
from app.core.deps import get_current_user


def _speech_api():
    return importlib.import_module("app.api.speech")


def test_speech_route_requires_authentication():
    route = next(
        (
            item for item in api_router.routes
            if item.path == "/api/speech" and "POST" in item.methods
        ),
        None,
    )

    assert route is not None
    dependency = inspect.signature(route.endpoint).parameters["user"].default
    assert dependency.dependency is get_current_user


def test_ai_synthesis_uses_natural_chinese_voice(monkeypatch):
    speech_api = _speech_api()
    captured = {}

    class FakeCommunicate:
        def __init__(self, text, voice):
            captured.update(text=text, voice=voice)

        async def stream(self):
            yield {"type": "audio", "data": b"mp3-"}
            yield {"type": "WordBoundary", "data": b"ignored"}
            yield {"type": "audio", "data": b"audio"}

    monkeypatch.setattr(speech_api.edge_tts, "Communicate", FakeCommunicate)

    result = asyncio.run(speech_api.synthesize_text("你好"))

    assert result == b"mp3-audio"
    assert captured == {"text": "你好", "voice": "zh-CN-XiaoxiaoNeural"}


def test_speech_endpoint_returns_memory_audio_without_store(monkeypatch):
    speech_api = _speech_api()

    async def fake_synthesize(text):
        assert text == "自然朗读"
        return b"mp3-audio"

    monkeypatch.setattr(speech_api, "synthesize_text", fake_synthesize)

    response = asyncio.run(speech_api.create_speech(
        speech_api.SpeechRequest(text="自然朗读"), SimpleNamespace(id=1),
    ))

    assert response.body == b"mp3-audio"
    assert response.media_type == "audio/mpeg"
    assert response.headers["Cache-Control"] == "no-store"


def test_speech_failure_does_not_log_answer_text(monkeypatch, caplog):
    speech_api = _speech_api()
    sensitive_text = "完整回答正文 secret@example.com"

    async def fail_synthesize(text):
        raise RuntimeError(f"provider failed: {text}")

    monkeypatch.setattr(speech_api, "synthesize_text", fail_synthesize)

    with caplog.at_level(logging.ERROR, logger="app.api.speech"):
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(speech_api.create_speech(
                speech_api.SpeechRequest(text=sensitive_text), SimpleNamespace(id=1),
            ))

    assert exc_info.value.status_code == 503
    assert sensitive_text not in caplog.text
    assert "RuntimeError" in caplog.text
