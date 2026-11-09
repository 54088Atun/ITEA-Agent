"""语音识别

支持三种 provider:
- dashscope: 阿里云百炼原生语音识别接口(推荐 qwen-audio-3.0-asr-flash)
- openai:    调用 OpenAI 兼容 transcription 接口(需 ASR_MODEL + ASR_API_KEY)
- local:     本机 faster-whisper 离线识别(需 ASR_LOCAL_MODEL,无需 API Key)

未配置时返回未启用,由调用方提示,不在无能力环境里伪造识别结果。
"""
import asyncio
import base64
import logging
import mimetypes
import threading
import time
from pathlib import Path

import httpx

from app.core.config import settings
from app.services.runtime_metrics import record_runtime_metric

logger = logging.getLogger(__name__)

_local_model = None
_local_lock = threading.Lock()

LOCAL_PROVIDERS = {"local", "faster-whisper", "faster_whisper", "whisper"}
DASHSCOPE_PROVIDERS = {"dashscope", "bailian", "aliyun", "qwen"}
DASHSCOPE_ASR_PATH = "/api/v1/services/aigc/multimodal-generation/generation"


def _provider() -> str:
    return (settings.ASR_PROVIDER or "openai").strip().lower()


def _api_key() -> str:
    """语音识别密钥:优先 ASR_API_KEY,未单独配置时复用百炼 DASHSCOPE_API_KEY"""
    return settings.ASR_API_KEY or settings.DASHSCOPE_API_KEY


def asr_enabled() -> bool:
    if _provider() in LOCAL_PROVIDERS:
        return bool(settings.ASR_LOCAL_MODEL)
    return bool(settings.ASR_MODEL and _api_key())


def _get_local_model():
    """懒加载并复用本机模型,避免每次请求重复加载"""
    global _local_model
    if _local_model is not None:
        return _local_model
    with _local_lock:
        if _local_model is not None:
            return _local_model
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:  # pragma: no cover - 环境相关
            raise RuntimeError(
                "本地 ASR 未安装 faster-whisper,请先安装后再启用"
            ) from exc
        logger.info(
            "加载本地 ASR 模型 model=%s device=%s compute=%s",
            settings.ASR_LOCAL_MODEL, settings.ASR_LOCAL_DEVICE,
            settings.ASR_LOCAL_COMPUTE_TYPE,
        )
        _local_model = WhisperModel(
            settings.ASR_LOCAL_MODEL,
            device=settings.ASR_LOCAL_DEVICE or "cpu",
            compute_type=settings.ASR_LOCAL_COMPUTE_TYPE or "int8",
        )
        return _local_model


def _transcribe_local_sync(path: Path) -> str:
    model = _get_local_model()
    segments, info = model.transcribe(
        str(path),
        language=settings.ASR_LANGUAGE or None,
        beam_size=5,
        vad_filter=True,
    )
    text = "".join(getattr(seg, "text", "") for seg in segments).strip()
    if not text:
        raise ValueError("未识别到语音内容")
    logger.info("本地 ASR 完成 language=%s chars=%s", getattr(info, "language", ""), len(text))
    return text


async def _transcribe_local(path: Path) -> str:
    return await asyncio.to_thread(_transcribe_local_sync, path)


async def _transcribe_openai(path: Path, filename: str) -> str:
    from openai import AsyncOpenAI

    client = AsyncOpenAI(
        base_url=settings.ASR_API_BASE or None,
        api_key=_api_key(),
        timeout=settings.ASR_TIMEOUT,
    )
    data = path.read_bytes()
    payload = {
        "model": settings.ASR_MODEL,
        "file": (filename, data),
    }
    if settings.ASR_LANGUAGE:
        payload["language"] = settings.ASR_LANGUAGE
    resp = await client.audio.transcriptions.create(**payload)
    text = (getattr(resp, "text", "") or "").strip()
    if not text:
        raise ValueError("未识别到语音内容")
    return text


def _wav_sample_rate(data: bytes) -> int:
    """从 WAV 头读取采样率;非 WAV 默认 16000"""
    if len(data) >= 28 and data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        rate = int.from_bytes(data[24:28], "little")
        return rate or 16000
    return 16000


async def _transcribe_dashscope(path: Path, filename: str) -> str:
    """阿里云百炼原生语音识别:音频以 data URL 传入,支持 5 分钟以内文件"""
    data = path.read_bytes()
    suffix = Path(filename).suffix.lstrip(".").lower() or "wav"
    mime = mimetypes.guess_type(filename)[0] or f"audio/{suffix}"
    payload = {
        "model": settings.ASR_MODEL,
        "input": {
            "messages": [{
                "role": "user",
                "content": [{
                    "type": "input_audio",
                    "input_audio": {
                        "data": f"data:{mime};base64,{base64.b64encode(data).decode()}",
                    },
                }],
            }],
        },
        "parameters": {
            "format": suffix,
            "sample_rate": str(_wav_sample_rate(data)),
        },
    }
    base = (settings.ASR_API_BASE or "https://dashscope.aliyuncs.com").rstrip("/")
    url = base + DASHSCOPE_ASR_PATH
    async with httpx.AsyncClient(timeout=settings.ASR_TIMEOUT) as client:
        resp = await client.post(
            url, json=payload,
            headers={"Authorization": f"Bearer {_api_key()}"},
        )
    try:
        body = resp.json()
    except ValueError as exc:
        raise RuntimeError("语音识别服务返回了非 JSON 响应") from exc
    if resp.status_code >= 400:
        raise RuntimeError(str(body.get("message") or "语音识别失败"))
    output = body.get("output") or {}
    text = str(
        (output.get("sentence") or {}).get("text")
        or output.get("text")
        or ""
    ).strip()
    if not text:
        raise ValueError("未识别到语音内容")
    return text


async def transcribe_audio(path: Path, filename: str) -> str:
    """把音频转写为文字;失败时抛异常由调用方转为可读提示"""
    started_at = time.monotonic()
    try:
        if not asr_enabled():
            raise RuntimeError("语音识别未配置")

        if _provider() in LOCAL_PROVIDERS:
            text = await _transcribe_local(path)
        elif _provider() in DASHSCOPE_PROVIDERS:
            text = await _transcribe_dashscope(path, filename)
        else:
            text = await _transcribe_openai(path, filename)
    except (Exception, asyncio.CancelledError):
        record_runtime_metric(
            "asr", "failure", (time.monotonic() - started_at) * 1000,
        )
        raise
    record_runtime_metric(
        "asr", "success", (time.monotonic() - started_at) * 1000,
    )
    return text
