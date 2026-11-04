"""上传文件保留期与清理(NF-03)

清理范围:
- uploads/vision/**          识图图片,保留 FILE_RETENTION_DAYS 天
- uploads/audio/**           语音录音,识别完成即删除;此处仅兜底清理异常残留
- uploads/**/drafts/**       解析/草稿临时文件,保留 DRAFT_RETENTION_DAYS 天
- uploads/avatar/**          仅清理「未被任何用户引用」且超期的孤儿头像

课程资料(如 uploads/{course_id}/outline.pdf)属于教学资产,不在清理范围内。
"""
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from app.core.config import settings

logger = logging.getLogger(__name__)

AVATAR_PREFIX = "/uploads/avatar/"


def _cutoff(now: datetime, days: int) -> float:
    return (now - timedelta(days=max(1, days))).timestamp()


def _remove(path: Path, category: str, stats: dict) -> bool:
    try:
        size = path.stat().st_size
        path.unlink()
    except OSError as exc:
        logger.warning("删除失败 %s: %s", path, exc)
        return False
    stats["deleted"] += 1
    stats["freed_bytes"] += size
    stats["by_category"][category] = stats["by_category"].get(category, 0) + 1
    return True


def _prune_empty_dirs(root: Path) -> None:
    if not root.exists():
        return
    for path in sorted(root.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        if path.is_dir():
            try:
                next(path.iterdir())
            except StopIteration:
                path.rmdir()
            except OSError:
                continue


def _referenced_avatars() -> set[str]:
    from app.db.session import SessionLocal
    from app.models.user import User

    db = SessionLocal()
    try:
        rows = db.query(User.avatar_url).filter(User.avatar_url.isnot(None)).all()
        return {Path(url).name for (url,) in rows if url}
    except Exception as exc:  # noqa: BLE001
        logger.warning("读取头像引用失败,跳过头像清理: %s", exc)
        return set()
    finally:
        db.close()


def cleanup_uploads(
    now: Optional[datetime] = None,
    upload_dir: Optional[Path] = None,
    referenced_avatars: Optional[set[str]] = None,
) -> dict:
    """删除超过保留期的上传文件,返回统计信息"""
    now = now or datetime.utcnow()
    root = Path(upload_dir or settings.upload_path)
    stats = {"deleted": 0, "freed_bytes": 0, "by_category": {}}

    file_cutoff = _cutoff(now, settings.FILE_RETENTION_DAYS)
    draft_cutoff = _cutoff(now, settings.DRAFT_RETENTION_DAYS)

    for category in ("vision", "audio"):
        base = root / category
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if path.is_file() and path.stat().st_mtime < file_cutoff:
                _remove(path, category, stats)
        _prune_empty_dirs(base)

    for path in root.rglob("*"):
        if path.is_file() and "drafts" in path.parts and path.stat().st_mtime < draft_cutoff:
            _remove(path, "drafts", stats)

    avatar_dir = root / "avatar"
    if avatar_dir.exists():
        referenced = referenced_avatars
        if referenced is None:
            referenced = _referenced_avatars()
        for path in avatar_dir.rglob("*"):
            if not path.is_file() or path.name in referenced:
                continue
            if path.stat().st_mtime < draft_cutoff:
                _remove(path, "avatar", stats)
        _prune_empty_dirs(avatar_dir)

    if stats["deleted"]:
        logger.info(
            "上传文件清理完成: %s 个文件, 释放 %.1f KB, 分类=%s",
            stats["deleted"], stats["freed_bytes"] / 1024, stats["by_category"],
        )
    return stats


def cleanup_uploads_task() -> dict:
    """调度器入口:异常不外抛,避免拖垮后台任务"""
    try:
        return cleanup_uploads()
    except Exception as exc:  # noqa: BLE001
        logger.error("上传文件清理失败: %s", exc)
        return {"deleted": 0, "freed_bytes": 0, "by_category": {}, "error": str(exc)}
