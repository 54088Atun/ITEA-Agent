"""学生通知与通知偏好"""
from sqlalchemy import (
    Boolean, Column, BigInteger, Integer, String, Text, DateTime, ForeignKey,
    UniqueConstraint, func,
)
from app.db.session import Base

BigIntPK = BigInteger().with_variant(Integer, "sqlite")


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "source_type", "source_id",
            name="uq_notification_source",
        ),
    )

    id = Column(BigIntPK, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False, index=True)
    category = Column(String(20), nullable=False, index=True)
    title = Column(String(200), nullable=False)
    message = Column(Text, nullable=False)
    link_url = Column(String(500), nullable=True)
    source_type = Column(String(30), nullable=False)
    source_id = Column(String(100), nullable=False)
    is_read = Column(Boolean, nullable=False, default=False, server_default="0")
    read_at = Column(DateTime, nullable=True)
    deliver_at = Column(DateTime, nullable=False, index=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())


class NotificationPreference(Base):
    __tablename__ = "notification_preferences"

    id = Column(BigIntPK, primary_key=True, autoincrement=True)
    user_id = Column(
        BigInteger, ForeignKey("users.id"), nullable=False, unique=True, index=True,
    )
    assignment_enabled = Column(Boolean, nullable=False, default=True, server_default="1")
    exam_enabled = Column(Boolean, nullable=False, default=True, server_default="1")
    interview_enabled = Column(Boolean, nullable=False, default=True, server_default="1")
    review_enabled = Column(Boolean, nullable=False, default=True, server_default="1")
    quiet_start = Column(String(5), nullable=True, comment="免打扰开始 HH:MM")
    quiet_end = Column(String(5), nullable=True, comment="免打扰结束 HH:MM")
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
