"""任务规划节点:输出带依赖的任务图,并在执行失败或证据不足时触发一次重规划

规划只在链路的两个位置生效:
- prepare 之后:首次进入业务节点前生成 3~5 步计划;
- plan_patch 之后(无用户中途调整):检查工具执行结果,必要时追加一条重规划步骤。

重规划不写 plan_revisions,避免与用户中途提交的计划调整语义冲突。
"""
import logging

from app.agent.state import AgentState

logger = logging.getLogger(__name__)

MAX_REPLANS = 1
MAX_PLAN_STEPS = 5
MAX_REASON_ITEMS = 3
PLACEHOLDER_CONTEXTS = ("(缺少课程或检索词,未检索)", "(未检索到相关内容)")


def _question(state: AgentState) -> str:
    """取最近一条用户消息作为检索词,缺失时给通用检索词"""
    for msg in reversed(state.get("messages") or []):
        if (msg or {}).get("role") == "user":
            text = str(msg.get("content") or "").strip()
            if text:
                return text[:80]
    return "课程知识要点"


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
            ("分析学情,定位薄弱知识点", "stats_analyzer",
             {"course_id": course_id, "metric": "weakness"}),
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
            ("分析学情,定位薄弱点", "stats_analyzer",
             {"course_id": course_id, "metric": "weakness"}),
            ("读取学情档案,匹配讲解深度", "profile_query",
             {"course_id": course_id}),
            ("汇总生成教案框架", "doc_generator",
             {"doc_type": "lesson_plan", "data": {"course_id": course_id}}),
        ],
    }

    steps = specs.get(branch) or specs["tutor"]
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
        new_plan = _build_plan(branch, state)
        logger.info("任务规划完成 branch=%s 步骤数=%s", branch, len(new_plan))
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
        "args": {},
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
