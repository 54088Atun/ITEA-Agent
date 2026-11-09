"""通用上传路由:图片识图(可选视觉模型)、语音识别(可选 ASR)"""
import asyncio
import logging
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, WebSocket
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import get_current_user
from app.core.log_sanitizer import safe_exception
from app.db.session import get_db
from app.models.user import User
from app.services.asr import asr_enabled, transcribe_audio
from app.services.content_moderation import (
    moderation_enabled, record_rejection, screen_with_config,
)
from app.services.material_parser import (
    CODE_EXTS, DOC_EXTS, SUPPORTED_HINT, TEXT_EXTS, extract_text, safe_filename,
)
from app.services.quotas import (
    assert_audio_upload_allowed, assert_image_upload_allowed,
    record_audio_upload, record_image_upload,
)
from app.services.realtime_asr import (
    issue_stream_ticket, relay_audio_stream, user_from_stream_ticket,
)
from app.services.vision import (
    MAX_IMAGE_BYTES, describe_image, describe_image_semantics, vision_enabled,
    vlm_enabled,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/uploads", tags=["上传"])

MAX_BATCH_IMAGES = 3

ALLOWED_MIME = {"image/png", "image/jpeg", "image/jpg", "image/webp"}
EXT_BY_MIME = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/webp": ".webp",
}
MIME_BY_EXT = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}

AUDIO_EXTS = {".webm", ".ogg", ".mp3", ".wav", ".m4a", ".mp4", ".aac"}

AUDIO_EXT_BY_MIME = {
    "audio/webm": ".webm",
    "video/webm": ".webm",
    "audio/ogg": ".ogg",
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/mp4": ".m4a",
    "audio/x-m4a": ".m4a",
    "audio/aac": ".aac",
}


def _audio_ext(file: UploadFile) -> str:
    ext = Path(file.filename or "").suffix.lower()
    if ext in AUDIO_EXTS:
        return ext
    mime = (file.content_type or "").lower().split(";")[0].strip()
    return AUDIO_EXT_BY_MIME.get(mime, "")


def _probe_duration(path: Path) -> float:
    """读取音频时长(秒);解码失败返回 0,由大小/次数限额兜底"""
    try:
        import av
    except ImportError:
        return 0.0
    try:
        with av.open(str(path)) as container:
            if container.duration:
                return round(float(container.duration) / 1_000_000, 2)
            stream = next(
                (s for s in container.streams if s.type == "audio"), None,
            )
            if stream and stream.duration and stream.time_base:
                return round(float(stream.duration * stream.time_base), 2)
    except Exception as exc:  # noqa: BLE001
        logger.warning("读取音频时长失败: %s", safe_exception(exc))
    return 0.0


async def _process_image(file: UploadFile, user: User, db: Session) -> dict:
    """校验、落盘并识别单张图片"""
    mime = (file.content_type or "").lower().split(";")[0].strip()
    if mime not in ALLOWED_MIME:
        # 部分客户端不带正确 content-type,退回按扩展名判定
        mime = MIME_BY_EXT.get(Path(file.filename or "").suffix.lower(), "")
    if mime not in ALLOWED_MIME:
        raise HTTPException(status_code=400, detail="仅支持 PNG / JPG / WEBP 图片")

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="图片为空")
    # 识图未配置时直接拒绝,不落盘、不消耗每日配额
    enabled = vision_enabled()
    if not enabled:
        raise HTTPException(
            status_code=503,
            detail="识图服务未配置，请直接输入题目文字",
        )
    # 能力开关 + 大小 + 每日次数
    assert_image_upload_allowed(db, user, len(data))

    save_dir = settings.upload_path / "vision" / str(user.id)
    save_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid.uuid4().hex}{EXT_BY_MIME.get(mime, '.png')}"
    path = save_dir / filename
    path.write_bytes(data)
    record_image_upload(db, user, len(data))

    text = None
    description = ""
    error = None
    try:
        text = await describe_image(path, mime)
    except ValueError as e:
        # 图片过大 / 未识别到文字属于输入问题,不能笼统报"服务不可用"
        logger.warning("图片识图失败: %s", safe_exception(e))
        if len(data) > MAX_IMAGE_BYTES:
            error = f"图片过大，请压缩后再上传（上限 {MAX_IMAGE_BYTES // 1024 // 1024}MB）"
        else:
            error = "未识别到图片中的文字，请换一张清晰的图片或直接输入题目"
    except Exception as e:  # noqa: BLE001
        logger.warning("图片识图失败: %s", safe_exception(e))
        error = "识图服务暂时不可用，请手动输入题目内容"

    if vlm_enabled():
        description = await describe_image_semantics(path)

    if text and moderation_enabled(db):
        verdict = screen_with_config(db, text)
        if verdict["flagged"]:
            path.unlink(missing_ok=True)
            record_rejection(db, user.id, text, verdict, "图片识图")
            db.commit()
            raise HTTPException(status_code=400, detail="图片内容未通过审核，请更换图片")

    return {
        "path": f"/uploads/vision/{user.id}/{filename}",
        "filename": filename,
        "size": len(data),
        "vision_enabled": enabled,
        "vlm_enabled": vlm_enabled(),
        "text": text or "",
        "description": description,
        "error": error,
    }


@router.post("/images")
async def upload_images(
    files: list[UploadFile] = File(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """批量上传题目图片(最多 3 张);单张失败不影响其他图片"""
    if not files:
        raise HTTPException(status_code=400, detail="请至少上传一张图片")
    if len(files) > MAX_BATCH_IMAGES:
        raise HTTPException(
            status_code=400,
            detail=f"一次最多上传 {MAX_BATCH_IMAGES} 张图片",
        )

    items: list[dict] = []
    for file in files:
        try:
            items.append(await _process_image(file, user, db))
        except HTTPException as exc:
            items.append({
                "path": "",
                "filename": file.filename or "",
                "size": 0,
                "vision_enabled": vision_enabled(),
                "vlm_enabled": vlm_enabled(),
                "text": "",
                "description": "",
                "error": exc.detail,
            })

    return {
        "items": items,
        "count": len(items),
        "vision_enabled": vision_enabled(),
        "vlm_enabled": vlm_enabled(),
    }


def _user_image_dir(user: User) -> Path:
    return settings.upload_path / "vision" / str(user.id)


@router.get("/images/mine")
def list_my_images(user: User = Depends(get_current_user)):
    """列出本人上传的识图图片(默认保留 30 天,可自助提前删除)"""
    save_dir = _user_image_dir(user)
    items = []
    if save_dir.exists():
        files = sorted(
            (p for p in save_dir.iterdir()
             if p.is_file() and p.suffix.lower() in IMAGE_EXTS),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for path in files:
            stat = path.stat()
            items.append({
                "filename": path.name,
                "size": stat.st_size,
                "created_at": datetime.fromtimestamp(stat.st_mtime).isoformat(
                    timespec="seconds",
                ),
                "path": f"/uploads/vision/{user.id}/{path.name}",
            })
    return {"items": items, "count": len(items)}


@router.delete("/images/mine/{filename}")
def delete_my_image(filename: str, user: User = Depends(get_current_user)):
    """删除本人上传的识图图片,不能操作他人目录"""
    name = Path(filename).name
    if name != filename or Path(name).suffix.lower() not in IMAGE_EXTS:
        raise HTTPException(status_code=404, detail="图片不存在")
    path = _user_image_dir(user) / name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="图片不存在")
    path.unlink()
    return {"deleted": name}


@router.post("/audio/stream-ticket")
def audio_stream_ticket(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """签发实时语音识别票据:浏览器 WebSocket 用查询参数携带"""
    if not asr_enabled():
        raise HTTPException(status_code=400, detail="语音识别未配置")
    assert_audio_upload_allowed(db, user, 0, 0)
    return {
        "ticket": issue_stream_ticket(user),
        "expires_in": 60,
        "model": settings.ASR_REALTIME_MODEL,
    }


@router.websocket("/audio/stream")
async def audio_stream(websocket: WebSocket, token: str = Query("")):
    """实时语音识别:浏览器 PCM 分片 → 百炼实时 ASR → 文本回传"""
    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        user = user_from_stream_ticket(token, db)
    finally:
        db.close()
    if not user:
        await websocket.close(code=4401)
        return
    await websocket.accept()
    await relay_audio_stream(websocket, user)


@router.post("/audio")
async def upload_audio(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """上传录音并转写为文字;识别结果由前端回填输入框,用户确认后再发送"""
    ext = _audio_ext(file)
    if not ext:
        raise HTTPException(
            status_code=400,
            detail="仅支持 WEBM / OGG / MP3 / WAV / M4A / AAC 音频",
        )

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="音频为空")
    if not asr_enabled():
        raise HTTPException(
            status_code=503,
            detail="语音识别未配置，请联系管理员开启 ASR，或直接输入文字",
        )

    save_dir = settings.upload_path / "audio" / str(user.id)
    save_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid.uuid4().hex}{ext}"
    path = save_dir / filename
    path.write_bytes(data)

    duration = _probe_duration(path)
    try:
        assert_audio_upload_allowed(db, user, len(data), duration)
    except HTTPException:
        path.unlink(missing_ok=True)
        raise
    # 通过校验即计入当日用量,防止失败重试绕过限额
    record_audio_upload(db, user, len(data), duration)

    try:
        text = await asyncio.wait_for(
            transcribe_audio(path, filename),
            timeout=settings.ASR_TIMEOUT + 5,
        )
    except asyncio.TimeoutError:
        logger.warning("语音识别超时: user=%s size=%s", user.id, len(data))
        raise HTTPException(status_code=504, detail="语音识别超时，请重试或改用文字输入")
    except ValueError:
        # 麦克风静音/无声或录音太短:这是录制问题,不是识别服务故障
        raise HTTPException(
            status_code=422,
            detail="未检测到语音内容，请确认麦克风未被静音、输入设备选择正确后重新录音",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("语音识别失败: %s", safe_exception(exc))
        raise HTTPException(
            status_code=502,
            detail="语音识别服务暂时不可用，请改用文字输入",
        )
    finally:
        # 录音仅在识别时临时使用,识别结束即删除,不做留存
        path.unlink(missing_ok=True)

    if moderation_enabled(db):
        verdict = screen_with_config(db, text)
        if verdict["flagged"]:
            path.unlink(missing_ok=True)
            record_rejection(db, user.id, text, verdict, "语音识别")
            db.commit()
            raise HTTPException(status_code=400, detail="语音内容未通过审核，请重新录制")

    return {
        "text": text,
        "filename": filename,
        "size": len(data),
        "duration": duration,
    }


CHAT_DOC_EXTS = TEXT_EXTS | CODE_EXTS | DOC_EXTS
CHAT_DOC_TEXT_LIMIT = 8000


@router.post("/documents")
async def upload_document(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """聊天侧文档解析:提取文本供本轮问答使用,解析后立即删除原文件"""
    filename = safe_filename(file.filename or "upload")
    ext = Path(filename).suffix.lower()
    if ext not in CHAT_DOC_EXTS:
        raise HTTPException(
            status_code=400,
            detail=f"仅支持 {SUPPORTED_HINT} 等文档",
        )

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="文件为空")
    if len(data) > settings.CHAT_DOC_MAX_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"文件超过 {settings.CHAT_DOC_MAX_BYTES // 1024 // 1024}MB 上限",
        )

    save_dir = settings.upload_path / "docs" / str(user.id)
    save_dir.mkdir(parents=True, exist_ok=True)
    path = save_dir / f"{uuid.uuid4().hex}{ext}"
    path.write_bytes(data)
    try:
        text = await run_in_threadpool(extract_text, path, filename)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.warning("聊天文档解析失败: %s", safe_exception(exc))
        raise HTTPException(status_code=422, detail="文档解析失败，请换一个文件或直接粘贴文本")
    finally:
        # 聊天附件只在解析时临时使用,不做留存
        path.unlink(missing_ok=True)

    text = (text or "").strip()
    if not text:
        raise HTTPException(status_code=422, detail="未从文档中解析到文本内容")

    if moderation_enabled(db):
        verdict = screen_with_config(db, text)
        if verdict["flagged"]:
            record_rejection(db, user.id, text, verdict, "聊天文档")
            db.commit()
            raise HTTPException(status_code=400, detail="文档内容未通过审核，请更换文件")

    return {
        "filename": filename,
        "size": len(data),
        "chars": len(text),
        "truncated": len(text) > CHAT_DOC_TEXT_LIMIT,
        "text": text[:CHAT_DOC_TEXT_LIMIT],
    }
