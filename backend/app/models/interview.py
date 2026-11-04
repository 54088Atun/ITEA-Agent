"""面试记录表"""
from sqlalchemy import Column, BigInteger, String, Text, Integer, DateTime, ForeignKey, func
from app.db.session import Base

BigIntPK = BigInteger().with_variant(Integer, "sqlite")


class InterviewRecord(Base):
    __tablename__ = "interview_records"

    id = Column(BigIntPK, primary_key=True, autoincrement=True)
    profile_id = Column(BigInteger, ForeignKey("student_profiles.id"), nullable=False, index=True)
    assignment_id = Column(
        BigInteger, ForeignKey("interview_assignments.id"), nullable=True, index=True,
    )
    round = Column(Integer, nullable=False, comment="面试轮次")
    question = Column(Text, nullable=False)
    answer = Column(Text, comment="学生回答")
    score = Column(Integer, comment="评分 0-100")
    score_dimensions = Column(Text, nullable=True, comment="四维评分 JSON")
    feedback = Column(Text, comment="完整点评")
    visibility = Column(
        String(20), nullable=False, default="private", server_default="private",
        comment="private/teacher",
    )
    created_at = Column(DateTime, server_default=func.now())
