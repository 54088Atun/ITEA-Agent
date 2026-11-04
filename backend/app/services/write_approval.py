"""写操作审批与审计(AG-07)

按三级口径统一约束高风险写操作:
- full   完全审批:低风险写入(如 AI 建议批改),直接执行并留痕
- auto   自动审批:规则校验通过后执行(归属/去重/选题校验),留痕
- manual 手动审批:必须二次确认(confirm=true)后才能执行,留痕

所有受控写操作都会写入 write_audits,记录操作人、角色、审批级别、
目标对象与结果;未确认的 manual 操作记录为 blocked,便于事后追溯。
"""
import json
import logging
from dataclasses import dataclass
from typing import Any, Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.log import WriteAuditLog
from app.models.user import User
from app.services.security_levels import LEVEL_LABEL

logger = logging.getLogger(__name__)

TEACHER_ROLES = ("teacher", "admin")


@dataclass(frozen=True)
class WriteAction:
    key: str
    label: str
    level: str
    target_type: str
    roles: tuple[str, ...]


ACTIONS: dict[str, WriteAction] = {
    "assignment.publish": WriteAction(
        "assignment.publish", "发布作业", "manual", "assignment", TEACHER_ROLES,
    ),
    "assignment.close": WriteAction(
        "assignment.close", "关闭作业", "manual", "assignment", TEACHER_ROLES,
    ),
    "assignment.grade_confirm": WriteAction(
        "assignment.grade_confirm", "确认作业成绩", "manual", "submission", TEACHER_ROLES,
    ),
    "assignment.ai_grade": WriteAction(
        "assignment.ai_grade", "AI 建议批改作业", "full", "submission", TEACHER_ROLES,
    ),
    "exam.publish": WriteAction(
        "exam.publish", "发布考试", "manual", "exam", TEACHER_ROLES,
    ),
    "exam.close": WriteAction(
        "exam.close", "关闭考试", "manual", "exam", TEACHER_ROLES,
    ),
    "exam.score_confirm": WriteAction(
        "exam.score_confirm", "确认简答得分", "manual", "exam_record", TEACHER_ROLES,
    ),
    "exam.ai_grade": WriteAction(
        "exam.ai_grade", "AI 简答评分建议", "full", "exam_record", TEACHER_ROLES,
    ),
    "exam.question_adopt": WriteAction(
        "exam.question_adopt", "采纳 AI 题目草稿", "auto", "question_draft", TEACHER_ROLES,
    ),
    "exam.plan_adopt": WriteAction(
        "exam.plan_adopt", "采纳考试科目建议", "auto", "exam_plan_draft", TEACHER_ROLES,
    ),
    "course.kp_adopt": WriteAction(
        "course.kp_adopt", "采纳知识点草稿", "auto", "knowledge_draft", TEACHER_ROLES,
    ),
    "course.share_create": WriteAction(
        "course.share_create", "生成课程分享码", "manual", "course", TEACHER_ROLES,
    ),
    "course.share_revoke": WriteAction(
        "course.share_revoke", "撤销课程分享码", "manual", "course_share", TEACHER_ROLES,
    ),
}


def get_action(key: str) -> WriteAction:
    action = ACTIONS.get(key)
    if action is None:
        raise KeyError(f"未登记的写操作: {key}")
    return action


def action_catalog() -> list[dict]:
    """写操作目录:供接口与前端展示审批级别"""
    return [
        {
            "key": action.key,
            "label": action.label,
            "level": action.level,
            "level_label": LEVEL_LABEL[action.level],
            "target_type": action.target_type,
            "roles": list(action.roles),
        }
        for action in ACTIONS.values()
    ]


def _detail_text(detail: Any) -> Optional[str]:
    if detail is None:
        return None
    if isinstance(detail, str):
        return detail[:2000]
    try:
        return json.dumps(detail, ensure_ascii=False)[:2000]
    except TypeError:
        return str(detail)[:2000]


def _record(
    db: Session,
    user: User,
    action: WriteAction,
    status: str,
    *,
    target_type: Optional[str] = None,
    target_id: Optional[int] = None,
    detail: Any = None,
) -> WriteAuditLog:
    row = WriteAuditLog(
        user_id=user.id,
        user_role=user.role or "",
        action=action.key,
        action_label=action.label,
        approval_mode=action.level,
        status=status,
        target_type=target_type or action.target_type,
        target_id=target_id,
        detail=_detail_text(detail),
    )
    db.add(row)
    return row


def authorize_write(
    db: Session,
    user: User,
    action_key: str,
    *,
    confirmed: bool = False,
    target_type: Optional[str] = None,
    target_id: Optional[int] = None,
    detail: Any = None,
) -> WriteAction:
    """校验角色与审批级别;manual 未确认时记 blocked 并抛 428"""
    action = get_action(action_key)
    if user.role not in action.roles:
        raise HTTPException(status_code=403, detail="当前角色无权执行该操作")
    if action.level == "manual" and not confirmed:
        _record(
            db, user, action, "blocked",
            target_type=target_type, target_id=target_id, detail=detail,
        )
        db.commit()
        logger.info(
            "写操作待确认: user=%s action=%s target=%s/%s",
            user.id, action.key, target_type, target_id,
        )
        raise HTTPException(
            status_code=428,
            detail={
                "code": "confirmation_required",
                "action": action.key,
                "label": action.label,
                "message": f"{action.label}属于手动审批操作，请确认后重试",
            },
        )
    return action


def record_executed(
    db: Session,
    user: User,
    action: WriteAction,
    *,
    target_type: Optional[str] = None,
    target_id: Optional[int] = None,
    detail: Any = None,
) -> WriteAuditLog:
    """记录已执行的写操作;调用方负责随业务一起 commit"""
    return _record(
        db, user, action, "executed",
        target_type=target_type, target_id=target_id, detail=detail,
    )
