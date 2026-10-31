"""图片识图:调用可选的多模态模型提取图片中的题目/文字

未配置 VISION_MODEL / VISION_API_KEY 时返回 None,由调用方提示"识图未启用",
避免在无视觉能力的环境里伪造结果。
"""
import base64
import logging
from pathlib import Path

from app.core.config import settings

logger = logging.getLogger(__name__)

MAX_IMAGE_BYTES = 8 * 1024 * 1024

EXTRACT_PROMPT = (
    "你是教学辅助助手。请准确提取图片中的题目、文字与公式,"
    "保持原有层级与题意;若图片是手写内容,尽量转写为可读文本。"
    "只输出提取结果,不要解题,不要添加解释。"
)


def vision_enabled() -> bool:
    return bool(settings.VISION_MODEL and settings.VISION_API_KEY)


async def describe_image(path: Path, mime: str) -> str | None:
    if not vision_enabled():
        return None
    if path.stat().st_size > MAX_IMAGE_BYTES:
        raise ValueError("图片超过 8MB")

    from openai import AsyncOpenAI

    client = AsyncOpenAI(
        base_url=settings.VISION_API_BASE or None,
        api_key=settings.VISION_API_KEY,
    )
    b64 = base64.b64encode(path.read_bytes()).decode()
    resp = await client.chat.completions.create(
        model=settings.VISION_MODEL,
        temperature=0,
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": EXTRACT_PROMPT},
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
            ],
        }],
    )
    content = (resp.choices[0].message.content or "").strip()
    return content or None
