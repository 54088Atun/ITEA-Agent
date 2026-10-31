"""学情档案相关表:学情档案、掌握度、错题、复习计划"""
from sqlalchemy import (
    Column, BigInteger, String, Text, Enum, Integer, DECIMAL, DateTime,
    ForeignKey, UniqueConstraint, func,
)
from app.db.session import Base

BigIntPK = BigInteger().with_variant(Integer, "sqlite")


class StudentProfile(Base):
    """学情档案表 —— 全模块共享核心,单一数据源"""
    __tablename__ = "student_profiles"

    id = Column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True, autoincrement=True,
    )
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False, index=True)
    course_id = Column(BigInteger, ForeignKey("courses.id"), nullable=False, index=True)
    overall_progress = Column(DECIMAL(5, 2), default=0, comment="总体进度%")
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class MasteryRecord(Base):
    """知识点掌握度表"""
    __tablename__ = "mastery_records"

    id = Column(BigIntPK, primary_key=True, autoincrement=True)
    profile_id = Column(BigInteger, ForeignKey("student_profiles.id"), nullable=False, index=True)
    kp_id = Column(BigInteger, ForeignKey("knowledge_points.id"), nullable=False, index=True)
    mastery_level = Column(Integer, default=0, comment="掌握度 0-100")
    last_assessed_at = Column(DateTime, server_default=func.now())


class WrongQuestion(Base):
    """错题集表"""
    __tablename__ = "wrong_questions"
    __table_args__ = (
        UniqueConstraint("profile_id", "source_type", "source_id", name="uq_wrong_question_source"),
    )

    id = Column(BigIntPK, primary_key=True, autoincrement=True)
    profile_id = Column(BigInteger, ForeignKey("student_profiles.id"), nullable=False, index=True)
    kp_id = Column(BigInteger, ForeignKey("knowledge_points.id"), nullable=True, comment="关联知识点,未匹配时为空")
    question_content = Column(Text, nullable=False)
    error_type = Column(String(50), comment="概念/逻辑/语法")
    source_type = Column(String(30), nullable=True, comment="manual/exam_record 等来源")
    source_id = Column(String(100), nullable=True, comment="来源内唯一标识")
    created_at = Column(DateTime, server_default=func.now())


class ReviewPlan(Base):
    """复习计划表 —— 遗忘曲线驱动"""
    __tablename__ = "review_plans"

    id = Column(BigIntPK, primary_key=True, autoincrement=True)
    wrong_question_id = Column(BigInteger, ForeignKey("wrong_questions.id"), nullable=False, index=True)
    next_review_at = Column(DateTime, nullable=False, index=True)
    review_count = Column(Integer, default=0, comment="已复习次数")
    interval_days = Column(Integer, default=1, comment="当前间隔天数")
    status = Column(Enum("pending", "done", "expired", name="review_status"), default="pending")
