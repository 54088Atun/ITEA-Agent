"""管理端操作审计:统一写入 operation_logs"""
import logging
from typing import Optional

from sqlalchemy.orm import Session

from app.models.log import OperationLog
from app.models.user import User

logger = logging.getLogger(__name__)


def write_operation_log(
    db: Session,
    admin: User,
    action: str,
    target_type: str,
    target_id: Optional[int] = None,
    detail: Optional[str] = None,
    ip: Optional[str] = None,
    commit: bool = True,
) -> Optional[OperationLog]:
    """写入一条操作审计日志(日志失败不阻断业务)"""
    try:
        log = OperationLog(
            admin_id=admin.id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            detail=detail[:2000] if detail else None,
            ip=ip,
        )
        db.add(log)
        if commit:
            db.commit()
        else:
            db.flush()
        return log
    except Exception as e:
        db.rollback()
        logger.warning("操作日志写入失败: %s", e)
        return None
