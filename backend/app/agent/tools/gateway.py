"""Agent 工具网关:统一工具描述、角色可见性与调用契约

本模块只负责“工具目录”，不直接执行业务逻辑。
执行仍由 tool_executor 按 TOOL_REGISTRY 完成，后续接入 LLM bind_tools 时
直接复用这里的 schema，避免工具描述散落在各节点里。
"""
from dataclasses import dataclass

from app.services.capabilities import ROLE_CAPABILITIES


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
        description="知识库检索:答疑、备课、出题前调用,返回带来源标注的知识片段",
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
        name="code_executor",
        description="沙箱执行代码:学生代码排错,返回 stdout/stderr/exit_code",
        parameters={
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "待执行代码"},
                "language": {
                    "type": "string",
                    "enum": ["python", "java", "cpp"],
                    "description": "编程语言,默认 python",
                },
                "timeout": {"type": "integer", "description": "超时秒数,上限 10"},
            },
            "required": ["code"],
        },
        roles=("student", "admin"),
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
                "trigger_at": {"type": "string", "description": "触发时间(ISO 格式)"},
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
    """返回当前角色可用的工具目录,未授权工具不下发"""
    allowed = set(ROLE_CAPABILITIES.get(role, {}).get("tools", []))
    return [spec.to_dict() for spec in TOOL_SPECS if spec.name in allowed]


def get_tool_spec(name: str) -> ToolSpec | None:
    return _SPEC_BY_NAME.get(name)


# 单轮工具调用总量上限:超过只执行前 N 个,其余拒绝
MAX_CALLS_PER_BATCH = 8

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

    只拦截「伪造参数、越界枚举、类型错误」,必填项缺失仍交给工具自身报错,
    避免改变既有调用链的异常语义。
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
    return None


def tool_schemas(role: str) -> list[dict]:
    """OpenAI/DeepSeek 风格的 function calling schema"""
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
