"""题库与 AI 出题草稿

- 题目归属教师与课程,可选关联知识点
- 题型:single(单选)/multiple(多选)/judge(判断)/short(简答)
- AI 出题只写入草稿表,教师勾选采纳后才进入正式题库
"""
from sqlalchemy import (
    Column, BigInteger, String, Text, Integer, DateTime, ForeignKey, func,
)
from app.db.session import Base

BigIntPK = BigInteger().with_variant(Integer, "sqlite")


class Question(Base):
    __tablename__ = "questions"

    id = Column(BigIntPK, primary_key=True, autoincrement=True)
    teacher_id = Column(BigInteger, ForeignKey("users.id"), nullable=False, index=True)
    course_id = Column(BigInteger, ForeignKey("courses.id"), nullable=False, index=True)
    kp_id = Column(BigInteger, ForeignKey("knowledge_points.id"), nullable=True, index=True)
    type = Column(String(20), nullable=False, comment="single/multiple/judge/short")
    stem = Column(Text, nullable=False, comment="题干")
    options = Column(Text, comment="选项 JSON:[{key,text}]")
    answer = Column(Text, nullable=False, comment="答案:选项键或文本")
    analysis = Column(Text, comment="解析")
    difficulty = Column(Integer, nullable=False, default=3, server_default="3")
    source = Column(String(20), nullable=False, default="manual", server_default="manual",
                    comment="manual/agent")
    status = Column(String(20), nullable=False, default="active", server_default="active",
                    comment="active/archived")
    created_at = Column(DateTime, server_default=func.now())


class QuestionDraft(Base):
    __tablename__ = "question_drafts"

    id = Column(BigIntPK, primary_key=True, autoincrement=True)
    teacher_id = Column(BigInteger, ForeignKey("users.id"), nullable=False, index=True)
    course_id = Column(BigInteger, ForeignKey("courses.id"), nullable=False, index=True)
    kp_ids = Column(Text, comment="出题范围知识点 ID,逗号分隔")
    payload = Column(Text, nullable=False, comment="题目草稿 JSON 数组")
    status = Column(String(20), nullable=False, default="draft", server_default="draft",
                    comment="draft/adopted/discarded")
    created_at = Column(DateTime, server_default=func.now())
