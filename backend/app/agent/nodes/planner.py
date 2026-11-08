"""任务规划节点:输出带依赖的任务图,并在执行失败或证据不足时触发一次重规划

规划只在链路的两个位置生效:
- prepare 之后:首次进入业务节点前生成 3~5 步计划;
- plan_patch 之后(无用户中途调整):检查工具执行结果,必要时追加一条重规划步骤。

重规划不写 plan_revisions,避免与用户中途提交的计划调整语义冲突。
"""
import logging

from app.agent.state import AgentState
from app.core.config import settings

logger = logging.getLogger(__name__)

MAX_REPLANS = 1
MAX_PLAN_STEPS = 5
MAX_REASON_ITEMS = 3
PLACEHOLDER_CONTEXTS = ("(缺少课程或检索词,未检索)", "(未检索到相关内容)")
# 检索类工具必须带 query,重规划与 LLM 规划都要补齐
RETRIEVAL_TOOLS = ("course_evidence", "rag_search")


def _question(state: AgentState) -> str:
    """取最近一条用户消息作为检索词,缺失时给通用检索词"""
    for msg in reversed(state.get("messages") or []):
        if (msg or {}).get("role") == "user":
            text = str(msg.get("content") or "").strip()
            if text:
                return text[:80]
    return "课程知识要点"


def _allowed_steps(steps: list[tuple], state: AgentState) -> list[tuple]:
    """按调用者角色过滤计划步骤;全部被过滤时保留一条无工具的说明步骤"""
    from app.services.capabilities import tool_denied_reason

    role = state.get("user_role") or "student"
    allowed = [
        item for item in steps
        if not item[1] or tool_denied_reason(role, item[1]) is None
    ]
    if allowed:
        return allowed
    return [("理解问题并组织回答", "", {"query": _question(state)})]


def _build_plan(branch: str, state: AgentState) -> list[dict]:
    """按分支生成带依赖的任务图(每步只描述规划,不在此执行)"""
    course_id = state.get("course_id")
    user_id = state.get("user_id")
    query = _question(state)

    specs = {
        "teacher": [
            ("检索课程资料,确认讲解依据", "course_evidence",
             {"query": query, "course_id": course_id}),
            ("分析班级学情,定位薄弱点", "stats_analyzer",
             {"course_id": course_id, "metric": "weakness"}),
            ("生成教案框架", "doc_generator",
             {"doc_type": "lesson_plan", "data": {"course_id": course_id}}),
        ],
        "tutor": [
            ("检索课程资料,确认知识依据", "course_evidence",
             {"query": query, "course_id": course_id}),
            ("读取学情档案,匹配讲解深度", "profile_query",
             {"course_id": course_id}),
            ("补充检索已建索引资料", "rag_search",
             {"query": query, "course_id": course_id}),
        ],
        "review": [
            ("检索课程资料,确认复习范围", "course_evidence",
             {"query": query, "course_id": course_id}),
            # 复盘是学生入口:原计划里的 stats_analyzer 学生无权调用,改为读取本人学情
            ("读取学情档案,定位薄弱知识点", "profile_query",
             {"course_id": course_id}),
            ("安排复习提醒", "reminder_scheduler",
             {"user_id": user_id, "task_type": "review"}),
        ],
        "interview": [
            ("检索课程资料,确认考察依据", "course_evidence",
             {"query": query, "course_id": course_id}),
            ("读取学情档案,匹配提问难度", "profile_query",
             {"course_id": course_id}),
            ("补充检索面试常考素材", "rag_search",
             {"query": query, "course_id": course_id, "scope": "interview"}),
        ],
        "admin": [
            ("列出课程概览", "admin.course_list", {"limit": 10}),
            ("统计资料审核情况", "admin.material_stats", {}),
            ("汇总近期风险", "admin.risk_summary", {"days": 7}),
        ],
        "team": [
            ("检索课程资料,确认共同依据", "course_evidence",
             {"query": query, "course_id": course_id}),
            # 协作入口由发起者角色驱动,计划只列各角色都可用的工具
            ("读取学情档案,匹配讲解深度", "profile_query",
             {"course_id": course_id}),
            ("补充检索已建索引资料", "rag_search",
             {"query": query, "course_id": course_id}),
        ],
    }

    steps = specs.get(branch) or specs["tutor"]
    # 计划即承诺:过滤调用者无权使用的工具,避免展示"调不动的步骤"
    steps = _allowed_steps(steps, state)
    return _render_plan(steps)


def _render_plan(steps: list[tuple]) -> list[dict]:
    """把 (title, tool, args) 步骤渲染成带依赖链的任务图"""
    plan = []
    for idx, (title, tool, args) in enumerate(steps[:MAX_PLAN_STEPS], start=1):
        plan.append({
            "step": idx,
            "title": title,
            "tool": tool,
            "args": args,
            "depends_on": [idx - 1] if idx > 1 else [],
            "status": "pending",
        })
    return plan


def _normalize_steps(raw: dict, state: AgentState, allowed: set[str]) -> list[tuple]:
    """校验模型输出的步骤:丢弃越权工具、补齐检索参数"""
    query = _question(state)
    course_id = state.get("course_id")
    steps: list[tuple] = []
    for item in (raw.get("steps") or []) if isinstance(raw, dict) else []:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        tool = str(item.get("tool") or "").strip()
        if tool and tool not in allowed:
            logger.info("规划丢弃越权工具: %s", tool)
            continue
        args = dict(item.get("args") or {}) if isinstance(item.get("args"), dict) else {}
        if tool in RETRIEVAL_TOOLS:
            args.setdefault("query", query)
            if course_id is not None:
                args.setdefault("course_id", course_id)
        steps.append((title[:60], tool, args))
        if len(steps) >= MAX_PLAN_STEPS:
            break
    return steps


async def _llm_plan(state: AgentState) -> list[tuple] | None:
    """用一次低成本模型调用生成计划;不可用或输出非法时返回 None 走模板"""
    from app.agent.llm import llm_invoke
    from app.agent.prompts import load_prompt, render_prompt
    from app.agent.nodes.router import _parse_json
    from app.agent.nodes.tool_executor import tool_schemas_for_role

    role = state.get("user_role") or "student"
    schemas = tool_schemas_for_role(role)
    if not schemas:
        return None
    catalog = "\n".join(
        f"- {schema['name']}: {schema.get('description', '')}" for schema in schemas
    )
    try:
        raw_text = await llm_invoke(
            [
                {
                    "role": "system",
                    "content": render_prompt(
                        load_prompt("planner"), catalog=catalog,
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"用户身份:{role}\n课程 ID:{state.get('course_id')}\n"
                        f"用户问题:{_question(state)}"
                    ),
                },
            ],
            temperature=0.0,
        )
        raw = _parse_json(raw_text)
    except Exception as exc:  # noqa: BLE001
        logger.warning("LLM 规划不可用,回退静态模板: %s", exc)
        return None

    steps = _normalize_steps(raw, state, {schema["name"] for schema in schemas})
    return steps or None


def _has_evidence(data) -> bool:
    """判断课程资料检索是否拿到可用证据(非占位上下文或有片段均算)"""
    if not isinstance(data, dict):
        return False
    context = str(data.get("context") or "").strip()
    if context and context not in PLACEHOLDER_CONTEXTS:
        return True
    return bool(data.get("fragments"))


def _failed_tools(state: AgentState) -> list[tuple[str, str]]:
    """收集工具失败记录(六字段契约中 ok=False 即失败)"""
    failures = []
    for item in state.get("tool_trace") or []:
        result = (item or {}).get("result")
        if isinstance(result, dict) and result.get("ok") is False:
            name = (item or {}).get("name") or "unknown"
            error = str(result.get("error") or "未知错误")[:120]
            failures.append((name, error))
    return failures


def _evidence_missing(state: AgentState) -> bool:
    """course_evidence 被调用过但全部未拿到证据"""
    called = False
    for item in state.get("tool_trace") or []:
        if (item or {}).get("name") != "course_evidence":
            continue
        called = True
        result = (item or {}).get("result")
        data = result.get("data") if isinstance(result, dict) else None
        if _has_evidence(data):
            return False
    return called


def _retry_args(state: AgentState, tool: str, query: str) -> dict:
    """重试步骤参数:优先复用上次调用参数,并补齐检索工具必需参数

    只写空 args 会让网关判定「必填参数缺失」,重规划实际必然失败。
    """
    args: dict = {}
    for item in reversed(state.get("tool_trace") or []):
        if (item or {}).get("name") == tool:
            args = dict((item or {}).get("arguments") or {})
            break
    if tool in ("course_evidence", "rag_search"):
        args.setdefault("query", query)
        if state.get("course_id") is not None:
            args.setdefault("course_id", state["course_id"])
    elif tool == "profile_query" and state.get("course_id") is not None:
        args.setdefault("course_id", state["course_id"])
    return args


def _detect_replan_reason(state: AgentState) -> str:
    """判定是否需要重规划,返回原因;无需重规划返回空串"""
    failures = _failed_tools(state)
    if failures:
        detail = ";".join(
            f"{name}:{error}" for name, error in failures[:MAX_REASON_ITEMS]
        )
        return f"工具执行失败({detail})"
    if _evidence_missing(state):
        return "课程资料检索无可用证据,需调整检索策略"
    return ""


async def planner_node(state: AgentState) -> dict:
    """首次生成任务计划;之后仅在有失败/证据不足时追加一条重规划步骤"""
    plan = list(state.get("task_plan") or [])
    replan_count = int(state.get("replan_count") or 0)

    if not plan:
        branch = state.get("branch") or "tutor"
        steps = None
        if getattr(settings, "PLANNER_LLM_ENABLED", False):
            steps = await _llm_plan(state)
        new_plan = _render_plan(steps) if steps else _build_plan(branch, state)
        logger.info(
            "任务规划完成 branch=%s 步骤数=%s 来源=%s",
            branch, len(new_plan), "llm" if steps else "template",
        )
        return {
            "task_plan": new_plan,
            "current_step": len(new_plan),
            "plan_status": "planned",
            "replan_reason": "",
            "replan_count": replan_count,
        }

    reason = _detect_replan_reason(state)
    if not reason:
        return {"plan_status": "skipped", "replan_reason": ""}

    if replan_count >= MAX_REPLANS:
        logger.warning("重规划已达上限 %s,不再重试 原因=%s", MAX_REPLANS, reason)
        return {"plan_status": "exhausted", "replan_reason": reason}

    cursor = int(state.get("current_step") or len(plan)) + 1
    failures = _failed_tools(state)
    retry_tool = failures[0][0] if failures else "course_evidence"
    plan.append({
        "step": cursor,
        "title": f"重规划:依据「{reason}」调整后重试",
        "tool": retry_tool,
        "args": _retry_args(state, retry_tool, _question(state)),
        "depends_on": [cursor - 1] if cursor > 1 else [],
        "status": "pending",
        "action": "replan",
        "reason": reason,
    })
    logger.info("触发重规划(第 %s 次) 原因=%s", replan_count + 1, reason)
    return {
        "task_plan": plan,
        "current_step": cursor,
        "plan_status": "replanned",
        "replan_count": replan_count + 1,
        "replan_reason": reason,
    }
