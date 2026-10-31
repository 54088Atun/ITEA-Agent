"""用户表"""
from sqlalchemy import Column, BigInteger, String, Enum, DateTime, func
from app.db.session import Base


class User(Base):
    __tablename__ = "users"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    role = Column(Enum("teacher", "student", "admin", name="user_role"), nullable=False, index=True)
    admin_level = Column(String(20), nullable=True, comment="管理员级别: super/normal/observer")
    name = Column(String(50), nullable=False)
    email = Column(String(100), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    status = Column(
        Enum("active", "disabled", name="user_status"),
        nullable=False, default="active", server_default="active",
        comment="账号状态(管理端启停用)",
    )
    created_at = Column(DateTime, server_default=func.now())