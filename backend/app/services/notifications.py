"""持久化通知、目标学生触达与免打扰投递"""
from datetime import datetime, time, timedelta
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.time import normalize_seconds, utcnow
from app.models.classroom import ClassMember, CourseEnrollment
from app.models.notification import Notification, NotificationPreference

CATEGORIES = ("assignment", "exam", "interview", "review")


def get_preferences(
    db: Session, user_id: int, create: bool = False,
) -> NotificationPreference:
    pref = db.query(NotificationPreference).filter_by(user_id=user_id).first()
    if pref or not create:
        return pref or NotificationPreference(user_id=user_id)
    pref = NotificationPreference(user_id=user_id)
    db.add(pref)
    db.flush()
    return pref


def preference_out(pref: NotificationPreference) -> dict:
    return {
        "assignment_enabled": pref.assignment_enabled is not False,
        "exam_enabled": pref.exam_enabled is not False,
        "interview_enabled": pref.interview_enabled is not False,
        "review_enabled": pref.review_enabled is not False,
        "quiet_start": pref.quiet_start,
        "quiet_end": pref.quiet_end,
    }


def update_preferences(db: Session, user_id: int, req) -> dict:
    pref = get_preferences(db, user_id, create=True)
    for category in CATEGORIES:
        setattr(pref, f"{category}_enabled", getattr(req, f"{category}_enabled"))
    pref.quiet_start = req.quiet_start or None
    pref.quiet_end = req.quiet_end or None
    pref.updated_at = utcnow()
    db.flush()
    return preference_out(pref)


def _minutes(value: str) -> int:
    hour, minute = value.split(":")
    return int(hour) * 60 + int(minute)


def _delivery_time(pref: NotificationPreference, now: datetime) -> datetime:
    if not pref.quiet_start or not pref.quiet_end:
        return now
    start = _minutes(pref.quiet_start)
    end = _minutes(pref.quiet_end)
    if start == end:
        return now
    current = now.hour * 60 + now.minute
    in_quiet = (
        start <= current < end if start < end
        else current >= start or current < end
    )
    if not in_quiet:
        return now
    end_time = time(end // 60, end % 60)
    day = now.date() if current < end else now.date() + timedelta(days=1)
    return datetime.combine(day, end_time)


def create_notification(
    db: Session,
    user_id: int,
    category: str,
    title: str,
    message: str,
    link_url: Optional[str],
    source_type: str,
    source_id: str,
    target_at: Optional[datetime] = None,
) -> Optional[Notification]:
    """按来源幂等写入;分类关闭时跳过,免打扰时延迟可见

    target_at 为期望触达时间(naive UTC):通知不会早于该时间可见,
    且该时间同样参与免打扰计算。
    """
    existing = db.query(Notification).filter_by(
        user_id=user_id, source_type=source_type, source_id=str(source_id),
    ).first()
    if existing:
        return existing
    pref = get_preferences(db, user_id)
    if category not in CATEGORIES or getattr(pref, f"{category}_enabled") is False:
        return None
    # MySQL 无小数秒 DATETIME 会四舍五入,避免即时通知被延迟到下一秒
    now = utcnow()
    base = now
    if target_at is not None:
        base = max(normalize_seconds(target_at), now)
    row = Notification(
        user_id=user_id,
        category=category,
        title=title[:200],
        message=message[:4000],
        link_url=link_url,
        source_type=source_type,
        source_id=str(source_id),
        is_read=False,
        deliver_at=_delivery_time(pref, base),
        created_at=now,
    )
    db.add(row)
    db.flush()
    return row


def notify_task_students(
    db: Session,
    category: str,
    source_id: int,
    title: str,
    course_id: Optional[int],
    class_id: Optional[int],
    link_url: str,
) -> int:
    """复用任务可见性:班级任务只触达 active 成员,课程任务触达选课学生"""
    if class_id is not None:
        user_ids = [row[0] for row in db.query(ClassMember.student_id).filter(
            ClassMember.class_id == class_id,
            ClassMember.status == "active",
        ).all()]
    elif course_id is not None:
        user_ids = [row[0] for row in db.query(CourseEnrollment.student_id).filter(
            CourseEnrollment.course_id == course_id,
        ).all()]
    else:
        user_ids = []

    labels = {"assignment": "作业", "exam": "考试", "interview": "面试"}
    created = 0
    for user_id in set(user_ids):
        row = create_notification(
            db=db,
            user_id=user_id,
            category=category,
            title=f"新{labels.get(category, '学习')}任务：{title}",
            message=f"教师发布了新{labels.get(category, '学习')}任务“{title}”，请及时查看。",
            link_url=link_url,
            source_type=category,
            source_id=str(source_id),
        )
        if row is not None:
            created += 1
    return created


def notification_out(row: Notification) -> dict:
    return {
        "id": row.id,
        "category": row.category,
        "task_type": row.category,
        "title": row.title,
        "message": row.message,
        "link_url": row.link_url,
        "source_type": row.source_type,
        "source_id": row.source_id,
        "is_read": bool(row.is_read),
        "read_at": row.read_at,
        "deliver_at": row.deliver_at,
        "created_at": row.created_at,
        "timestamp": row.created_at.isoformat() if row.created_at else None,
    }


def list_notifications(
    db: Session,
    user_id: int,
    unread_only: bool = False,
    category: Optional[str] = None,
) -> dict:
    delivered = db.query(Notification).filter(
        Notification.user_id == user_id,
        Notification.deliver_at <= utcnow(),
    )
    unread_count = delivered.filter(Notification.is_read.is_(False)).count()
    query = delivered
    if unread_only:
        query = query.filter(Notification.is_read.is_(False))
    if category in CATEGORIES:
        query = query.filter(Notification.category == category)
    rows = query.order_by(Notification.created_at.desc(), Notification.id.desc()).limit(100).all()
    return {
        "notifications": [notification_out(row) for row in rows],
        "unread_count": unread_count,
    }


def mark_notification_read(db: Session, user_id: int, notification_id: int) -> dict:
    row = db.query(Notification).filter_by(id=notification_id, user_id=user_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="通知不存在")
    if not row.is_read:
        row.is_read = True
        row.read_at = utcnow()
    db.flush()
    return notification_out(row)


def mark_all_notifications_read(db: Session, user_id: int) -> int:
    rows = db.query(Notification).filter_by(user_id=user_id, is_read=False).all()
    now = utcnow()
    for row in rows:
        row.is_read = True
        row.read_at = now
    db.flush()
    return len(rows)
