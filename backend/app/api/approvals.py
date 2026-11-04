"""写操作审批目录与审计查询(AG-07)"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.log import WriteAuditLog
from app.models.user import User
from app.services.security_levels import LEVEL_DESC, LEVEL_LABEL
from app.services.write_approval import action_catalog

router = APIRouter(prefix="/approvals", tags=["审批与审计"])


@router.get("/actions")
def list_actions(user: User = Depends(get_current_user)):
    """写操作目录:每个操作对应的审批级别与可用角色"""
    items = action_catalog()
    return {
        "items": items,
        "total": len(items),
        "levels": [
            {"key": key, "label": LEVEL_LABEL[key], "description": LEVEL_DESC[key]}
            for key in ("full", "auto", "manual")
        ],
    }


@router.get("/logs")
def list_logs(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    scope: str = Query("me", pattern="^(me|all)$"),
    action: Optional[str] = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """写操作审计:默认看自己的记录;管理员可传 scope=all 查看全部"""
    if scope == "all" and user.role != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可查看全部审计")

    query = db.query(WriteAuditLog, User).outerjoin(
        User, WriteAuditLog.user_id == User.id,
    )
    if not (scope == "all" and user.role == "admin"):
        query = query.filter(WriteAuditLog.user_id == user.id)
    if action:
        query = query.filter(WriteAuditLog.action == action)

    total = query.count()
    rows = (
        query.order_by(WriteAuditLog.id.desc())
        .offset((page - 1) * size)
        .limit(size)
        .all()
    )
    return {
        "items": [
            {
                "id": row.id,
                "user_id": row.user_id,
                "user_name": owner.name if owner else None,
                "user_role": row.user_role,
                "action": row.action,
                "action_label": row.action_label,
                "approval_mode": row.approval_mode,
                "approval_label": LEVEL_LABEL.get(row.approval_mode, row.approval_mode),
                "status": row.status,
                "target_type": row.target_type,
                "target_id": row.target_id,
                "detail": row.detail,
                "created_at": row.created_at,
            }
            for row, owner in rows
        ],
        "total": total,
        "page": page,
        "size": size,
    }
