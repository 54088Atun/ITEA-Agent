"""面试记录表"""
from sqlalchemy import Column, BigInteger, Text, Integer, DateTime, ForeignKey, func
from app.db.session import Base

BigIntPK = BigInteger().with_variant(Integer, "sqlite")


class InterviewRecord(Base):
    __tablename__ = "interview_records"

    id = Column(BigIntPK, primary_key=True, autoincrement=True)
    profile_id = Column(BigInteger, ForeignKey("student_profiles.id"), nullable=False, index=True)
    round = Column(Integer, nullable=False, comment="面试轮次")
    question = Column(Text, nullable=False)
    answer = Column(Text, comment="学生回答")
    score = Column(Integer, comment="评分 0-100")
    feedback = Column(Text, comment="点评")
    created_at = Column(DateTime, server_default=func.now())
