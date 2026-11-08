"""Agent 对话相关请求/响应模型"""
from pydantic import BaseModel
from typing import Optional, List, Dict, Any, Literal


class ChatRequest(BaseModel):
    session_id: Optional[str] = None  # 续接会话
    course_id: Optional[int] = None
    message: str = ""
    # 多模态附件: {type: image|audio|text, text, path, filename}
    attachments: List[Dict[str, Any]] = []
    collaborate: bool = False  # 多 Agent 协作模式
    request_id: Optional[str] = None  # 前端幂等键，用于断线续答/重试去重
    interview_assignment_id: Optional[int] = None  # 后续面试消息沿用同一作业时长约束
    # 错题复盘:true=本次消息作为错题提交并写入学情与复习计划;false=只做诊断/查询
    review_submit: bool = False


class ToolConfirmRequest(BaseModel):
    """高危工具确认执行请求:令牌绑定会话/用户/工具/参数"""

    session_id: str
    tool: str
    arguments: Dict[str, Any] = {}
    token: str


class ChatEvent(BaseModel):
    """SSE 事件结构"""
    type: str  # token / tool_call / branch / done / error
    data: Dict[str, Any] = {}


class ConversationFavorite(BaseModel):
    favorite: bool = True


class ConversationRename(BaseModel):
    title: str


class ConversationSecurityLevel(BaseModel):
    """会话人工分级;null 表示清除覆盖并恢复自动判定"""
    security_level: Optional[
        Literal["full", "auto", "manual", "confidential"]
    ] = None


class MemoryCreate(BaseModel):
    """写入一条 Agent 记忆:必须带来源与 TTL"""
    content: str
    memory_type: Literal["episodic", "semantic"] = "semantic"
    course_id: Optional[int] = None
    source_type: Literal["conversation", "manual", "feedback"] = "manual"
    source_id: Optional[str] = None
    ttl_days: Optional[int] = 30


class FeedbackCreate(BaseModel):
    """回答反馈:点赞/点踩,可关联运行与消息"""
    rating: Literal["up", "down"]
    run_id: Optional[int] = None
    session_id: Optional[str] = None
    message_id: Optional[int] = None
    comment: Optional[str] = None


class PlanRevisionCreate(BaseModel):
    """运行中途的计划调整:提交后在下一超级步生效"""
    instruction: str
