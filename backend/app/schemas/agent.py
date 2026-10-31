"""Agent 对话相关请求/响应模型"""
from pydantic import BaseModel
from typing import Optional, List, Dict, Any


class ChatRequest(BaseModel):
    session_id: Optional[str] = None  # 续接会话
    course_id: Optional[int] = None
    message: str
    attachments: List[Dict[str, Any]] = []  # 可选:代码文件等


class ChatEvent(BaseModel):
    """SSE 事件结构"""
    type: str  # token / tool_call / branch / done / error
    data: Dict[str, Any] = {}


class ConversationRename(BaseModel):
    title: str