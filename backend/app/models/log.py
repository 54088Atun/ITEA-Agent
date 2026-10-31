"""日志表:交互日志、风控日志、操作审计、系统配置"""
from sqlalchemy import Column, BigInteger, String, Text, DateTime, ForeignKey, Integer, func
from app.db.session import Base

BigIntPK = BigInteger().with_variant(Integer, "sqlite")


class InteractionLog(Base):
    """全量交互日志,可追溯"""
    __tablename__ = "interaction_logs"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, nullable=False, index=True)
    session_id = Column(String(64), nullable=False, index=True)
    role = Column(String(20), nullable=False)
    branch = Column(String(20), comment="teacher/tutor/review/interview/admin/block")
    content = Column(Text, comment="交互内容摘要")
    created_at = Column(DateTime, server_default=func.now())


class RiskLog(Base):
    """风控拦截日志"""
    __tablename__ = "risk_logs"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, nullable=False, index=True)
    request_content = Column(Text, nullable=False, comment="原始请求")
    risk_type = Column(String(50), comment="代写/索答案/替考/代写简历")
    action_taken = Column(String(50), comment="拦截/转引导")
    created_at = Column(DateTime, server_default=func.now())


class OperationLog(Base):
    """管理端操作审计日志"""
    __tablename__ = "operation_logs"

    id = Column(BigIntPK, primary_key=True, autoincrement=True)
    admin_id = Column(BigInteger, ForeignKey("users.id"), nullable=False, index=True)
    action = Column(String(50), nullable=False, comment="create/update/delete/disable/enable/approve/reject/config")
    target_type = Column(String(50), nullable=False, comment="user/course/material/config/risk_log")
    target_id = Column(BigInteger, comment="目标对象 ID")
    detail = Column(Text, comment="变更详情(含前后快照 JSON)")
    ip = Column(String(45))
    created_at = Column(DateTime, server_default=func.now())


class SystemConfig(Base):
    """系统配置表(管理端专属)"""
    __tablename__ = "system_config"

    id = Column(BigIntPK, primary_key=True, autoincrement=True)
    config_key = Column(String(100), unique=True, nullable=False)
    config_value = Column(Text)
    description = Column(String(200))
    updated_by = Column(BigInteger, ForeignKey("users.id"), comment="最后修改人")
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())