"""reminder_scheduler:定时提醒调度(APScheduler)

实现要点:
- 基于 APScheduler 后台任务,定时扫描到期的复习计划
- 到点向前端推送 SSE 通知(通过全局通知队列)
- MVP:单进程内存调度,生产可换 Redis 队列
"""
import logging
import asyncio
from datetime import datetime

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
        "timestamp": datetime.utcnow().isoformat(),
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
        now = datetime.utcnow()
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

        scheduler = BackgroundScheduler()
        # 每 5 分钟扫描一次到期复习计划
        scheduler.add_job(
            _scan_due_reviews,
            "interval",
            minutes=5,
            id="review_reminder",
            replace_existing=True,
        )
        scheduler.start()
        _scheduler_started = True
        logger.info("提醒调度器已启动(每 5 分钟扫描到期复习计划)")
    except Exception as e:
        logger.error("调度器启动失败(提醒功能降级): %s", e)


def reminder_scheduler(
    user_id: int,
    task_type: str = "review",
    trigger_at: str = "",
) -> dict:
    """定时提醒工具

    Args:
        user_id: 用户 ID
        task_type: 任务类型(review/interview)
        trigger_at: 触发时间(ISO 格式,MVP 直接即时入队)

    Returns:
        {"scheduled": true, "task_type": ..., "message": ...}
    """
    messages = {
        "review": "已为你安排错题复习提醒,到期将自动通知你复盘。",
        "interview": "已为你安排面试实训提醒,请按时参加模拟面试。",
    }
    msg = messages.get(task_type, f"已为你安排 {task_type} 提醒。")

    # MVP:直接入队即时通知;生产环境应写入调度系统按 trigger_at 延时推送
    push_notification(user_id, task_type, msg)

    return {
        "scheduled": True,
        "task_type": task_type,
        "trigger_at": trigger_at,
        "message": msg,
    }