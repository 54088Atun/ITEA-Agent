"""检索能力判定:课程资料存在且索引就绪时,才允许发起课程检索。"""
import logging

from app.db.session import SessionLocal
from app.models.course import CourseMaterial

logger = logging.getLogger(__name__)


def retrieval_available(course_id: int | None) -> bool:
    """课程是否有可检索资料与索引。

    返回 False 时,Agent 跳过强制检索并隐藏检索工具,避免每轮先做一次
    注定失败的检索(线上索引未配置时单轮白付 8-10 秒)。
    """
    if not course_id:
        return False
    try:
        db = SessionLocal()
        try:
            has_material = db.query(CourseMaterial.id).filter(
                CourseMaterial.course_id == course_id,
            ).first() is not None
        finally:
            db.close()
    except Exception as exc:  # noqa: BLE001
        # 能力检查失败时不误伤既有检索能力
        logger.warning("检索能力检查失败，按可用处理: %s", exc)
        return True
    if not has_material:
        return False
    from app.agent.tools.rag_search import index_ready
    return index_ready(course_id)
