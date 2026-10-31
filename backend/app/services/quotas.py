"""上传配额:图片大小、每日次数、能力开关"""
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.upload_event import UploadEvent
from app.models.user import User
from app.services.feature_flags import get_int, is_enabled


def assert_image_upload_allowed(db: Session, user: User, size: int) -> None:
    """校验图片上传:开关 / 大小 / 当日次数,不通过直接抛 4xx"""
    if not is_enabled(db, "feature_image_vision"):
        raise HTTPException(status_code=403, detail="图片识图功能已关闭，请联系管理员")

    max_mb = max(1, min(get_int(db, "upload_image_max_mb", 8), 20))
    if size > max_mb * 1024 * 1024:
        raise HTTPException(status_code=400, detail=f"图片不能超过 {max_mb}MB")

    daily_limit = get_int(db, "vision_daily_limit", 30)
    if daily_limit > 0:
        day_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        used = db.query(func.count(UploadEvent.id)).filter(
            UploadEvent.user_id == user.id,
            UploadEvent.kind == "image",
            UploadEvent.created_at >= day_start,
        ).scalar() or 0
        if used >= daily_limit:
            raise HTTPException(
                status_code=429,
                detail=f"今日识图次数已达上限（{daily_limit} 次），请明日再试",
            )


def record_image_upload(db: Session, user: User, size: int) -> None:
    db.add(UploadEvent(user_id=user.id, kind="image", size=size))
    db.commit()
