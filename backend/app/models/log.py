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
    security_level = Column(
        String(20), nullable=True, comment="信息分级:public/internal/sensitive/confidential",
    )
    created_at = Column(DateTime, server_default=func.now())


class RiskLog(Base):
    """风控拦截日志"""
    __tablename__ = "risk_logs"

    id = Column(BigIntPK, primary_key=True, autoincrement=True)
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


class WriteAuditLog(Base):
    """统一写操作审计(AG-07):每条写入记录审批级别与执行结果"""
    __tablename__ = "write_audits"

    id = Column(BigIntPK, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, nullable=False, index=True)
    user_role = Column(String(20), nullable=False)
    action = Column(String(60), nullable=False, index=True, comment="写操作标识")
    action_label = Column(String(100), nullable=False, comment="写操作名称")
    approval_mode = Column(String(20), nullable=False, comment="full/auto/manual")
    status = Column(String(20), nullable=False, comment="executed/blocked")
    target_type = Column(String(40))
    target_id = Column(BigInteger)
    detail = Column(Text)
    created_at = Column(DateTime, server_default=func.now())


class AgentRun(Base):
    """Agent 运行记录:用于回放路由、工具调用、反思与耗时"""
    __tablename__ = "agent_runs"

    id = Column(BigIntPK, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, nullable=False, index=True)
    session_id = Column(String(64), nullable=False, index=True)
    request_id = Column(String(64), nullable=True, index=True)
    role = Column(String(20), nullable=False)
    branch = Column(String(30), nullable=True)
    status = Column(
        String(20), nullable=False, default="running", server_default="running",
        comment="running/success/error/blocked/cancelled/failed/dead",
    )
    input_preview = Column(String(500))
    output_preview = Column(Text)
    steps = Column(Text, comment="步骤 JSON 数组")
    error = Column(Text)
    duration_ms = Column(Integer)
    created_at = Column(DateTime, server_default=func.now())
    finished_at = Column(DateTime, nullable=True)


class AgentRunSpan(Base):
    """Agent 每步 span:route/plan/tool/reflect/answer,支持失败回放"""
    __tablename__ = "agent_run_spans"

    id = Column(BigIntPK, primary_key=True, autoincrement=True)
    run_id = Column(BigInteger, nullable=False, index=True)
    seq = Column(Integer, nullable=False, comment="同一次运行内的步骤序号")
    kind = Column(
        String(20), nullable=False, comment="route/plan/tool/reflect/answer",
    )
    name = Column(String(60), comment="节点或工具名")
    status = Column(String(20), nullable=False, default="ok", server_default="ok",
                    comment="ok/error/blocked/skipped")
    payload = Column(Text, comment="入参 JSON")
    result = Column(Text, comment="结果摘要 JSON")
    tokens = Column(Integer, comment="该步 token 估算")
    duration_ms = Column(Integer, comment="该步耗时")
    error = Column(Text)
    created_at = Column(DateTime, server_default=func.now())


class AgentPlanRevision(Base):
    """运行中途的计划调整:用户在生成过程中追加约束,下一超级步生效"""
    __tablename__ = "agent_plan_revisions"

    id = Column(BigIntPK, primary_key=True, autoincrement=True)
    run_id = Column(BigInteger, nullable=False, index=True)
    session_id = Column(String(64), nullable=False, index=True)
    user_id = Column(BigInteger, nullable=False, index=True)
    instruction = Column(String(500), nullable=False, comment="用户追加的调整要求")
    status = Column(
        String(20), nullable=False, default="pending", server_default="pending",
        comment="pending/applied/expired",
    )
    applied_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now())


class AgentCheckpoint(Base):
    """LangGraph 检查点:按超级步落盘状态快照,进程中断后可从中恢复"""
    __tablename__ = "agent_checkpoints"

    id = Column(BigIntPK, primary_key=True, autoincrement=True)
    thread_id = Column(String(64), nullable=False, index=True, comment="会话/运行归属线程")
    checkpoint_ns = Column(
        String(64), nullable=False, default="", server_default="", comment="子图命名空间",
    )
    checkpoint_id = Column(String(64), nullable=False, index=True, comment="检查点 ID(字典序即先后)")
    parent_checkpoint_id = Column(String(64), comment="父检查点 ID")
    run_id = Column(BigInteger, index=True, comment="关联运行")
    session_id = Column(String(64), index=True)
    node = Column(String(60), comment="写入来源:input/loop/update")
    seq = Column(Integer, nullable=False, default=0, server_default="0", comment="同线程内序号")
    state = Column(Text, comment="检查点快照(序列化后 base64)")
    checkpoint_meta = Column(Text, comment="检查点元数据(序列化后 base64)")
    writes = Column(Text, comment="未完成写入 JSON")
    status = Column(String(20), nullable=False, default="ok", server_default="ok", comment="ok/error")
    created_at = Column(DateTime, server_default=func.now())


class AgentDeadLetter(Base):
    """失败运行死信队列:记录失败原因与恢复所需输入,支持重放"""
    __tablename__ = "agent_dead_letters"

    id = Column(BigIntPK, primary_key=True, autoincrement=True)
    run_id = Column(BigInteger, index=True)
    user_id = Column(BigInteger, nullable=False, index=True)
    session_id = Column(String(64), index=True)
    request_id = Column(String(64), index=True)
    reason = Column(String(200), comment="失败原因摘要")
    payload = Column(Text, comment="恢复所需输入 JSON")
    status = Column(
        String(20), nullable=False, default="pending", server_default="pending",
        comment="pending/replayed/discarded",
    )
    retry_count = Column(Integer, nullable=False, default=0, server_default="0")
    last_run_id = Column(BigInteger, comment="重放后生成的新 run")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class SystemConfig(Base):
    """系统配置表(管理端专属)"""
    __tablename__ = "system_config"

    id = Column(BigIntPK, primary_key=True, autoincrement=True)
    config_key = Column(String(100), unique=True, nullable=False)
    config_value = Column(Text)
    description = Column(String(200))
    updated_by = Column(BigInteger, ForeignKey("users.id"), comment="最后修改人")
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())