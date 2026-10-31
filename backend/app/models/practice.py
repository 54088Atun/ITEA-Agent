"""练习记录表"""
from sqlalchemy import Column, BigInteger, Text, Enum, Boolean, Integer, DateTime, ForeignKey, func
from app.db.session import Base

BigIntPK = BigInteger().with_variant(Integer, "sqlite")


class PracticeRecord(Base):
    __tablename__ = "practice_records"

    id = Column(BigIntPK, primary_key=True, autoincrement=True)
    profile_id = Column(BigInteger, ForeignKey("student_profiles.id"), nullable=False, index=True)
    kp_id = Column(BigInteger, ForeignKey("knowledge_points.id"), nullable=True, comment="关联知识点,未匹配时为空")
    type = Column(
        Enum("in_class", "variant", "code", name="practice_type"),
        nullable=False, comment="课内练习/变式练习/代码作业",
    )
    content = Column(Text, nullable=False, comment="题目或代码内容")
    is_correct = Column(Boolean, nullable=True, comment="是否正确,未批改时为空")
    created_at = Column(DateTime, server_default=func.now())
