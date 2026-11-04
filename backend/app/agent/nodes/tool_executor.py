"""tool_executor:工具执行节点

职责:
- 读取 state.tool_calls 中的工具调用请求(LLM Function Calling 产出)
- 按名称查 TOOL_REGISTRY 执行对应工具
- 结果写入 state.tool_results 供业务节点注入 prompt
"""
import json
import logging
import time

from app.agent.state import AgentState
from app.agent.tools import TOOL_REGISTRY
from app.services.prompt_guard import sanitize_payload

logger = logging.getLogger(__name__)

# 工具 Schema 描述(供 LLM bind_tools 使用)
TOOL_SCHEMAS = [
    {
        "name": "rag_search",
        "description": "知识库检索:答疑/备课/出题前必调,返回带来源标注的知识片段",
        "parameters": {
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
    },
    {
        "name": "code_executor",
        "description": "沙箱执行代码:学生代码排错,返回 stdout/stderr/exit_code",
        "parameters": {
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
    },
    {
        "name": "doc_generator",
        "description": "文档生成:教师教案/预习单/学情报表,返回下载链接",
        "parameters": {
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
    },
    {
        "name": "stats_analyzer",
        "description": "学情统计:班级薄弱知识点 TOP-N、进度趋势、掌握度分布",
        "parameters": {
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
    },
    {
        "name": "reminder_scheduler",
        "description": "定时提醒:错题复习提醒、面试实训提醒",
        "parameters": {
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
    },
    {
        "name": "sql_query",
        "description": "只读 SQL 分析:在白名单视图上执行聚合查询,返回结果表",
        "parameters": {
            "type": "object",
            "properties": {
                "sql": {"type": "string", "description": "单条 SELECT 语句,只能引用白名单视图"},
                "course_id": {"type": "integer", "description": "课程范围"},
            },
            "required": ["sql"],
        },
    },
    {
        "name": "project.search_code",
        "description": "项目自检:按关键词搜索代码与文档,返回文件、行号与片段",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "字面量关键词"},
                "path": {"type": "string", "description": "相对项目根目录的子目录"},
                "limit": {"type": "integer", "description": "返回条数,默认 20"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "project.read_file",
        "description": "项目自检:读取项目内文本文件,限制文件大小与单次行数",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "相对项目根目录的文件路径"},
                "start_line": {"type": "integer", "description": "起始行,默认 1"},
                "end_line": {"type": "integer", "description": "结束行,默认按上限"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "project.git_diff",
        "description": "项目自检:查看当前工作区 diff,只执行固定 git 命令",
        "parameters": {
            "type": "object",
            "properties": {
                "stat_only": {"type": "boolean", "description": "只返回统计信息"},
            },
        },
    },
    {
        "name": "project.search_logs",
        "description": "项目自检:检索项目日志,按关键词与级别过滤",
        "parameters": {
            "type": "object",
            "properties": {
                "keyword": {"type": "string", "description": "关键词"},
                "level": {"type": "string", "description": "级别,如 error"},
                "limit": {"type": "integer", "description": "返回条数,默认 100"},
            },
        },
    },
    {
        "name": "project.run_tests",
        "description": "项目自检:执行预置测试集,不接受任意 shell 参数",
        "parameters": {
            "type": "object",
            "properties": {
                "suite": {
                    "type": "string",
                    "enum": ["all", "agent", "api", "security"],
                    "description": "预置测试集",
                },
            },
        },
    },
    {
        "name": "project.db_schema",
        "description": "项目自检:查看数据库表与字段结构,不返回业务数据",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "web.search",
        "description": "受控联网搜索:需要配置服务商,结果带来源链接",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜索问题"},
                "top_k": {"type": "integer", "description": "返回条数,默认 5"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "web.fetch",
        "description": "受控抓取:只允许白名单域名的 HTML/文本页面",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "http/https 链接"},
            },
            "required": ["url"],
        },
    },
    {
        "name": "course_evidence",
        "description": "课程资料检索:回答课程事实题、备课、出题前调用,返回带来源的片段",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "检索问题或关键词"},
                "course_id": {"type": "integer", "description": "课程 ID"},
                "top_k": {"type": "integer", "description": "返回条数,默认 5"},
            },
            "required": ["query", "course_id"],
        },
    },
    {
        "name": "profile_query",
        "description": "学情读取:需要个性化辅导、定位薄弱点时调用,返回压缩后的学情摘要",
        "parameters": {
            "type": "object",
            "properties": {
                "course_id": {"type": "integer", "description": "课程 ID"},
            },
        },
    },
    {
        "name": "admin.course_list",
        "description": "管理端课程查询:按审核状态/关键词列出课程,带素材数与知识点数",
        "parameters": {
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
    },
    {
        "name": "admin.material_stats",
        "description": "管理端素材统计:按课程统计素材与知识点数量,素材少的排在前面",
        "parameters": {
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
    },
    {
        "name": "admin.user_lookup",
        "description": "管理端账号查询:按角色/状态/姓名筛选,不返回邮箱与密码",
        "parameters": {
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
    },
    {
        "name": "admin.risk_summary",
        "description": "管理端风控总览:近 N 天命中总数、类型分布与最近记录",
        "parameters": {
            "type": "object",
            "properties": {
                "days": {"type": "integer", "description": "统计天数,默认 7"},
            },
        },
    },
    {
        "name": "admin.config_get",
        "description": "管理端配置读取:按 key 查询系统配置,敏感项返回掩码",
        "parameters": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "配置键,缺省表示全部"},
            },
        },
    },
]


def tool_schemas_for_role(role: str) -> list[dict]:
    """按角色能力矩阵过滤工具 Schema,避免把越权工具暴露给模型"""
    from app.services.capabilities import ROLE_CAPABILITIES

    allowed = set((ROLE_CAPABILITIES.get(role) or {}).get("tools") or [])
    return [schema for schema in TOOL_SCHEMAS if schema["name"] in allowed]


def _apply_scope_defaults(name: str, args: dict, state: AgentState,
                          tool, spec) -> None:
    """最小权限:课程与用户范围以会话上下文为准,不接受模型自行切换

    模型给出的 course_id/user_id 若与上下文不一致,直接按上下文收口并留痕,
    防止提示注入诱导读取其他课程或其他用户的数据。
    """
    signature = set(tool.__code__.co_varnames[:tool.__code__.co_argcount])
    properties = (spec.parameters.get("properties") or {}) if spec else {}

    def _force(key: str, state_value) -> bool:
        """有上下文值时覆盖模型入参并留痕;返回是否已处理"""
        if not state_value:
            return False
        requested = args.get(key)
        if requested not in (None, "", state_value):
            logger.warning(
                "工具 %s 请求 %s=%s 超出上下文 %s,已按上下文收口",
                name, key, requested, state_value,
            )
        args[key] = state_value
        return True

    # 显式声明参数的走签名;仅用 **kwargs 接收的工具,只在模型传了该参数时收口
    state_course = state.get("course_id")
    if "course_id" in signature:
        if not _force("course_id", state_course) and "course_id" not in args:
            args["course_id"] = 1  # 兼容旧行为:无课程上下文时用默认课程
    elif state_course and "course_id" in args and "course_id" in properties:
        _force("course_id", state_course)

    state_user = state.get("user_id")
    if "user_id" in signature:
        _force("user_id", state_user)
    elif state_user and "user_id" in args and "user_id" in properties:
        _force("user_id", state_user)


def _execute_single(call: dict, state: AgentState) -> dict:
    """执行单个工具调用,所有出口统一走 tool_result 契约"""
    from app.agent.tools.gateway import (
        UNTRUSTED_TOOLS,
        get_tool_spec,
        tool_result,
        validate_tool_arguments,
    )

    started = time.perf_counter()
    name = call.get("name", "")
    args = dict(call.get("arguments") or {})

    def _elapsed() -> float:
        return (time.perf_counter() - started) * 1000

    def _fail(message: str, **extra) -> dict:
        payload = tool_result(False, None, error=message, latency_ms=_elapsed())
        # 保留顶层附加字段(available / requires_confirmation),兼容既有消费方
        payload.update(extra)
        return payload

    tool = TOOL_REGISTRY.get(name)
    if not tool:
        return _fail(f"未知工具: {name}", available=list(TOOL_REGISTRY.keys()))

    from app.services.capabilities import ROLE_CAPABILITIES, tool_denied_reason

    role = state.get("user_role") or "student"
    denial = tool_denied_reason(role, name)
    if denial:
        logger.warning("工具越权被拒绝: role=%s tool=%s", role, name)
        available = ROLE_CAPABILITIES.get(role, {}).get("tools", [])
        return _fail(denial, available=available)

    spec = get_tool_spec(name)
    # 注入默认参数:course_id / user_id 从 state 补全并强制收口
    _apply_scope_defaults(name, args, state, tool, spec)

    if spec is not None:
        allowed_extra = set(tool.__code__.co_varnames[:tool.__code__.co_argcount])
        reason = validate_tool_arguments(spec, args, allowed_extra)
        if reason:
            logger.warning("工具参数被拒绝: %s", reason)
            return _fail(reason)

    try:
        result = tool(**args)
    except TypeError as e:
        logger.warning("工具参数错误(%s): %s", name, e)
        return _fail(f"工具 {name} 参数错误: {e}")
    except Exception as e:
        logger.error("工具执行失败(%s): %s", name, e)
        return _fail(f"工具 {name} 执行失败: {e}")

    logger.info("工具执行成功: %s(args=%s)", name, list(args.keys()))
    if not isinstance(result, dict):
        result = {"result": result}
    return tool_result(
        True,
        result,
        sources=result.get("sources"),
        latency_ms=_elapsed(),
        untrusted=name in UNTRUSTED_TOOLS,
    )


async def tool_executor_node(state: AgentState) -> dict:
    """工具执行节点:批量执行 tool_calls,结果合并写入 tool_results

    安全策略(P1-6):单轮总量与单工具次数上限、高危工具需显式确认、
    返回内容按不可信数据处理(命中指令覆盖就地中和)。
    """
    calls = state.get("tool_calls") or []
    if not calls:
        return {"tool_results": {}}

    from app.agent.tools.gateway import (
        MAX_CALLS_PER_BATCH,
        get_tool_spec,
        tool_result,
    )

    results: dict[str, dict] = {}
    counts: dict[str, int] = {}
    rejected = 0
    for i, call in enumerate(calls):
        name = (call or {}).get("name", f"tool_{i}")
        if i >= MAX_CALLS_PER_BATCH:
            results[name] = tool_result(
                False,
                None,
                error=f"单轮工具调用超过上限 {MAX_CALLS_PER_BATCH},已拒绝",
            )
            rejected += 1
            continue

        spec = get_tool_spec(name)
        if spec is not None and spec.requires_confirmation and not call.get("confirmed"):
            payload = tool_result(False, None, error=f"高危工具 {name} 需用户确认后执行")
            # 顶层附加字段:前端据此弹出确认卡片
            payload["requires_confirmation"] = True
            results[name] = payload
            rejected += 1
            continue

        limit = spec.max_calls_per_turn if spec is not None else 3
        used = counts.get(name, 0)
        if used >= limit:
            results[name] = tool_result(
                False,
                None,
                error=f"工具 {name} 单轮最多调用 {limit} 次",
            )
            rejected += 1
            continue

        counts[name] = used + 1
        results[name] = sanitize_payload(_execute_single(call, state))

    if rejected:
        logger.warning(
            "工具调用被安全策略拒绝 %s 次(session=%s)",
            rejected, state.get("session_id"),
        )
    return {"tool_results": results, "tool_calls": []}