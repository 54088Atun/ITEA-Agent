"""上传配额:图片/语音的大小、次数、时长与能力开关

限额从 system_config 读取(见 feature_flags.FEATURE_DEFAULTS),
教师/管理员按角色倍数放宽,0 表示不限。
"""
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.upload_event import UploadEvent
from app.models.user import User
from app.services.feature_flags import get_int, is_enabled

# 角色配额倍数:学生 1x,教师 2x,管理员 4x
ROLE_MULTIPLIER = {"student": 1, "teacher": 2, "admin": 4}


def _scaled(limit: int, user: User) -> int:
    if limit <= 0:
        return 0
    return limit * ROLE_MULTIPLIER.get(getattr(user, "role", ""), 1)


def _day_start() -> datetime:
    return datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)


def assert_image_upload_allowed(db: Session, user: User, size: int) -> None:
    """校验图片上传:开关 / 大小 / 当日次数,不通过直接抛 4xx"""
    if not is_enabled(db, "feature_image_vision"):
        raise HTTPException(status_code=403, detail="图片识图功能已关闭，请联系管理员")

    max_mb = max(1, min(get_int(db, "upload_image_max_mb", 8), 8))
    if size > max_mb * 1024 * 1024:
        raise HTTPException(
            status_code=400, detail=f"图片过大，请压缩后再上传（上限 {max_mb}MB）",
        )

    daily_limit = _scaled(get_int(db, "vision_daily_limit", 30), user)
    if daily_limit > 0:
        used = db.query(func.count(UploadEvent.id)).filter(
            UploadEvent.user_id == user.id,
            UploadEvent.kind == "image",
            UploadEvent.created_at >= _day_start(),
        ).scalar() or 0
        if used >= daily_limit:
            raise HTTPException(
                status_code=429,
                detail=f"今日识图次数已达上限（{daily_limit} 次），请明日再试",
            )


def record_image_upload(db: Session, user: User, size: int) -> None:
    db.add(UploadEvent(user_id=user.id, kind="image", size=size, duration_seconds=0))
    db.commit()


def assert_audio_upload_allowed(
    db: Session, user: User, size: int, duration: float = 0,
) -> None:
    """校验语音上传:开关 / 大小 / 单次时长 / 当日次数与总时长"""
    if not is_enabled(db, "feature_asr"):
        raise HTTPException(status_code=403, detail="语音识别功能已关闭，请联系管理员")

    max_mb = max(1, min(get_int(db, "asr_max_mb", 10), 50))
    if size > max_mb * 1024 * 1024:
        raise HTTPException(status_code=400, detail=f"音频不能超过 {max_mb}MB，请缩短录音")

    max_seconds = get_int(db, "asr_max_seconds", 300)
    if max_seconds > 0 and duration > max_seconds:
        raise HTTPException(
            status_code=400,
            detail=f"单次语音不能超过 {max_seconds} 秒，请分段上传",
        )

    day_start = _day_start()
    daily_limit = _scaled(get_int(db, "asr_daily_limit", 50), user)
    if daily_limit > 0:
        used = db.query(func.count(UploadEvent.id)).filter(
            UploadEvent.user_id == user.id,
            UploadEvent.kind == "audio",
            UploadEvent.created_at >= day_start,
        ).scalar() or 0
        if used >= daily_limit:
            raise HTTPException(
                status_code=429,
                detail=f"今日语音识别次数已达上限（{daily_limit} 次），请明日再试",
            )

    daily_seconds = _scaled(get_int(db, "asr_daily_seconds", 1800), user)
    if daily_seconds > 0 and duration > 0:
        used_seconds = db.query(func.coalesce(func.sum(UploadEvent.duration_seconds), 0)).filter(
            UploadEvent.user_id == user.id,
            UploadEvent.kind == "audio",
            UploadEvent.created_at >= day_start,
        ).scalar() or 0
        if float(used_seconds) + duration > daily_seconds:
            remaining = max(0, int(daily_seconds - float(used_seconds)))
            raise HTTPException(
                status_code=429,
                detail=(
                    f"今日语音识别时长已达上限（{daily_seconds // 60} 分钟），"
                    f"剩余约 {remaining} 秒，请明日再试"
                ),
            )


def record_audio_upload(
    db: Session, user: User, size: int, duration: float = 0,
) -> None:
    db.add(UploadEvent(
        user_id=user.id, kind="audio", size=size, duration_seconds=max(0.0, duration),
    ))
    db.commit()
