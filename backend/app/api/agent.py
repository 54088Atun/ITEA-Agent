"""Agent 统一入口:统一对话(SSE) / 会话列表 / 工具目录 / 记忆 / 反馈 / 运行取消"""
import json
import logging
import uuid
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.models.conversation import Conversation, ChatMessage
from app.models.log import AgentRun
from app.models.agent_memory import AgentMemory, AgentFeedback
from app.schemas.agent import (
    ChatRequest, FeedbackCreate, MemoryCreate, PlanRevisionCreate,
)
from app.api.chat import (
    stream_agent_response, list_sessions, SSE_HEADERS, cancel_run_task,
    build_resume_state, replay_in_background, resume_in_background,
)
from app.agent.checkpoint import load_latest_state
from app.agent.tools.gateway import available_tools
from app.services.agent_runs import (
    MAX_PLAN_REVISIONS,
    add_plan_revision,
    cancel_run,
    count_pending_plan_revisions,
    discard_dead_letter,
    get_dead_letter,
    get_run as get_agent_run,
    list_dead_letters,
    list_plan_revisions,
    mark_dead_letter_replayed,
)
from app.services.agent_trace import list_spans

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/agent", tags=["Agent"])

MAX_MEMORY_CHARS = 2000
MAX_FEEDBACK_CHARS = 500


@router.post("/chat")
async def agent_chat(
    req: ChatRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """统一对话入口(SSE 流式) —— 所有教学类请求经内核分发"""
    return StreamingResponse(
        stream_agent_response(req, user, db, request=request),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


@router.get("/sessions")
def agent_sessions(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """会话历史列表:按最近活跃时间倒序"""
    return list_sessions(db, user.id)


@router.get("/tools")
def agent_tools(user: User = Depends(get_current_user)):
    """当前角色可用的 Agent 工具目录"""
    return {"role": user.role, "tools": available_tools(user.role)}


# ---------- 记忆 ----------

def _memory_out(row: AgentMemory) -> dict:
    return {
        "id": row.id,
        "course_id": row.course_id,
        "memory_type": row.memory_type,
        "content": row.content,
        "source_type": row.source_type,
        "source_id": row.source_id,
        "expires_at": row.expires_at,
        "created_at": row.created_at,
    }


@router.get("/memory")
def list_memories(
    course_id: Optional[int] = Query(None, description="按课程筛选"),
    limit: int = Query(50, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """查看本人的 Agent 记忆(已过期与已删除的不返回)"""
    now = datetime.utcnow()
    query = db.query(AgentMemory).filter(
        AgentMemory.user_id == user.id,
        AgentMemory.deleted_at.is_(None),
        or_(AgentMemory.expires_at.is_(None), AgentMemory.expires_at > now),
    )
    if course_id is not None:
        query = query.filter(AgentMemory.course_id == course_id)
    rows = query.order_by(AgentMemory.id.desc()).limit(limit).all()
    return {"total": len(rows), "items": [_memory_out(row) for row in rows]}


@router.post("/memory", status_code=201)
def create_memory(
    req: MemoryCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """写入一条记忆:必须带来源,按 TTL 自动过期,可随时删除"""
    content = (req.content or "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="记忆内容不能为空")
    if len(content) > MAX_MEMORY_CHARS:
        raise HTTPException(
            status_code=400, detail=f"记忆内容过长,上限 {MAX_MEMORY_CHARS} 字",
        )
    if req.ttl_days is not None and not 1 <= req.ttl_days <= 365:
        raise HTTPException(status_code=400, detail="ttl_days 需在 1-365 之间")

    expires_at = (
        datetime.utcnow() + timedelta(days=req.ttl_days)
        if req.ttl_days else None
    )
    row = AgentMemory(
        user_id=user.id,
        course_id=req.course_id,
        memory_type=req.memory_type,
        content=content,
        source_type=req.source_type,
        source_id=(req.source_id or "")[:100] or None,
        expires_at=expires_at,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _memory_out(row)


@router.delete("/memory/{memory_id}")
def delete_memory(
    memory_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """软删除本人记忆;管理员可删除任意记忆"""
    row = db.query(AgentMemory).filter(AgentMemory.id == memory_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="记忆不存在")
    if row.user_id != user.id and user.role != "admin":
        raise HTTPException(status_code=403, detail="只能删除自己的记忆")
    if row.deleted_at is None:
        row.deleted_at = datetime.utcnow()
        db.commit()
    return {"id": memory_id, "deleted": True}


# ---------- 回答反馈 ----------

@router.post("/feedback", status_code=201)
def create_feedback(
    req: FeedbackCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """对回答点赞/点踩:可关联运行记录与会话消息,便于后续评估"""
    comment = (req.comment or "").strip()
    if len(comment) > MAX_FEEDBACK_CHARS:
        raise HTTPException(
            status_code=400, detail=f"反馈原因过长,上限 {MAX_FEEDBACK_CHARS} 字",
        )

    run = None
    if req.run_id is not None:
        run = db.query(AgentRun).filter(AgentRun.id == req.run_id).first()
        if not run:
            raise HTTPException(status_code=404, detail="运行记录不存在")
        if run.user_id != user.id and user.role != "admin":
            raise HTTPException(status_code=403, detail="只能反馈自己的对话")

    if req.message_id is not None:
        message = db.query(ChatMessage).join(
            Conversation, ChatMessage.conversation_id == Conversation.id,
        ).filter(
            ChatMessage.id == req.message_id,
            Conversation.user_id == user.id,
        ).first()
        if not message:
            raise HTTPException(status_code=404, detail="消息不存在")

    session_id = req.session_id or (run.session_id if run else None)
    row = AgentFeedback(
        user_id=user.id,
        run_id=req.run_id,
        session_id=session_id,
        message_id=req.message_id,
        rating=req.rating,
        comment=comment or None,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {
        "id": row.id,
        "rating": row.rating,
        "run_id": row.run_id,
        "session_id": row.session_id,
        "message_id": row.message_id,
        "created_at": row.created_at,
    }


# ---------- 计划时间线 ----------

KIND_LABELS = {
    "route": "路由",
    "plan": "准备",
    "replan": "计划调整",
    "expert": "协作专家",
    "tool": "工具调用",
    "reflect": "校验",
    "answer": "回答",
    "block": "风控拦截",
}


def _json_or_raw(value):
    """span 里的 payload/result 是 JSON 字符串;解析失败时原样返回"""
    if value is None:
        return None
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return value


def _timeline_items(spans: list[dict]) -> list[dict]:
    return [
        {
            "seq": span.get("seq"),
            "kind": span.get("kind"),
            "kind_label": KIND_LABELS.get(span.get("kind"), span.get("kind")),
            "name": span.get("name"),
            "status": span.get("status"),
            "duration_ms": span.get("duration_ms"),
            "tokens": span.get("tokens"),
            "payload": _json_or_raw(span.get("payload")),
            "result": _json_or_raw(span.get("result")),
            "error": span.get("error"),
            "created_at": span.get("created_at"),
        }
        for span in spans
    ]


@router.get("/runs/{run_id}/timeline")
def agent_run_timeline(
    run_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """查看本人一次运行的计划时间线;管理员可查看任意用户"""
    run = get_agent_run(db, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="运行记录不存在")
    if run["user_id"] != user.id and user.role != "admin":
        raise HTTPException(status_code=403, detail="只能查看自己的运行记录")

    spans = list_spans(db, run_id)
    return {
        "run": {
            "id": run["id"],
            "session_id": run["session_id"],
            "branch": run["branch"],
            "status": run["status"],
            "duration_ms": run["duration_ms"],
            "error": run["error"],
            "created_at": run["created_at"],
            "finished_at": run["finished_at"],
        },
        "summary": {
            "steps": len(spans),
            "tools": [span["name"] for span in spans if span.get("kind") == "tool"],
            "tokens": sum(int(span.get("tokens") or 0) for span in spans),
        },
        "timeline": _timeline_items(spans),
    }


# ---------- 运行取消 ----------

@router.post("/runs/{run_id}/cancel")
def cancel_agent_run(
    run_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """取消正在运行的任务:仅本人或管理员,回写 cancelled 并中断执行"""
    run = db.query(AgentRun).filter(AgentRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="运行记录不存在")
    if run.user_id != user.id and user.role != "admin":
        raise HTTPException(status_code=403, detail="只能取消自己的任务")

    task_cancelled = cancel_run_task(run_id)
    status = cancel_run(db, run_id)
    return {
        "run_id": run_id,
        "status": status,
        "task_cancelled": task_cancelled,
    }


# ---------- 运行中途计划调整 ----------

MAX_PLAN_INSTRUCTION_CHARS = 500


@router.get("/runs/{run_id}/plan")
def agent_run_plan(
    run_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """查看一次运行的任务计划与调整记录:仅本人或管理员"""
    run = get_agent_run(db, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="运行记录不存在")
    if run["user_id"] != user.id and user.role != "admin":
        raise HTTPException(status_code=403, detail="只能查看自己的运行记录")

    snapshot = load_latest_state(run["session_id"], run_id, db=db) or {}
    values = snapshot.get("channel_values") or {}
    return {
        "run_id": run_id,
        "status": run["status"],
        "task_plan": values.get("task_plan") or [],
        "current_step": values.get("current_step") or 0,
        "revisions": list_plan_revisions(db, run_id),
    }


@router.post("/runs/{run_id}/plan", status_code=201)
def revise_agent_plan(
    run_id: int,
    req: PlanRevisionCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """运行中途追加一条计划调整:下一超级步生效,按新约束重新作答"""
    run = db.query(AgentRun).filter(AgentRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="运行记录不存在")
    if run.user_id != user.id and user.role != "admin":
        raise HTTPException(status_code=403, detail="只能调整自己的运行计划")
    if run.status != "running":
        raise HTTPException(
            status_code=409, detail="任务已结束,请直接在新消息中提出调整",
        )

    instruction = (req.instruction or "").strip()
    if not instruction:
        raise HTTPException(status_code=400, detail="调整要求不能为空")
    if len(instruction) > MAX_PLAN_INSTRUCTION_CHARS:
        raise HTTPException(
            status_code=400,
            detail=f"调整要求过长,上限 {MAX_PLAN_INSTRUCTION_CHARS} 字",
        )
    if count_pending_plan_revisions(db, run_id) >= MAX_PLAN_REVISIONS:
        raise HTTPException(
            status_code=400,
            detail=f"单次运行最多调整 {MAX_PLAN_REVISIONS} 次,请等待当前调整生效",
        )

    revision = add_plan_revision(
        db,
        run_id=run_id,
        session_id=run.session_id,
        user_id=run.user_id,
        instruction=instruction,
    )
    return {**revision, "status": "pending"}


# ---------- 运行恢复 ----------

@router.post("/runs/{run_id}/resume")
async def resume_agent_run(
    run_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """从最近检查点恢复一次中断的运行:后台继续执行,结果走幂等缓存"""
    run = db.query(AgentRun).filter(AgentRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="运行记录不存在")
    if run.user_id != user.id and user.role != "admin":
        raise HTTPException(status_code=403, detail="只能恢复自己的任务")
    if run.status == "running":
        raise HTTPException(status_code=409, detail="任务仍在执行,无需恢复")

    state = build_resume_state(run.session_id, run.id)
    if not state:
        raise HTTPException(status_code=400, detail="没有可恢复的检查点")
    owner = db.get(User, run.user_id)
    if not owner:
        raise HTTPException(status_code=404, detail="运行所属用户不存在")

    request_id = f"resume-{uuid.uuid4().hex[:12]}"
    resume_in_background(state, owner, request_id)
    return {
        "run_id": run_id,
        "request_id": request_id,
        "session_id": run.session_id,
        "status": "resuming",
    }


# ---------- 死信队列 ----------

@router.get("/dead-letters")
def list_agent_dead_letters(
    status: Optional[str] = Query(None, description="pending/replayed/discarded"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """死信列表:管理员可查看全部,普通用户只看自己的"""
    owner_id = None if user.role == "admin" else user.id
    return list_dead_letters(
        db, status=status, user_id=owner_id, page=page, page_size=page_size,
    )


@router.post("/dead-letters/{dead_id}/replay")
async def replay_agent_dead_letter(
    dead_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """重放一条死信:按原输入在后台重新生成,结果走幂等缓存"""
    letter = get_dead_letter(db, dead_id)
    if not letter:
        raise HTTPException(status_code=404, detail="死信不存在")
    if letter["user_id"] != user.id and user.role != "admin":
        raise HTTPException(status_code=403, detail="只能重放自己的死信")
    if letter["status"] != "pending":
        raise HTTPException(status_code=400, detail="该死信已处理")

    payload = letter.get("payload") or {}
    session_id = payload.get("session_id") or letter.get("session_id")
    message = str(payload.get("message") or "").strip()
    if not session_id or not message:
        raise HTTPException(status_code=400, detail="死信缺少重放所需的会话或输入")

    owner = db.get(User, letter["user_id"])
    if not owner:
        raise HTTPException(status_code=404, detail="死信所属用户不存在")

    if mark_dead_letter_replayed(db, dead_id, None) != "replayed":
        raise HTTPException(status_code=400, detail="死信状态更新失败")

    request_id = f"replay-{uuid.uuid4().hex[:12]}"
    req = ChatRequest(
        session_id=session_id, message=message, request_id=request_id,
        course_id=payload.get("course_id"),
    )
    replay_in_background(req, owner)
    return {
        "dead_letter_id": dead_id,
        "request_id": request_id,
        "session_id": session_id,
        "status": "replaying",
    }


@router.post("/dead-letters/{dead_id}/discard")
def discard_agent_dead_letter(
    dead_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """丢弃一条死信:不再重放,保留审计记录"""
    letter = get_dead_letter(db, dead_id)
    if not letter:
        raise HTTPException(status_code=404, detail="死信不存在")
    if letter["user_id"] != user.id and user.role != "admin":
        raise HTTPException(status_code=403, detail="只能处理自己的死信")
    if letter["status"] != "pending":
        raise HTTPException(status_code=400, detail="该死信已处理")
    discard_dead_letter(db, dead_id)
    return {"dead_letter_id": dead_id, "status": "discarded"}
