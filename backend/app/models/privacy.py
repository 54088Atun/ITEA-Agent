"""隐私设置模型:每个用户一条(PC-07)"""
from sqlalchemy import (
    Column, BigInteger, DateTime, ForeignKey, Integer, String, func,
)

from app.db.session import Base

BigIntPK = BigInteger().with_variant(Integer, "sqlite")


class PrivacySetting(Base):
    __tablename__ = "privacy_settings"

    id = Column(BigIntPK, primary_key=True, autoincrement=True)
    user_id = Column(
        BigInteger, ForeignKey("users.id"), unique=True, nullable=False, index=True,
    )
    name_visibility = Column(
        String(20), nullable=False, default="classmates", server_default="classmates",
        comment="姓名可见范围:private/teachers/classmates",
    )
    email_visibility = Column(
        String(20), nullable=False, default="private", server_default="private",
        comment="邮箱可见范围:private/teachers/classmates",
    )
    learning_visibility = Column(
        String(20), nullable=False, default="teachers", server_default="teachers",
        comment="学习记录可见范围:private/teachers/classmates",
    )
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
