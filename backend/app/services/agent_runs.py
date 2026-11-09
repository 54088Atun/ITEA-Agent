"""Agent 运行记录:写入、结束与查询

运行记录独立于请求会话写入,客户端断开后仍能落库,
供管理端回放路由、工具调用、反思与耗时。
"""
import json
import logging
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.log import AgentDeadLetter, AgentPlanRevision, AgentRun

logger = logging.getLogger(__name__)

MAX_PREVIEW = 4000
MAX_STEPS = 80


def _preview(text: Optional[str], limit: int = MAX_PREVIEW) -> str:
    value = str(text or "")
    return value if len(value) <= limit else value[:limit] + "..."


def start_run(
    user_id: int,
    role: str,
    session_id: str,
    request_id: Optional[str],
    message: str,
) -> Optional[int]:
    """创建一条 running 记录;失败不影响主对话"""
    db = SessionLocal()
    try:
        run = AgentRun(
            user_id=user_id,
            role=role,
            session_id=session_id,
            request_id=request_id,
            status="running",
            input_preview=_preview(message, 500),
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        return run.id
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.warning("Agent 运行记录创建失败: %s", exc)
        return None
    finally:
        db.close()


def finish_run(
    run_id: Optional[int],
    *,
    status: str,
    branch: Optional[str],
    output: str,
    error: str,
    steps: list[dict],
    duration_ms: int,
) -> None:
    """结束运行记录;独立会话写入,避免请求会话关闭后丢失"""
    if not run_id:
        return
    db = SessionLocal()
    try:
        run = db.query(AgentRun).filter(AgentRun.id == run_id).first()
        if not run:
            return
        # 已取消的运行不被后续成功回写覆盖
        if run.status == "cancelled" and status == "success":
            status = "cancelled"
        run.status = status
        run.branch = branch
        run.output_preview = _preview(output)
        run.error = _preview(error) if error else None
        run.steps = json.dumps(steps[:MAX_STEPS], ensure_ascii=False)
        run.duration_ms = int(duration_ms)
        run.finished_at = datetime.utcnow()
        db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.warning("Agent 运行记录结束失败: %s", exc)
    finally:
        db.close()


def list_runs(
    db: Session,
    *,
    status: Optional[str] = None,
    user_id: Optional[int] = None,
    branch: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    query = db.query(AgentRun)
    if status:
        query = query.filter(AgentRun.status == status)
    if user_id:
        query = query.filter(AgentRun.user_id == user_id)
    if branch:
        query = query.filter(AgentRun.branch == branch)

    total = query.count()
    page = max(1, page)
    page_size = min(max(1, page_size), 100)
    rows = (
        query.order_by(AgentRun.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [
            {
                "id": run.id,
                "user_id": run.user_id,
                "role": run.role,
                "session_id": run.session_id,
                "request_id": run.request_id,
                "branch": run.branch,
                "status": run.status,
                "input_preview": run.input_preview,
                "duration_ms": run.duration_ms,
                "created_at": run.created_at,
                "finished_at": run.finished_at,
            }
            for run in rows
        ],
    }


def get_run(db: Session, run_id: int) -> Optional[dict]:
    run = db.query(AgentRun).filter(AgentRun.id == run_id).first()
    if not run:
        return None
    try:
        steps = json.loads(run.steps) if run.steps else []
    except (TypeError, ValueError):
        steps = []
    return {
        "id": run.id,
        "user_id": run.user_id,
        "role": run.role,
        "session_id": run.session_id,
        "request_id": run.request_id,
        "branch": run.branch,
        "status": run.status,
        "input_preview": run.input_preview,
        "output_preview": run.output_preview,
        "steps": steps,
        "error": run.error,
        "duration_ms": run.duration_ms,
        "created_at": run.created_at,
        "finished_at": run.finished_at,
    }


def run_stats(db: Session) -> dict:
    """管理端概览:状态分布与耗时

    平均耗时只统计成功完成的运行:风控拦截、幂等复用与快速失败
    往往只有几百毫秒,混入平均值会把真实回答耗时(通常数秒到数十秒)稀释掉。
    """
    status_rows = dict(
        db.query(AgentRun.status, func.count(AgentRun.id))
        .group_by(AgentRun.status)
        .all()
    )
    avg_duration = (
        db.query(func.avg(AgentRun.duration_ms))
        .filter(AgentRun.duration_ms.isnot(None), AgentRun.status == "success")
        .scalar()
        or 0
    )
    avg_duration_all = (
        db.query(func.avg(AgentRun.duration_ms))
        .filter(AgentRun.duration_ms.isnot(None))
        .scalar()
        or 0
    )
    return {
        "by_status": {str(key): int(value) for key, value in status_rows.items()},
        "avg_duration_ms": int(avg_duration),
        "avg_duration_all_ms": int(avg_duration_all),
        "success_count": int(status_rows.get("success", 0)),
    }


def cancel_run(db: Session, run_id: int) -> Optional[str]:
    """把 running 运行标记为 cancelled;返回最新状态,记录不存在返回 None"""
    run = db.query(AgentRun).filter(AgentRun.id == run_id).first()
    if not run:
        return None
    if run.status != "running":
        return run.status
    run.status = "cancelled"
    run.error = "用户已取消"
    run.finished_at = datetime.utcnow()
    db.commit()
    return "cancelled"


# ---------- 持久化幂等键 ----------

def find_run_by_request(
    db: Session, request_id: str, user_id: Optional[int] = None,
) -> Optional[dict]:
    """按幂等键查历史运行;跨进程/重启后仍可判定重复请求

    优先返回已结束的记录(running 可能仍在执行,交由调用方决定是否复用)。
    """
    if not request_id:
        return None
    query = db.query(AgentRun).filter(AgentRun.request_id == request_id)
    if user_id:
        query = query.filter(AgentRun.user_id == user_id)
    rows = query.order_by(AgentRun.id.desc()).limit(5).all()
    if not rows:
        return None
    finished = [r for r in rows if r.status != "running"]
    run = (finished or rows)[0]
    return {
        "id": run.id,
        "user_id": run.user_id,
        "session_id": run.session_id,
        "request_id": run.request_id,
        "branch": run.branch,
        "status": run.status,
        "output_preview": run.output_preview,
        "error": run.error,
        "created_at": run.created_at,
        "finished_at": run.finished_at,
    }


def mark_stale_running_as_failed(max_age_seconds: int = 600) -> int:
    """把长时间停留在 running 的运行标记为 failed 并转入死信队列

    进程重启后内存任务已丢失,running 记录不会有结果,统一收尾并留下可重放死信。
    """
    db = SessionLocal()
    try:
        deadline = datetime.utcnow() - timedelta(seconds=max_age_seconds)
        stale = (
            db.query(AgentRun)
            .filter(AgentRun.status == "running", AgentRun.created_at < deadline)
            .all()
        )
        if not stale:
            return 0
        for run in stale:
            run.status = "failed"
            run.error = "运行超时或进程重启,任务已中断"
            run.finished_at = datetime.utcnow()
            db.add(AgentDeadLetter(
                run_id=run.id,
                user_id=run.user_id,
                session_id=run.session_id,
                request_id=run.request_id,
                reason="运行中断(超时或进程重启)",
                payload=json.dumps({
                    "session_id": run.session_id,
                    "request_id": run.request_id,
                    "message": run.input_preview,
                }, ensure_ascii=False),
            ))
        db.commit()
        logger.info("已将 %s 条僵死运行转入死信队列", len(stale))
        return len(stale)
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.warning("僵死运行收尾失败: %s", exc)
        return 0
    finally:
        db.close()


# ---------- 死信队列 ----------

def add_dead_letter(
    *,
    user_id: int,
    run_id: Optional[int] = None,
    session_id: Optional[str] = None,
    request_id: Optional[str] = None,
    reason: str = "",
    payload: Optional[dict] = None,
) -> Optional[int]:
    """登记一条待处理死信;失败不影响主流程"""
    db = SessionLocal()
    try:
        row = AgentDeadLetter(
            run_id=run_id,
            user_id=user_id,
            session_id=session_id,
            request_id=request_id,
            reason=(reason or "")[:200],
            payload=json.dumps(payload, ensure_ascii=False) if payload else None,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row.id
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.warning("死信登记失败: %s", exc)
        return None
    finally:
        db.close()


def list_dead_letters(
    db: Session,
    *,
    status: Optional[str] = None,
    user_id: Optional[int] = None,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    query = db.query(AgentDeadLetter)
    if status:
        query = query.filter(AgentDeadLetter.status == status)
    if user_id:
        query = query.filter(AgentDeadLetter.user_id == user_id)

    total = query.count()
    page = max(1, page)
    page_size = min(max(1, page_size), 100)
    rows = (
        query.order_by(AgentDeadLetter.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [_dead_letter_dict(row) for row in rows],
    }


def _dead_letter_dict(row: AgentDeadLetter) -> dict:
    try:
        payload = json.loads(row.payload) if row.payload else None
    except (TypeError, ValueError):
        payload = None
    return {
        "id": row.id,
        "run_id": row.run_id,
        "user_id": row.user_id,
        "session_id": row.session_id,
        "request_id": row.request_id,
        "reason": row.reason,
        "payload": payload,
        "status": row.status,
        "retry_count": row.retry_count,
        "last_run_id": row.last_run_id,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def get_dead_letter(db: Session, dead_id: int) -> Optional[dict]:
    row = db.query(AgentDeadLetter).filter(AgentDeadLetter.id == dead_id).first()
    return _dead_letter_dict(row) if row else None


def mark_dead_letter_replayed(
    db: Session, dead_id: int, new_run_id: Optional[int],
) -> Optional[str]:
    """标记死信已重放;返回最新状态,记录不存在返回 None"""
    row = db.query(AgentDeadLetter).filter(AgentDeadLetter.id == dead_id).first()
    if not row:
        return None
    row.status = "replayed"
    row.retry_count = int(row.retry_count or 0) + 1
    row.last_run_id = new_run_id
    row.updated_at = datetime.utcnow()
    db.commit()
    return "replayed"


def discard_dead_letter(db: Session, dead_id: int) -> Optional[str]:
    """标记死信已丢弃;返回最新状态,记录不存在返回 None"""
    row = db.query(AgentDeadLetter).filter(AgentDeadLetter.id == dead_id).first()
    if not row:
        return None
    row.status = "discarded"
    row.updated_at = datetime.utcnow()
    db.commit()
    return "discarded"


# ---------- 运行中途计划调整(P2-5) ----------

MAX_PLAN_REVISIONS = 3


def _plan_revision_dict(row: AgentPlanRevision) -> dict:
    return {
        "id": row.id,
        "run_id": row.run_id,
        "session_id": row.session_id,
        "instruction": row.instruction,
        "status": row.status,
        "applied_at": row.applied_at,
        "created_at": row.created_at,
    }


def count_pending_plan_revisions(db: Session, run_id: int) -> int:
    return (
        db.query(func.count(AgentPlanRevision.id))
        .filter(
            AgentPlanRevision.run_id == run_id,
            AgentPlanRevision.status == "pending",
        )
        .scalar()
        or 0
    )


def add_plan_revision(
    db: Session, *, run_id: int, session_id: str, user_id: int, instruction: str,
) -> dict:
    """登记一条待生效的计划调整;调用方负责校验运行归属与状态"""
    row = AgentPlanRevision(
        run_id=run_id,
        session_id=session_id,
        user_id=user_id,
        instruction=instruction,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _plan_revision_dict(row)


def list_plan_revisions(db: Session, run_id: int) -> list[dict]:
    rows = (
        db.query(AgentPlanRevision)
        .filter(AgentPlanRevision.run_id == run_id)
        .order_by(AgentPlanRevision.id.asc())
        .all()
    )
    return [_plan_revision_dict(row) for row in rows]


def take_pending_plan_revisions(
    run_id: Optional[int], limit: int = MAX_PLAN_REVISIONS,
) -> list[dict]:
    """供图节点调用:取出并标记已生效;独立会话,失败返回空列表"""
    if not run_id:
        return []
    db = SessionLocal()
    try:
        rows = (
            db.query(AgentPlanRevision)
            .filter(
                AgentPlanRevision.run_id == run_id,
                AgentPlanRevision.status == "pending",
            )
            .order_by(AgentPlanRevision.id.asc())
            .limit(limit)
            .all()
        )
        if not rows:
            return []
        applied_at = datetime.utcnow()
        for row in rows:
            row.status = "applied"
            row.applied_at = applied_at
        db.commit()
        return [_plan_revision_dict(row) for row in rows]
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.warning("计划调整读取失败 run=%s: %s", run_id, exc)
        return []
    finally:
        db.close()


def expire_plan_revisions(run_id: Optional[int]) -> None:
    """运行结束时作废未消费的调整,避免串到同一会话的下一次运行"""
    if not run_id:
        return
    db = SessionLocal()
    try:
        db.query(AgentPlanRevision).filter(
            AgentPlanRevision.run_id == run_id,
            AgentPlanRevision.status == "pending",
        ).update(
            {"status": "expired"}, synchronize_session=False,
        )
        db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.warning("计划调整清理失败 run=%s: %s", run_id, exc)
    finally:
        db.close()
