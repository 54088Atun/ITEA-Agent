"""通用上传路由:图片识图(可选视觉模型)"""
import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.services.quotas import assert_image_upload_allowed, record_image_upload
from app.services.vision import describe_image, vision_enabled

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/uploads", tags=["上传"])

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


@router.post("/image")
async def upload_image(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """上传题目/板书图片;已配置视觉模型时返回识别文本"""
    mime = (file.content_type or "").lower()
    if mime not in ALLOWED_MIME:
        # 部分客户端不带正确 content-type,退回按扩展名判定
        mime = MIME_BY_EXT.get(Path(file.filename or "").suffix.lower(), "")
    if mime not in ALLOWED_MIME:
        raise HTTPException(status_code=400, detail="仅支持 PNG / JPG / WEBP 图片")

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="图片为空")
    # 能力开关 + 大小 + 每日次数
    assert_image_upload_allowed(db, user, len(data))

    save_dir = settings.upload_path / "vision" / str(user.id)
    save_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid.uuid4().hex}{EXT_BY_MIME.get(mime, '.png')}"
    path = save_dir / filename
    path.write_bytes(data)
    record_image_upload(db, user, len(data))

    text = None
    error = None
    if vision_enabled():
        try:
            text = await describe_image(path, mime)
        except Exception as e:  # noqa: BLE001
            logger.warning("图片识图失败: %s", e)
            error = "识图服务暂时不可用，请手动输入题目内容"

    return {
        "path": f"/uploads/vision/{user.id}/{filename}",
        "filename": filename,
        "size": len(data),
        "vision_enabled": vision_enabled(),
        "text": text or "",
        "error": error,
    }
