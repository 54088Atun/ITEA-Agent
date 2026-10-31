"""知识点/大纲草稿表:AI 解析结果先入库为草稿,教师采纳后才进入正式表"""
from sqlalchemy import (
    Column, BigInteger, String, Text, DateTime, ForeignKey, Integer, func,
)
from app.db.session import Base

BigIntPK = BigInteger().with_variant(Integer, "sqlite")


class KnowledgeDraft(Base):
    __tablename__ = "knowledge_drafts"

    id = Column(BigIntPK, primary_key=True, autoincrement=True)
    course_id = Column(BigInteger, ForeignKey("courses.id"), nullable=False, index=True)
    teacher_id = Column(BigInteger, ForeignKey("users.id"), nullable=False, index=True)
    filename = Column(String(255))
    source_text_length = Column(Integer, default=0)
    payload = Column(Text, nullable=False, comment="JSON: {syllabus, knowledge_points}")
    status = Column(
        String(20), nullable=False, default="draft", server_default="draft",
        comment="draft/adopted/discarded",
    )
    created_at = Column(DateTime, server_default=func.now())
