"""面试作业表:教师向班级/课程发布面试任务,学生端仅在发布后可见"""
from sqlalchemy import (
    Column, BigInteger, String, Text, Integer, DateTime, ForeignKey, func,
)
from app.db.session import Base

BigIntPK = BigInteger().with_variant(Integer, "sqlite")


class InterviewAssignment(Base):
    __tablename__ = "interview_assignments"

    id = Column(BigIntPK, primary_key=True, autoincrement=True)
    teacher_id = Column(BigInteger, ForeignKey("users.id"), nullable=False, index=True)
    class_id = Column(BigInteger, ForeignKey("classes.id"), nullable=True, index=True)
    course_id = Column(BigInteger, ForeignKey("courses.id"), nullable=True, index=True)
    title = Column(String(120), nullable=False)
    description = Column(Text)
    due_at = Column(DateTime, nullable=True)
    status = Column(
        String(20), nullable=False, default="active", server_default="active",
        comment="active/closed",
    )
    created_at = Column(DateTime, server_default=func.now())

