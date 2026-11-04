"""admin.*:管理端只读工具(P0-5)

把管理助手原来固定读取的平台快照拆成按需查询的只读工具,
模型可以组合多个工具回答跨表问题,写操作仍走 ADMIN_ACTIONS 预览与审计。

安全边界:
- 仅 admin 角色可调用(由角色能力矩阵与 tool_executor 双重拦截)
- 只返回聚合结果与标识字段,不返回密码、邮箱、风险原文等隐私内容
- 单次返回条数上限 50,避免把整库数据塞进上下文
"""
import logging
from datetime import datetime, timedelta

from sqlalchemy import func, or_

from app.db.session import SessionLocal
from app.models.course import Course, CourseMaterial, KnowledgePoint
from app.models.log import RiskLog, SystemConfig
from app.models.user import User

logger = logging.getLogger(__name__)

MAX_LIMIT = 50
DEFAULT_LIMIT = 10
SENSITIVE_KEYWORDS = ("password", "secret", "key", "token", "credential")


def _limit(value, default: int = DEFAULT_LIMIT) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(1, min(number, MAX_LIMIT))


def _int_list(value) -> list[int]:
    if not isinstance(value, (list, tuple)):
        return []
    ids = []
    for item in value:
        try:
            ids.append(int(item))
        except (TypeError, ValueError):
            continue
    return ids[:MAX_LIMIT]


def _iso(value) -> str | None:
    return value.isoformat(sep=" ") if value else None


def admin_course_list(
    audit_status: str | None = None,
    keyword: str | None = None,
    limit: int = DEFAULT_LIMIT,
) -> dict:
    """按审核状态/关键词查询课程,带素材数与知识点数"""
    db = SessionLocal()
    try:
        query = db.query(Course).filter(Course.deleted_at.is_(None))
        if audit_status in ("pending", "approved", "rejected"):
            query = query.filter(Course.audit_status == audit_status)
        if keyword:
            like = f"%{keyword}%"
            query = query.filter(or_(Course.name.like(like), Course.code.like(like)))

        total = query.count()
        rows = query.order_by(Course.id.desc()).limit(_limit(limit)).all()
        ids = [course.id for course in rows]

        material_counts: dict[int, int] = {}
        point_counts: dict[int, int] = {}
        teacher_names: dict[int, str] = {}
        if ids:
            material_counts = dict(
                db.query(CourseMaterial.course_id, func.count(CourseMaterial.id))
                .filter(CourseMaterial.course_id.in_(ids))
                .group_by(CourseMaterial.course_id)
                .all()
            )
            point_counts = dict(
                db.query(KnowledgePoint.course_id, func.count(KnowledgePoint.id))
                .filter(KnowledgePoint.course_id.in_(ids))
                .group_by(KnowledgePoint.course_id)
                .all()
            )
            teacher_ids = {course.teacher_id for course in rows}
            teacher_names = dict(
                db.query(User.id, User.name).filter(User.id.in_(teacher_ids)).all()
            )

        return {
            "total": total,
            "items": [
                {
                    "course_id": course.id,
                    "name": course.name,
                    "code": course.code,
                    "audit_status": course.audit_status,
                    "teacher_id": course.teacher_id,
                    "teacher_name": teacher_names.get(course.teacher_id),
                    "materials": material_counts.get(course.id, 0),
                    "knowledge_points": point_counts.get(course.id, 0),
                    "created_at": _iso(course.created_at),
                }
                for course in rows
            ],
        }
    finally:
        db.close()


def admin_material_stats(
    course_ids: list[int] | None = None,
    limit: int = 20,
) -> dict:
    """按课程统计素材与知识点数量,默认按素材数升序,便于定位素材最少的课程"""
    db = SessionLocal()
    try:
        query = db.query(Course).filter(Course.deleted_at.is_(None))
        ids = _int_list(course_ids)
        if ids:
            query = query.filter(Course.id.in_(ids))
        rows = query.order_by(Course.id.desc()).limit(_limit(limit)).all()

        course_ids = [course.id for course in rows]
        material_counts: dict[int, int] = {}
        point_counts: dict[int, int] = {}
        if course_ids:
            material_counts = dict(
                db.query(CourseMaterial.course_id, func.count(CourseMaterial.id))
                .filter(CourseMaterial.course_id.in_(course_ids))
                .group_by(CourseMaterial.course_id)
                .all()
            )
            point_counts = dict(
                db.query(KnowledgePoint.course_id, func.count(KnowledgePoint.id))
                .filter(KnowledgePoint.course_id.in_(course_ids))
                .group_by(KnowledgePoint.course_id)
                .all()
            )

        items = [
            {
                "course_id": course.id,
                "name": course.name,
                "audit_status": course.audit_status,
                "materials": material_counts.get(course.id, 0),
                "knowledge_points": point_counts.get(course.id, 0),
            }
            for course in rows
        ]
        items.sort(key=lambda item: (item["materials"], item["course_id"]))
        return {"total": len(items), "items": items}
    finally:
        db.close()


def admin_user_lookup(
    keyword: str | None = None,
    role: str | None = None,
    status: str | None = None,
    limit: int = DEFAULT_LIMIT,
) -> dict:
    """按角色/状态/关键词查询账号,不返回邮箱与密码等隐私字段"""
    db = SessionLocal()
    try:
        query = db.query(User)
        if role in ("teacher", "student", "admin"):
            query = query.filter(User.role == role)
        if status in ("active", "disabled"):
            query = query.filter(User.status == status)
        if keyword:
            like = f"%{keyword}%"
            query = query.filter(User.name.like(like))

        total = query.count()
        rows = query.order_by(User.id.desc()).limit(_limit(limit)).all()
        return {
            "total": total,
            "items": [
                {
                    "user_id": user.id,
                    "name": user.name,
                    "role": user.role,
                    "admin_level": user.admin_level,
                    "status": user.status,
                    "created_at": _iso(user.created_at),
                }
                for user in rows
            ],
        }
    finally:
        db.close()


def admin_risk_summary(days: int = 7) -> dict:
    """近 N 天风控命中总览:类型分布 + 最近命中(不含请求原文)"""
    try:
        window = max(1, min(int(days), 90))
    except (TypeError, ValueError):
        window = 7
    since = datetime.utcnow() - timedelta(days=window)

    db = SessionLocal()
    try:
        query = db.query(RiskLog).filter(RiskLog.created_at >= since)
        total = query.count()
        by_type = dict(
            db.query(RiskLog.risk_type, func.count(RiskLog.id))
            .filter(RiskLog.created_at >= since)
            .group_by(RiskLog.risk_type)
            .all()
        )
        recent = query.order_by(RiskLog.id.desc()).limit(5).all()
        return {
            "days": window,
            "total": total,
            "by_type": by_type,
            "recent": [
                {
                    "risk_id": row.id,
                    "user_id": row.user_id,
                    "risk_type": row.risk_type,
                    "action_taken": row.action_taken,
                    "created_at": _iso(row.created_at),
                }
                for row in recent
            ],
        }
    finally:
        db.close()


def admin_config_get(key: str | None = None) -> dict:
    """读取系统配置项;命中敏感词的键只返回掩码,不返回明文值"""
    db = SessionLocal()
    try:
        query = db.query(SystemConfig)
        if key:
            query = query.filter(SystemConfig.config_key == key)
        rows = query.order_by(SystemConfig.config_key).limit(MAX_LIMIT).all()

        items = []
        for row in rows:
            sensitive = any(
                word in (row.config_key or "").lower() for word in SENSITIVE_KEYWORDS
            )
            items.append({
                "key": row.config_key,
                "value": "***" if sensitive else row.config_value,
                "sensitive": sensitive,
            })
        return {"total": len(items), "items": items}
    finally:
        db.close()
