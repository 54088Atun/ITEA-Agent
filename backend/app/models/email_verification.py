"""邮箱验证码表:只保存 HMAC 摘要,数据库泄露也无法还原明文码"""
from sqlalchemy import (
    Column, BigInteger, String, DateTime, Integer, Index, func,
)
from app.db.session import Base

BigIntPK = BigInteger().with_variant(Integer, "sqlite")


class EmailVerificationCode(Base):
    __tablename__ = "email_verification_codes"

    id = Column(BigIntPK, primary_key=True, autoincrement=True)
    email = Column(String(100), nullable=False, index=True, comment="标准化小写邮箱")
    purpose = Column(
        String(20), nullable=False, comment="register / reset_password",
    )
    code_hash = Column(
        String(64), nullable=False, comment="HMAC-SHA256(SECRET_KEY, purpose:email:code)",
    )
    expires_at = Column(DateTime, nullable=False, comment="过期时间")
    attempts = Column(
        Integer, nullable=False, default=0, server_default="0", comment="校验失败次数",
    )
    consumed_at = Column(DateTime, nullable=True, comment="消费时间(成功/作废)")
    request_ip = Column(String(64), nullable=True, comment="申请 IP,用于限流")
    created_at = Column(DateTime, nullable=False, server_default=func.now())

    __table_args__ = (
        Index("ix_email_code_lookup", "email", "purpose", "created_at"),
        Index("ix_email_code_ip", "request_ip", "created_at"),
    )
