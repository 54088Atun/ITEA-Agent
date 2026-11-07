"""reminder_scheduler:定时提醒调度(APScheduler)

实现要点:
- 基于 APScheduler 后台任务,定时扫描到期的复习计划
- 到点向前端推送 SSE 通知(通过全局通知队列)
- MVP:单进程内存调度,生产可换 Redis 队列
"""
import logging
import asyncio
from datetime import datetime

from app.core.time import to_utc_naive, utcnow
from app.services.notifications import create_notification

logger = logging.getLogger(__name__)

# 全局通知队列:SSE 端点从此读取推送给前端
# {user_id: [(task_type, message, timestamp), ...]}
_notification_queue: dict[int, list[dict]] = {}

_scheduler_started = False
# 已通知的计划 ID 集合(避免重复推送,内存级 MVP 方案)
_notified_plan_ids: set[int] = set()


def push_notification(user_id: int, task_type: str, message: str):
    """向指定用户的通知队列推送一条消息"""
    if user_id not in _notification_queue:
        _notification_queue[user_id] = []
    _notification_queue[user_id].append({
        "task_type": task_type,
        "message": message,
        "timestamp": utcnow().isoformat(),
    })
    # 队列上限 50 条,防止溢出
    if len(_notification_queue[user_id]) > 50:
        _notification_queue[user_id] = _notification_queue[user_id][-50:]
    logger.info("通知已入队(user=%s, type=%s)", user_id, task_type)


def pop_notifications(user_id: int) -> list[dict]:
    """取出并清空该用户的待推送通知(SSE 端点调用)"""
    return _notification_queue.pop(user_id, [])


def _scan_due_reviews():
    """扫描到期复习计划并入队通知(由 APScheduler 定时调用)"""
    from sqlalchemy import select
    from app.db.session import SessionLocal
    from app.models.profile import ReviewPlan, WrongQuestion, StudentProfile
    from app.services.notifications import create_notification

    db = SessionLocal()
    pushed = 0
    try:
        now = utcnow()
        due_plans = db.execute(
            select(ReviewPlan).where(
                ReviewPlan.status == "pending",
                ReviewPlan.next_review_at <= now,
            ).limit(100)
        ).scalars().all()

        for plan in due_plans:
            if plan.id in _notified_plan_ids:
                continue  # 已通知过,跳过
            # 通过 错题→学情档案→用户 获取 user_id
            wq = db.query(WrongQuestion).filter(WrongQuestion.id == plan.wrong_question_id).first()
            if not wq:
                continue
            profile = db.query(StudentProfile).filter(StudentProfile.id == wq.profile_id).first()
            if not profile:
                continue
            row = create_notification(
                db=db,
                user_id=profile.user_id,
                category="review",
                title="错题复习提醒",
                message="你有一条错题复习计划已到期，快去复盘吧！",
                link_url="/student/review",
                source_type="review_plan",
                source_id=str(plan.id),
            )
            if row is not None:
                _notified_plan_ids.add(plan.id)
                pushed += 1

        db.commit()
        if pushed:
            logger.info("复习提醒扫描完成,推送 %d 条通知", pushed)
    except Exception as e:
        db.rollback()
        logger.error("复习提醒扫描失败: %s", e)
    finally:
        db.close()


def start_scheduler():
    """启动 APScheduler 后台调度器(应用启动时调用一次)"""
    global _scheduler_started
    if _scheduler_started:
        return

    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from app.core.config import settings
        from app.services.storage_cleanup import cleanup_uploads_task

        scheduler = BackgroundScheduler()
        # 每 5 分钟扫描一次到期复习计划
        scheduler.add_job(
            _scan_due_reviews,
            "interval",
            minutes=5,
            id="review_reminder",
            replace_existing=True,
        )
        # 每日定时清理超期上传文件
        scheduler.add_job(
            cleanup_uploads_task,
            "cron",
            hour=settings.CLEANUP_HOUR,
            minute=settings.CLEANUP_MINUTE,
            id="cleanup_uploads",
            replace_existing=True,
        )
        scheduler.start()
        _scheduler_started = True
        logger.info(
            "提醒调度器已启动(每 5 分钟扫描复习计划;每日 %02d:%02d 清理上传文件)",
            settings.CLEANUP_HOUR, settings.CLEANUP_MINUTE,
        )
    except Exception as e:
        logger.error("调度器启动失败(提醒功能降级): %s", e)


REMINDER_MESSAGES = {
    "review": "已为你安排错题复习提醒,到期将自动通知你复盘。",
    "interview": "已为你安排面试实训提醒,请按时参加模拟面试。",
}

REMINDER_LINKS = {
    "review": "/student/review",
    "interview": "/student/interview",
}


def _parse_trigger_at(value: str) -> tuple[datetime | None, str]:
    """解析带时区的 ISO 时间为 naive UTC;空值表示立即提醒"""
    text = str(value or "").strip()
    if not text:
        return utcnow(), ""
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None, "invalid_trigger_at"
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None, "missing_timezone"
    return to_utc_naive(parsed), ""


def reminder_scheduler(
    user_id: int,
    task_type: str = "review",
    trigger_at: str = "",
) -> dict:
    """定时提醒工具

    Args:
        user_id: 用户 ID
        task_type: 任务类型(review/interview)
        trigger_at: 触发时间(带时区 ISO,如 2026-11-05T09:00:00+08:00)

    Returns:
        写入成功才返回 scheduled=true,并给出数据库实际 deliver_at。
    """
    if task_type not in REMINDER_MESSAGES:
        return {
            "scheduled": False,
            "task_type": task_type,
            "reason": "unsupported_task_type",
            "message": "仅支持 review 或 interview 提醒。",
        }
    target, error = _parse_trigger_at(trigger_at)
    msg = REMINDER_MESSAGES[task_type]
    if error:
        return {
            "scheduled": False,
            "task_type": task_type,
            "reason": error,
            "message": "触发时间必须为带时区的 ISO 时间。",
        }

    # 同一任务同一触发时间重试时命中唯一约束,不重复写入
    slot = (
        f"immediate:{target.date().isoformat()}"
        if not str(trigger_at or "").strip()
        else target.isoformat()
    )
    source_id = f"{task_type}:{slot}"

    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        row = create_notification(
            db=db,
            user_id=user_id,
            category=task_type,
            title="学习提醒",
            message=msg,
            link_url=REMINDER_LINKS[task_type],
            source_type="agent_reminder",
            source_id=source_id,
            target_at=target,
        )
        if row is None:
            db.rollback()
            return {
                "scheduled": False,
                "task_type": task_type,
                "reason": "category_disabled",
                "message": "该类提醒已在通知设置中关闭。",
            }
        db.commit()
        logger.info(
            "提醒已排期(user=%s, type=%s, deliver_at=%s)",
            user_id, task_type, row.deliver_at.isoformat(),
        )
        return {
            "scheduled": True,
            "task_type": task_type,
            "trigger_at": target.isoformat() + "Z",
            "deliver_at": row.deliver_at.isoformat() + "Z",
            "message": msg,
        }
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.error("提醒写入失败(user=%s, type=%s): %s", user_id, task_type, exc)
        return {
            "scheduled": False,
            "task_type": task_type,
            "reason": "persist_failed",
            "message": "提醒保存失败,请稍后重试。",
        }
    finally:
        db.close()