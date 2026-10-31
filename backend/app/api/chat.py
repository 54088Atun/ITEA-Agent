"""对话路由:SSE 流式调用 LangGraph Agent"""
import json
import time
import uuid
import logging
import asyncio
from datetime import datetime
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import func
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.db.session import get_db, SessionLocal
from app.core.deps import get_current_user
from app.models.user import User
from app.models.log import InteractionLog
from app.models.conversation import Conversation, ChatMessage
from app.schemas.agent import ChatRequest, ConversationRename
from app.agent.graph import get_graph
from app.agent.state import AgentState

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/chat", tags=["对话"])

# 简易内存会话存储(生产环境可换 Redis)
_sessions: Dict[str, List[Dict]] = {}
# 会话归属记录:session_id -> {user_id, updated_at}
_session_owner: Dict[str, Dict] = {}

MAX_HISTORY = 20  # 每次请求最多携带的历史轮数
# 单次对话的总时长上限:超过则中断并返回提示,避免一次请求长期占用连接
MAX_STREAM_SECONDS = 240

SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",  # nginx 不缓冲
}


def _sse_event(event_type: str, data: dict) -> str:
    """格式化 SSE 数据帧"""
    payload = json.dumps({"type": event_type, "data": data}, ensure_ascii=False)
    return f"data: {payload}\n\n"


def _last_user_text(messages: Optional[List[Dict]]) -> str:
    for m in reversed(messages or []):
        if m.get("role") == "user":
            return m.get("content", "")
    return ""


def _load_history_from_db(session_id: str, user_id: int) -> tuple[List[Dict], bool]:
    """从数据库加载会话历史;返回 (messages, 归属是否冲突)"""
    db = SessionLocal()
    try:
        conv = db.query(Conversation).filter(
            Conversation.session_id == session_id,
            Conversation.deleted_at.is_(None),
        ).first()
        if not conv:
            return [], False
        if conv.user_id != user_id:
            return [], True
        rows = (
            db.query(ChatMessage)
            .filter(ChatMessage.conversation_id == conv.id)
            .order_by(ChatMessage.id.desc())
            .limit(MAX_HISTORY * 2)
            .all()
        )
        return [{"role": r.role, "content": r.content} for r in reversed(rows)], False
    except Exception as e:
        logger.warning("历史会话读取失败: %s", e)
        return [], False
    finally:
        db.close()


def _persist_turn_sync(
    user_id: int, session_id: str, branch: str, course_id: Optional[int],
    user_text: str, assistant_text: str,
):
    """落库一轮问答(独立会话,避免阻塞流式响应)"""
    db = SessionLocal()
    try:
        conv = db.query(Conversation).filter(
            Conversation.session_id == session_id
        ).first()
        if conv and conv.user_id != user_id:
            logger.warning("会话归属不一致,跳过持久化 session=%s", session_id)
            return
        if not conv:
            conv = Conversation(
                session_id=session_id, user_id=user_id,
                title=(user_text or "新对话")[:30],
                branch=branch or None, course_id=course_id,
            )
            db.add(conv)
            db.flush()
        else:
            if branch:
                conv.branch = branch
            if course_id:
                conv.course_id = course_id
            conv.updated_at = datetime.utcnow()
        db.add(ChatMessage(conversation_id=conv.id, role="user", content=user_text))
        if assistant_text:
            db.add(ChatMessage(
                conversation_id=conv.id, role="assistant", content=assistant_text,
            ))
        db.commit()
    except Exception as e:
        db.rollback()
        logger.warning("会话持久化失败: %s", e)
    finally:
        db.close()


def _build_initial_state(req: ChatRequest, user: User) -> AgentState:
    """构建 LangGraph 初始状态"""
    session_id = req.session_id or str(uuid.uuid4())
    history = _sessions.get(session_id)
    if history is None:
        history, owner_conflict = _load_history_from_db(session_id, user.id)
        if owner_conflict:
            # 归属不符:不复用他人 session,重新开一条会话
            session_id = str(uuid.uuid4())
            history = []
    history = list(history)
    history.append({"role": "user", "content": req.message})
    # 截断过长历史
    if len(history) > MAX_HISTORY * 2:
        history = history[-(MAX_HISTORY * 2):]
    _sessions[session_id] = history
    _session_owner[session_id] = {"user_id": user.id, "updated_at": datetime.utcnow()}

    return AgentState(
        messages=history,
        session_id=session_id,
        user_id=user.id,
        user_role=user.role,
        admin_level=user.admin_level,
        user_name=user.name,
        course_id=req.course_id,
        intent="",
        branch="",
        task_plan=[],
        current_step=0,
        tool_calls=[],
        tool_results={},
        rag_context="",
        profile_snapshot={},
        profile_updates={},
        risk_flag=False,
        risk_type="",
        reflection_passed=False,
        reflection_notes="",
        reflection_count=0,
        final_output="",
        stream_queue=None,
    )


def _log_interaction_sync(user_id: int, role: str, session_id: str, branch: str, content: str):
    """写入交互日志(同步实现,只在线程池里调用)

    使用独立 Session:流式响应期间不能复用路由注入的那个会话,
    否则一次慢提交会连带阻塞其它请求。
    """
    db = SessionLocal()
    try:
        db.add(InteractionLog(
            user_id=user_id, session_id=session_id,
            role=role, branch=branch, content=content[:2000],
        ))
        db.commit()
    except Exception as e:
        db.rollback()
        logger.warning("交互日志写入失败: %s", e)
    finally:
        db.close()


async def _log_interaction(db: Session, user: User, session_id: str, branch: str, content: str):
    """异步包装:放到线程池执行,避免同步 commit 卡住事件循环

    db 参数保留是为了兼容既有调用点,实际不再使用。
    """
    try:
        await run_in_threadpool(
            _log_interaction_sync, user.id, user.role, session_id, branch, content
        )
    except Exception as e:
        logger.warning("交互日志写入失败: %s", e)


ANSWER_NODES = ("teacher", "tutor", "review", "interview", "admin")


async def _stream_graph(state: AgentState, db: Session, user: User,
                        request: Optional[Request] = None):
    """运行 LangGraph 并以真流式产出 SSE 事件

    - 回答节点通过 state["stream_queue"] 边生成边上交 token,
      首字延迟从「全流程耗时」降到「模型首个 token」;
    - request 用于检测客户端断开(用户切页面),断开后立即停止;
    - 总时长超过 MAX_STREAM_SECONDS 则中断。
    """
    graph = get_graph()
    session_id = state["session_id"]
    started_at = time.monotonic()
    queue: asyncio.Queue = asyncio.Queue()
    state["stream_queue"] = queue

    holder = {"final": "", "error": "", "branch": state.get("branch", ""),
              "course_id": state.get("course_id")}

    async def run_graph():
        """在独立任务里跑图,把事件与 token 都塞进队列"""
        try:
            async for chunk in graph.astream(state, stream_mode="updates"):
                for node_name, updates in chunk.items():
                    if not updates:
                        continue

                    if node_name == "prepare":
                        holder["course_id"] = updates.get("course_id")

                    if node_name == "router":
                        branch = updates.get("branch", "")
                        holder["branch"] = branch
                        await queue.put(("event", _sse_event("branch", {
                            "branch": branch,
                            "intent": updates.get("intent", ""),
                        })))
                        if branch == "block":
                            await queue.put(("event", _sse_event("risk", {
                                "risk_type": updates.get("risk_type", ""),
                            })))

                    elif node_name == "risk_guard":
                        output = updates.get("final_output", "")
                        holder["branch"] = "block"
                        if output:
                            holder["final"] = output
                            await _log_interaction(db, user, session_id, "block", output)

                    elif node_name == "tool_executor":
                        tool_results = updates.get("tool_results") or {}
                        for tool_name, result in tool_results.items():
                            preview = str(result)
                            if len(preview) > 500:
                                preview = preview[:500] + "..."
                            await queue.put(("event", _sse_event("tool_call", {
                                "name": tool_name, "preview": preview,
                            })))

                    elif node_name == "reflect":
                        if not updates.get("reflection_passed", True):
                            # 反思未通过 → 会带意见重写,先让前端丢掉已流出的草稿
                            await queue.put(("reset", _sse_event("reset", {})))
                            await queue.put(("event", _sse_event("reflect", {
                                "passed": False,
                                "notes": (updates.get("reflection_notes") or "")[:200],
                                "round": updates.get("reflection_count", 0),
                            })))

                    elif node_name in ANSWER_NODES:
                        holder["branch"] = node_name
                        output = updates.get("final_output", "")
                        if output:
                            holder["final"] = output
        except Exception as e:  # noqa: BLE001
            logger.exception("Agent 执行异常")
            holder["error"] = str(e)
        finally:
            await queue.put(None)

    task = asyncio.create_task(run_graph())
    streamed = ""

    try:
        while True:
            item = await queue.get()
            if item is None:
                break

            kind, payload = item
            if kind == "token":
                streamed += payload
                yield _sse_event("token", {"content": payload})
            elif kind == "reset":
                streamed = ""
                yield payload
            else:
                yield payload

            # 客户端断开 → 立刻停止,不再继续生成
            if request is not None and await request.is_disconnected():
                logger.info("客户端已断开,终止生成 session=%s", session_id)
                return

            if time.monotonic() - started_at > MAX_STREAM_SECONDS:
                logger.warning("对话超时中断 session=%s", session_id)
                yield _sse_event("error", {"message": "本次回答耗时过长已中断,请把问题拆小一些再试"})
                yield _sse_event("done", {"session_id": session_id})
                return

        await task
    finally:
        if not task.done():
            task.cancel()

    if holder["error"]:
        yield _sse_event("error", {"message": f"处理失败: {holder['error']}"})
        yield _sse_event("done", {"session_id": session_id})
        return

    final_output = holder["final"]
    if final_output:
        # 补发差额:节点可能补了标注(如 [AI 辅助参考]),或该节点没走流式(如 review 返回 JSON)
        rest = final_output[len(streamed):] if final_output.startswith(streamed) else final_output
        for i in range(0, len(rest), 48):
            yield _sse_event("token", {"content": rest[i:i + 48]})
            await asyncio.sleep(0.01)

        _sessions.setdefault(session_id, []).append(
            {"role": "assistant", "content": final_output})
        await run_in_threadpool(
            _persist_turn_sync, user.id, session_id,
            holder["branch"], holder["course_id"],
            _last_user_text(state.get("messages")), final_output,
        )
        await _log_interaction(db, user, session_id, holder["branch"], final_output)

    owner = _session_owner.get(session_id)
    if owner is not None:
        owner["updated_at"] = datetime.utcnow()
    yield _sse_event("done", {"session_id": session_id})


async def stream_agent_response(
    req: ChatRequest,
    user: User,
    db: Session,
    force_branch: Optional[str] = None,
    request: Optional[Request] = None,
):
    """可复用流式内核

    force_branch: 指定业务分支(teacher/interview 等),跳过意图识别,
    供 lesson-plan、interview/start 等结构化入口复用 Agent 图。
    request: 传入时用于检测客户端断开,断开即停止生成。
    """
    state = _build_initial_state(req, user)
    if force_branch:
        state["branch"] = force_branch
        state["intent"] = {
            "teacher": "prepare", "tutor": "learn",
            "review": "review", "interview": "interview", "admin": "chat",
        }.get(force_branch, "chat")
    async for event in _stream_graph(state, db, user, request):
        yield event


def list_sessions(db: Session, user_id: int) -> List[Dict]:
    """按交互日志聚合会话列表(最近活跃优先)"""
    rows = (
        db.query(
            InteractionLog.session_id,
            func.count(InteractionLog.id).label("cnt"),
            func.max(InteractionLog.created_at).label("updated_at"),
        )
        .filter(InteractionLog.user_id == user_id)
        .group_by(InteractionLog.session_id)
        .order_by(func.max(InteractionLog.created_at).desc())
        .all()
    )
    result = []
    for session_id, cnt, updated_at in rows:
        last = (
            db.query(InteractionLog.content)
            .filter(InteractionLog.user_id == user_id,
                    InteractionLog.session_id == session_id)
            .order_by(InteractionLog.id.desc())
            .first()
        )
        result.append({
            "session_id": session_id,
            "message_count": cnt,
            "last_message": (last[0] if last else "") or "",
            "updated_at": updated_at,
        })
    return result


@router.post("/stream")
async def chat_stream(
    req: ChatRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """SSE 流式对话入口

    事件类型:
    - branch: 路由分支结果 {branch, intent}
    - risk:   风控拦截 {risk_type}
    - tool_call: 工具调用 {name, preview}
    - reflect: 反思未通过 {passed, notes, round}
    - token:  输出内容分块 {content}
    - done:   结束 {session_id}
    - error:  异常 {message}
    """
    return StreamingResponse(
        stream_agent_response(req, user, db, request=request),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


@router.get("/conversations")
def list_conversations(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """历史对话列表(最近活跃优先,仅本人)"""
    convs = (
        db.query(Conversation)
        .filter(Conversation.user_id == user.id, Conversation.deleted_at.is_(None))
        .order_by(Conversation.updated_at.desc())
        .limit(50)
        .all()
    )
    ids = [c.id for c in convs]
    counts = {}
    if ids:
        rows = (
            db.query(ChatMessage.conversation_id, func.count(ChatMessage.id))
            .filter(ChatMessage.conversation_id.in_(ids))
            .group_by(ChatMessage.conversation_id)
            .all()
        )
        counts = dict(rows)
    return {
        "items": [
            {
                "session_id": c.session_id,
                "title": c.title,
                "branch": c.branch,
                "course_id": c.course_id,
                "message_count": counts.get(c.id, 0),
                "updated_at": c.updated_at,
            }
            for c in convs
        ]
    }


@router.patch("/conversations/{session_id}")
def rename_conversation(
    session_id: str,
    req: ConversationRename,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    conv = db.query(Conversation).filter(
        Conversation.session_id == session_id,
        Conversation.user_id == user.id,
        Conversation.deleted_at.is_(None),
    ).first()
    if not conv:
        return {"session_id": session_id, "updated": False}
    conv.title = req.title.strip()[:120] or conv.title
    db.commit()
    return {"session_id": session_id, "title": conv.title, "updated": True}


@router.delete("/conversations/{session_id}")
def delete_conversation(
    session_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    conv = db.query(Conversation).filter(
        Conversation.session_id == session_id,
        Conversation.user_id == user.id,
        Conversation.deleted_at.is_(None),
    ).first()
    if not conv:
        return {"session_id": session_id, "deleted": False}
    conv.deleted_at = datetime.utcnow()
    db.commit()
    _sessions.pop(session_id, None)
    _session_owner.pop(session_id, None)
    return {"session_id": session_id, "deleted": True}


@router.get("/history/{session_id}")
def get_history(
    session_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取会话历史(仅本人可读,优先持久化数据)"""
    conv = db.query(Conversation).filter(
        Conversation.session_id == session_id,
        Conversation.user_id == user.id,
        Conversation.deleted_at.is_(None),
    ).first()
    if conv:
        rows = (
            db.query(ChatMessage)
            .filter(ChatMessage.conversation_id == conv.id)
            .order_by(ChatMessage.id.asc())
            .all()
        )
        return {
            "session_id": session_id,
            "title": conv.title,
            "messages": [{"role": r.role, "content": r.content} for r in rows],
        }
    return {
        "session_id": session_id,
        "messages": _sessions.get(session_id, []),
    }
