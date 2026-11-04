"""作业与提交表:教师发布作业,学生提交,AI 批改仅出建议

设计口径:
- 作业可面向班级(class_id)或课程(class_id 为空时按选课关系判定)
- 仅 status='published' 的作业对学生可见;截止后禁止提交
- 参考答案在截止前不下发给学生,避免提前查看
- AI 批改只写 ai_score/ai_feedback/ai_graded_at,正式 score/feedback
  必须由教师调用确认接口后才写入
"""
from sqlalchemy import (
    Column, BigInteger, String, Text, Integer, DateTime, ForeignKey,
    UniqueConstraint, Boolean, func,
)
from app.db.session import Base

BigIntPK = BigInteger().with_variant(Integer, "sqlite")


class Assignment(Base):
    """作业发布记录"""
    __tablename__ = "assignments"

    id = Column(BigIntPK, primary_key=True, autoincrement=True)
    teacher_id = Column(BigInteger, ForeignKey("users.id"), nullable=False, index=True)
    course_id = Column(BigInteger, ForeignKey("courses.id"), nullable=True, index=True)
    class_id = Column(BigInteger, ForeignKey("classes.id"), nullable=True, index=True)
    title = Column(String(120), nullable=False)
    kind = Column(
        String(20), nullable=False, default="homework", server_default="homework",
        comment="homework/exam,作业或考试共用同一发布模型",
    )
    description = Column(Text, comment="作业要求")
    reference_answer = Column(Text, comment="参考答案,截止前不对学生下发")
    due_at = Column(DateTime, nullable=True, comment="截止时间")
    allow_late = Column(
        Boolean, nullable=False, default=False, server_default="0",
        comment="截止后是否允许正式补交",
    )
    status = Column(
        String(20), nullable=False, default="published", server_default="published",
        comment="draft/published/closed",
    )
    created_at = Column(DateTime, server_default=func.now())


class Submission(Base):
    """学生提交与批改结果"""
    __tablename__ = "submissions"
    __table_args__ = (
        UniqueConstraint("assignment_id", "student_id", name="uq_submission_student"),
    )

    id = Column(BigIntPK, primary_key=True, autoincrement=True)
    assignment_id = Column(
        BigInteger, ForeignKey("assignments.id"), nullable=False, index=True,
    )
    student_id = Column(BigInteger, ForeignKey("users.id"), nullable=False, index=True)
    content = Column(Text, nullable=False, comment="提交内容")
    attachment_url = Column(String(500), comment="附件地址(可选)")
    status = Column(
        String(20), nullable=False, default="submitted", server_default="submitted",
        comment="draft/submitted",
    )
    submitted_at = Column(DateTime, nullable=True, comment="正式提交时间")
    ai_score = Column(Integer, comment="AI 建议分数,未确认前不生效")
    ai_feedback = Column(Text, comment="AI 建议评语")
    ai_graded_at = Column(DateTime, comment="AI 批改时间")
    score = Column(Integer, comment="教师确认后的正式分数")
    feedback = Column(Text, comment="教师确认后的正式评语")
    confirmed_at = Column(DateTime, comment="教师确认时间,为空表示未确认")
    confirmed_by = Column(BigInteger, ForeignKey("users.id"), comment="确认教师")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
