"""Agent 记忆与回答反馈表

- 记忆:跨会话情景/语义记忆,必须带来源与过期时间,支持软删除
- 反馈:回答点赞/点踩,关联运行记录与消息,用于后续评估
"""
from sqlalchemy import (
    Column, BigInteger, String, Text, DateTime, Integer, func,
)
from app.db.session import Base

BigIntPK = BigInteger().with_variant(Integer, "sqlite")


class AgentMemory(Base):
    """用户级 Agent 记忆:按课程隔离,带来源与 TTL"""

    __tablename__ = "agent_memories"

    id = Column(BigIntPK, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, nullable=False, index=True)
    course_id = Column(BigInteger, nullable=True, index=True)
    memory_type = Column(
        String(20), nullable=False, default="semantic", server_default="semantic",
        comment="episodic 情景记忆 / semantic 语义记忆",
    )
    content = Column(Text, nullable=False)
    source_type = Column(
        String(30), nullable=False, default="manual", server_default="manual",
        comment="conversation/manual/feedback 等来源",
    )
    source_id = Column(String(100), nullable=True, comment="来源会话或消息标识")
    expires_at = Column(DateTime, nullable=True, comment="过期时间,空表示不过期")
    created_at = Column(DateTime, server_default=func.now())
    deleted_at = Column(DateTime, nullable=True, comment="软删除时间")
    session_id = Column(String(64), nullable=True, index=True, comment="来源会话")
    run_id = Column(BigInteger, nullable=True, index=True, comment="来源运行记录")
    summary = Column(Text, nullable=True, comment="记忆摘要(情景记忆用于检索)")
    importance = Column(
        Integer, nullable=False, default=1, server_default="1",
        comment="重要度 1-5,越高越优先注入",
    )
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class AgentFeedback(Base):
    """回答反馈:点赞/点踩与原因,关联运行与消息"""

    __tablename__ = "agent_feedback"

    id = Column(BigIntPK, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, nullable=False, index=True)
    run_id = Column(BigInteger, nullable=True, index=True)
    session_id = Column(String(64), nullable=True, index=True)
    message_id = Column(BigInteger, nullable=True, comment="被反馈的助手消息 ID")
    rating = Column(String(10), nullable=False, comment="up/down")
    comment = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
