"""会话与消息持久化表

用途:
- 取代仅存在内存的对话历史,重启/刷新后仍可续接
- 左侧历史列表按用户隔离,支持重命名与软删除
"""
from sqlalchemy import (
    Column, BigInteger, String, Text, Integer, DateTime, ForeignKey, func,
)
from app.db.session import Base

BigIntPK = BigInteger().with_variant(Integer, "sqlite")


class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(BigIntPK, primary_key=True, autoincrement=True)
    session_id = Column(String(64), nullable=False, unique=True, index=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False, index=True)
    title = Column(String(120), nullable=False, default="新对话")
    branch = Column(String(20), comment="teacher/tutor/review/interview/admin")
    course_id = Column(BigInteger, ForeignKey("courses.id"), nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), index=True)
    deleted_at = Column(DateTime, nullable=True)


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(BigIntPK, primary_key=True, autoincrement=True)
    conversation_id = Column(
        BigInteger, ForeignKey("conversations.id"), nullable=False, index=True,
    )
    role = Column(String(20), nullable=False, comment="user/assistant/system")
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, server_default=func.now(), index=True)
