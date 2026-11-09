"""用户表"""
from sqlalchemy import Column, BigInteger, String, Enum, DateTime, Integer, func
from app.db.session import Base

# SQLite 仅支持 INTEGER PRIMARY KEY 自增,测试库用变体兼容;MySQL 仍为 BIGINT
BigIntPK = BigInteger().with_variant(Integer, "sqlite")


class User(Base):
    __tablename__ = "users"

    id = Column(BigIntPK, primary_key=True, autoincrement=True)
    role = Column(Enum("teacher", "student", "admin", name="user_role"), nullable=False, index=True)
    admin_level = Column(String(20), nullable=True, comment="管理员级别: super/normal/observer")
    name = Column(String(50), nullable=False)
    avatar_url = Column(String(255), nullable=True, comment="头像相对路径")
    email = Column(String(100), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    status = Column(
        Enum("active", "disabled", name="user_status"),
        nullable=False, default="active", server_default="active",
        comment="账号状态(管理端启停用)",
    )
    token_version = Column(
        Integer, nullable=False, default=0, server_default="0",
        comment="令牌版本号,改密/登出全部设备时递增使旧 JWT 失效",
    )
    email_verified_at = Column(DateTime, nullable=True, comment="邮箱验证通过时间")
    created_at = Column(DateTime, server_default=func.now())