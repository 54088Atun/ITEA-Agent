"""回答朗读：自然 AI 语音合成，音频仅在内存中传递"""
import logging

import edge_tts
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from app.core.deps import get_current_user
from app.core.log_sanitizer import safe_exception
from app.models.user import User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/speech", tags=["语音合成"])

VOICE = "zh-CN-XiaoxiaoNeural"


class SpeechRequest(BaseModel):
    text: str = Field(min_length=1, max_length=12000)


async def synthesize_text(text: str) -> bytes:
    audio = bytearray()
    async for chunk in edge_tts.Communicate(text, VOICE).stream():
        if chunk["type"] == "audio":
            audio.extend(chunk["data"])
    if not audio:
        raise RuntimeError("AI 语音服务未返回音频")
    return bytes(audio)


@router.post("")
async def create_speech(
    payload: SpeechRequest,
    user: User = Depends(get_current_user),
):
    try:
        audio = await synthesize_text(payload.text)
    except Exception as exc:
        logger.error("AI 语音合成失败: %s", safe_exception(exc))
        raise HTTPException(
            status_code=503, detail="AI 语音服务暂时不可用，请稍后重试",
        ) from None
    return Response(
        content=audio,
        media_type="audio/mpeg",
        headers={"Cache-Control": "no-store"},
    )
