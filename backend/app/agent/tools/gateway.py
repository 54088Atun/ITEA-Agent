"""Agent 工具网关:统一工具描述、角色可见性与调用契约

本模块只负责“工具目录”，不直接执行业务逻辑。
执行仍由 tool_executor 按 TOOL_REGISTRY 完成，后续接入 LLM bind_tools 时
直接复用这里的 schema，避免工具描述散落在各节点里。
"""
import logging
from dataclasses import dataclass

from app.services.capabilities import ROLE_CAPABILITIES

logger = logging.getLogger(__name__)

# 工具决策审计:只记录决策元数据,从不记录调用参数
tool_audit_logger = logging.getLogger("app.audit.tool")

AUDIT_FIELDS = ("request_id", "role", "tool", "decision", "reason")


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict
    roles: tuple[str, ...] = ("teacher", "student", "admin")
    read_only: bool = True
    requires_confirmation: bool = False
    timeout_ms: int = 8000
    max_calls_per_turn: int = 3

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
            "roles": list(self.roles),
            "read_only": self.read_only,
            "requires_confirmation": self.requires_confirmation,
            "timeout_ms": self.timeout_ms,
            "max_calls_per_turn": self.max_calls_per_turn,
        }


TOOL_SPECS: tuple[ToolSpec, ...] = (
    ToolSpec(
        name="rag_search",
        description=(
            "知识库检索:仅在已构建课程索引时可用,未配置时返回明确不可用;"
            "课程事实题优先使用 course_evidence"
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "检索问题或关键词"},
                "course_id": {"type": "integer", "description": "课程 ID"},
                "scope": {
                    "type": "string",
                    "enum": ["courseware", "syllabus", "exercise", "interview"],
                    "description": "检索范围,默认不限",
                },
                "top_k": {"type": "integer", "description": "返回条数,默认 5"},
            },
            "required": ["query", "course_id"],
        },
        roles=("teacher", "student", "admin"),
    ),
    ToolSpec(
        name="doc_generator",
        description="文档生成:教师教案、预习单、学情报表,返回下载链接",
        parameters={
            "type": "object",
            "properties": {
                "doc_type": {
                    "type": "string",
                    "enum": ["lesson_plan", "preview_sheet", "report"],
                    "description": "文档类型",
                },
                "data": {"type": "object", "description": "文档内容数据"},
            },
            "required": ["doc_type", "data"],
        },
        roles=("teacher", "admin"),
        read_only=False,
    ),
    ToolSpec(
        name="stats_analyzer",
        description="学情统计:班级薄弱知识点 TOP-N、进度趋势、掌握度分布",
        parameters={
            "type": "object",
            "properties": {
                "course_id": {"type": "integer", "description": "课程 ID"},
                "metric": {
                    "type": "string",
                    "enum": ["weakness", "progress", "distribution"],
                    "description": "统计维度",
                },
                "top_n": {"type": "integer", "description": "TOP-N 条数,默认 10"},
            },
            "required": ["course_id", "metric"],
        },
        roles=("teacher", "admin"),
    ),
    ToolSpec(
        name="reminder_scheduler",
        description="定时提醒:错题复习提醒、面试实训提醒",
        parameters={
            "type": "object",
            "properties": {
                "user_id": {"type": "integer", "description": "用户 ID"},
                "task_type": {
                    "type": "string",
                    "enum": ["review", "interview"],
                    "description": "任务类型",
                },
                "trigger_at": {
                    "type": "string",
                    "description": (
                        "触发时间，带时区的 ISO 8601，"
                        "如 2026-11-10T20:00:00+08:00；相对日期按当前时间换算"
                    ),
                },
            },
            "required": ["user_id", "task_type"],
        },
        roles=("teacher", "student", "admin"),
        read_only=False,
        requires_confirmation=True,
    ),
    ToolSpec(
        name="sql_query",
        description="只读 SQL 分析:在白名单视图上执行聚合查询,返回结果表",
        parameters={
            "type": "object",
            "properties": {
                "sql": {"type": "string", "description": "单条 SELECT 语句,只能引用白名单视图"},
                "course_id": {"type": "integer", "description": "课程范围"},
            },
            "required": ["sql"],
        },
        roles=("teacher", "admin"),
        read_only=True,
        timeout_ms=5000,
        max_calls_per_turn=2,
    ),
    ToolSpec(
        name="project.search_code",
        description="项目自检:按关键词搜索代码与文档,返回文件、行号与片段",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "字面量关键词"},
                "path": {"type": "string", "description": "相对项目根目录的子目录"},
                "limit": {"type": "integer", "description": "返回条数,默认 20"},
            },
            "required": ["query"],
        },
        roles=("admin",),
    ),
    ToolSpec(
        name="project.read_file",
        description="项目自检:读取项目内文本文件,限制文件大小与单次行数",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "相对项目根目录的文件路径"},
                "start_line": {"type": "integer", "description": "起始行,默认 1"},
                "end_line": {"type": "integer", "description": "结束行,默认按上限"},
            },
            "required": ["path"],
        },
        roles=("admin",),
    ),
    ToolSpec(
        name="project.git_diff",
        description="项目自检:查看当前工作区 diff,只执行固定 git 命令",
        parameters={
            "type": "object",
            "properties": {
                "stat_only": {"type": "boolean", "description": "只返回统计信息"},
            },
        },
        roles=("admin",),
    ),
    ToolSpec(
        name="project.search_logs",
        description="项目自检:检索项目日志,按关键词与级别过滤",
        parameters={
            "type": "object",
            "properties": {
                "keyword": {"type": "string", "description": "关键词"},
                "level": {"type": "string", "description": "级别,如 error"},
                "limit": {"type": "integer", "description": "返回条数,默认 100"},
            },
        },
        roles=("admin",),
    ),
    ToolSpec(
        name="project.run_tests",
        description="项目自检:执行预置测试集,不接受任意 shell 参数",
        parameters={
            "type": "object",
            "properties": {
                "suite": {
                    "type": "string",
                    "enum": ["all", "agent", "api", "security"],
                    "description": "预置测试集",
                },
            },
        },
        roles=("admin",),
        read_only=False,
        requires_confirmation=True,
    ),
    ToolSpec(
        name="project.db_schema",
        description="项目自检:查看数据库表与字段结构,不返回业务数据",
        parameters={"type": "object", "properties": {}},
        roles=("admin",),
    ),
    ToolSpec(
        name="web.search",
        description="受控联网搜索:需要配置服务商,结果带来源链接",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜索问题"},
                "top_k": {"type": "integer", "description": "返回条数,默认 5"},
            },
            "required": ["query"],
        },
        roles=("teacher", "admin"),
    ),
    ToolSpec(
        name="web.fetch",
        description="受控抓取:只允许白名单域名的 HTML/文本页面",
        parameters={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "http/https 链接"},
            },
            "required": ["url"],
        },
        roles=("teacher", "admin"),
    ),
    ToolSpec(
        name="course_evidence",
        description="课程资料检索:回答课程事实题、备课、出题前调用,返回带来源的片段",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "检索问题或关键词"},
                "course_id": {"type": "integer", "description": "课程 ID"},
                "top_k": {"type": "integer", "description": "返回条数,默认 5"},
            },
            "required": ["query", "course_id"],
        },
        roles=("teacher", "student", "admin"),
    ),
    ToolSpec(
        name="profile_query",
        description="学情读取:需要个性化辅导、定位薄弱点时调用,返回压缩后的学情摘要",
        parameters={
            "type": "object",
            "properties": {
                "course_id": {"type": "integer", "description": "课程 ID"},
            },
        },
        roles=("teacher", "student", "admin"),
    ),
    ToolSpec(
        name="workspace_overview",
        description="读取当前用户全部课程/班级/作业/考试概览",
        parameters={"type": "object", "properties": {}},
        roles=("teacher", "student", "admin"),
        read_only=True,
        max_calls_per_turn=2,
    ),
    ToolSpec(
        name="workspace_action",
        description=(
            "执行当前用户有权限的写操作:课程/班级/成员/作业/题目/试卷;"
            "需人工确认后执行"
        ),
        parameters={
            "type": "object",
            "properties": {
                "action": {"type": "string"},
                "params": {"type": "object"},
                "summary": {"type": "string"},
            },
            "required": ["action", "params", "summary"],
        },
        roles=("teacher", "student", "admin"),
        read_only=False,
        requires_confirmation=True,
        max_calls_per_turn=2,
        timeout_ms=30000,
    ),
    ToolSpec(
        name="admin.course_list",
        description="管理端课程查询:按审核状态/关键词列出课程,带素材数与知识点数",
        parameters={
            "type": "object",
            "properties": {
                "audit_status": {
                    "type": "string",
                    "enum": ["pending", "approved", "rejected"],
                },
                "keyword": {"type": "string", "description": "课程名或课程代码关键词"},
                "limit": {"type": "integer", "description": "返回条数,默认 10"},
            },
        },
        roles=("admin",),
    ),
    ToolSpec(
        name="admin.material_stats",
        description="管理端素材统计:按课程统计素材与知识点数量,素材少的排在前面",
        parameters={
            "type": "object",
            "properties": {
                "course_ids": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "限定课程 ID,缺省表示全部",
                },
                "limit": {"type": "integer", "description": "返回条数,默认 20"},
            },
        },
        roles=("admin",),
    ),
    ToolSpec(
        name="admin.user_lookup",
        description="管理端账号查询:按角色/状态/姓名筛选,不返回邮箱与密码",
        parameters={
            "type": "object",
            "properties": {
                "keyword": {"type": "string", "description": "姓名关键词"},
                "role": {
                    "type": "string",
                    "enum": ["teacher", "student", "admin"],
                },
                "status": {"type": "string", "enum": ["active", "disabled"]},
                "limit": {"type": "integer", "description": "返回条数,默认 10"},
            },
        },
        roles=("admin",),
    ),
    ToolSpec(
        name="admin.risk_summary",
        description="管理端风控总览:近 N 天命中总数、类型分布与最近记录",
        parameters={
            "type": "object",
            "properties": {
                "days": {"type": "integer", "description": "统计天数,默认 7"},
            },
        },
        roles=("admin",),
    ),
    ToolSpec(
        name="admin.config_get",
        description="管理端配置读取:按 key 查询系统配置,敏感项返回掩码",
        parameters={
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "配置键,缺省表示全部"},
            },
        },
        roles=("admin",),
    ),
)

_SPEC_BY_NAME = {spec.name: spec for spec in TOOL_SPECS}


def available_tools(role: str) -> list[dict]:
    """返回当前角色可用的工具目录,未授权或当前不可用的工具不下发"""
    allowed = set(ROLE_CAPABILITIES.get(role, {}).get("tools", []))
    specs = [spec for spec in TOOL_SPECS if spec.name in allowed]
    from app.services.web_access import web_search_enabled
    if not web_search_enabled():
        specs = [spec for spec in specs if spec.name != "web.search"]
    return [spec.to_dict() for spec in specs]


def get_tool_spec(name: str) -> ToolSpec | None:
    return _SPEC_BY_NAME.get(name)


@dataclass(frozen=True)
class ToolApproval:
    """可信审批上下文:只能由服务端在用户显式确认后构造

    模型输出、工具 arguments 和客户端传入的 confirmed 都无权构造本对象,
    因此 `requires_confirmation` 只能被真正的人工确认放行。
    """

    tools: frozenset[str] = frozenset()

    def allows(self, name: str) -> bool:
        return name in self.tools


def coerce_tool_approval(value) -> ToolApproval | None:
    """把服务端状态里的审批声明归一为可信对象;无法识别时按未确认处理"""
    if value is None:
        return None
    if isinstance(value, ToolApproval):
        return value
    if isinstance(value, dict):
        names = value.get("tools") or ()
    elif isinstance(value, (list, tuple, set, frozenset)):
        names = value
    else:
        return None
    tools = frozenset(str(item) for item in names if item)
    return ToolApproval(tools=tools) if tools else None


def audit_tool_decision(
    *, request_id, role, tool, decision: str, reason: str = "",
) -> None:
    """记录工具决策审计:字段固定,严禁携带调用参数或业务正文"""
    payload = {
        "request_id": str(request_id or ""),
        "role": str(role or ""),
        "tool": str(tool or ""),
        "decision": decision,
        "reason": str(reason or ""),
    }
    tool_audit_logger.info("tool_decision", extra={"tool_audit": payload})


# 单轮工具调用总量上限:超过只执行前 N 个,其余拒绝
MAX_CALLS_PER_BATCH = 8


class TurnQuota:
    """单轮工具配额:由共享执行边界统一扣减,节点与工具循环复用同一规则"""

    def __init__(self, batch_limit: int | None = None):
        self.batch_limit = MAX_CALLS_PER_BATCH if batch_limit is None else batch_limit
        self._batch = 0
        self._used: dict[str, int] = {}

    def consume_batch(self) -> str | None:
        self._batch += 1
        if self._batch > self.batch_limit:
            return f"单轮工具调用超过上限 {self.batch_limit},已拒绝"
        return None

    def consume_tool(self, name: str, limit: int) -> str | None:
        used = self._used.get(name, 0)
        if used >= limit:
            return f"工具 {name} 单轮最多调用 {limit} 次"
        self._used[name] = used + 1
        return None


_TYPE_CHECKS = {
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
}


def validate_tool_arguments(
    spec: ToolSpec, args: dict, allowed_extra: set[str] | None = None,
) -> str | None:
    """按工具 schema 校验参数;返回拒绝原因,None 表示通过

    拦截「伪造参数、越界枚举、类型错误与缺失必填项」;必填参数缺失或为 None
    时在执行前直接拒绝,不再交给工具自身报错。
    """
    if not isinstance(args, dict):
        return f"工具 {spec.name} 参数必须是对象"

    properties = (spec.parameters or {}).get("properties") or {}
    allowed = set(properties) | set(allowed_extra or ())
    unknown = sorted(set(args) - allowed)
    if unknown:
        return f"工具 {spec.name} 不接受参数: {', '.join(unknown)}"

    for key, schema in properties.items():
        if key not in args or args[key] is None:
            continue
        expected = schema.get("type")
        check = _TYPE_CHECKS.get(expected)
        if check and not check(args[key]):
            return f"工具 {spec.name} 参数 {key} 类型应为 {expected}"
        enum = schema.get("enum")
        if enum and args[key] not in enum:
            return f"工具 {spec.name} 参数 {key} 取值不在允许范围: {enum}"

    required = (spec.parameters or {}).get("required") or []
    for key in required:
        if key not in args or args[key] is None:
            return f"工具 {spec.name} 缺少必需参数: {key}"
    return None


def tool_schemas(role: str) -> list[dict]:
    """OpenAI/DeepSeek 风格的 function calling schema

    注意:运行时的模型目录以 `nodes.tool_executor.tool_schemas_for_role` 为准,
    本函数仅供外部集成与契约校验复用,两者都从 TOOL_SPECS + 角色能力矩阵生成。
    """
    return [
        {
            "type": "function",
            "function": {
                "name": spec.name,
                "description": spec.description,
                "parameters": spec.parameters,
            },
        }
        for spec in TOOL_SPECS
        if spec.name in set(ROLE_CAPABILITIES.get(role, {}).get("tools", []))
    ]


# 返回内容来自外部资料的工具:交给模型前按不可信输入处理
UNTRUSTED_TOOLS = frozenset({
    "rag_search",
    "course_evidence",
    "web.search",
    "web.fetch",
    "project.search_code",
    "project.read_file",
    "project.search_logs",
})


def tool_result(
    ok: bool,
    data: dict | None = None,
    error: str | None = None,
    sources: list | None = None,
    latency_ms: float | int | None = None,
    untrusted: bool = False,
) -> dict:
    """统一工具返回契约:{ok, data, error, sources, latency_ms, untrusted}

    所有工具出口都走这里,下游只需认这六个字段:
    - ok 表示调用是否成功,error 仅在失败时非空
    - data 保留工具原始业务字段(context/fragments/summary 等)
    - sources 为可追溯来源,sources 为空表示本轮无可引用出处
    """
    if data is None:
        payload: dict = {}
    elif isinstance(data, dict):
        payload = dict(data)
    else:
        payload = {"result": data}
    return {
        "ok": bool(ok),
        "data": payload,
        "error": error,
        "sources": list(sources or []),
        "latency_ms": int(latency_ms or 0),
        "untrusted": bool(untrusted),
    }


def tool_timeout_seconds(spec: ToolSpec | None, fallback: float) -> float:
    """单次工具调用超时:优先用工具自身 timeout_ms,超出兜底时以兜底收口

    fallback 同时是全局上限,便于测试与运维统一收紧。
    """
    if spec is None or spec.timeout_ms <= 0:
        return fallback
    return min(spec.timeout_ms / 1000, fallback)
