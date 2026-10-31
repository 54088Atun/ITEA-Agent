"""tool_executor:工具执行节点

职责:
- 读取 state.tool_calls 中的工具调用请求(LLM Function Calling 产出)
- 按名称查 TOOL_REGISTRY 执行对应工具
- 结果写入 state.tool_results 供业务节点注入 prompt
"""
import json
import logging

from app.agent.state import AgentState
from app.agent.tools import TOOL_REGISTRY

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
]


def _execute_single(call: dict, state: AgentState) -> dict:
    """执行单个工具调用"""
    name = call.get("name", "")
    args = call.get("arguments", {})

    tool = TOOL_REGISTRY.get(name)
    if not tool:
        return {"error": f"未知工具: {name}", "available": list(TOOL_REGISTRY.keys())}

    # 注入默认参数:course_id / user_id 从 state 补全
    if "course_id" in tool.__code__.co_varnames and "course_id" not in args:
        args["course_id"] = state.get("course_id") or 1
    if "user_id" in tool.__code__.co_varnames and "user_id" not in args:
        args["user_id"] = state.get("user_id")

    try:
        result = tool(**args)
        logger.info("工具执行成功: %s(args=%s)", name, list(args.keys()))
        return result if isinstance(result, dict) else {"result": str(result)}
    except TypeError as e:
        logger.warning("工具参数错误(%s): %s", name, e)
        return {"error": f"工具 {name} 参数错误: {e}"}
    except Exception as e:
        logger.error("工具执行失败(%s): %s", name, e)
        return {"error": f"工具 {name} 执行失败: {e}"}


async def tool_executor_node(state: AgentState) -> dict:
    """工具执行节点:批量执行 tool_calls,结果合并写入 tool_results"""
    calls = state.get("tool_calls") or []
    if not calls:
        return {"tool_results": {}}

    results: dict[str, dict] = {}
    for i, call in enumerate(calls):
        name = call.get("name", f"tool_{i}")
        results[name] = _execute_single(call, state)

    return {"tool_results": results, "tool_calls": []}