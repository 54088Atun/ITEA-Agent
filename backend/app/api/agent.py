"""Agent 统一入口:统一对话(SSE) / 会话列表"""
import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.schemas.agent import ChatRequest
from app.api.chat import stream_agent_response, list_sessions, SSE_HEADERS

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/agent", tags=["Agent"])


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
