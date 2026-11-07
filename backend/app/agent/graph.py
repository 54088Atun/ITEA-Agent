"""LangGraph 状态图构建

流转:
START → router(含前置风控)
  ├─ block → END(风控拦截直接输出引导话术)
  └─ prepare(课程可见性校验) → planner(输出带依赖的任务图)
       → 业务节点(teacher/tutor/review/interview/admin)
         → tool_executor → plan_patch(中转计划调整)
           ├─ 有调整 → 带新约束回业务节点重跑
           └─ 无调整 → planner(仅在工具失败/证据不足时追加一次重规划)
                 ├─ planned/replanned → 业务节点
                 └─ skipped/exhausted → reflect
                       ├─ passed → memory_write → END
                       └─ failed → 回业务节点重写(reflect 内部控制最大循环次数)
"""
import logging

from langgraph.graph import StateGraph, START, END

from app.agent.state import AgentState
from app.agent.nodes import (
    router_node,
    risk_guard_node,
    reflect_node,
    memory_write_node,
    tool_executor_node,
    plan_patch_node,
    planner_node,
    teacher_node,
    tutor_node,
    review_node,
    interview_node,
    admin_node,
    collab_plan_node,
    collab_execute_node,
    collab_merge_node,
)
from app.db.session import SessionLocal
from app.models.course import Course
from app.models.user import User
from app.services.course_access import can_view_course

logger = logging.getLogger(__name__)

BUSINESS_NODES = ["teacher", "tutor", "review", "interview", "admin"]


def _visible_course_id(state: AgentState) -> int | None:
    """校验课程可见性:不可见或不存在时按"无课程"处理,避免越权检索与编造学情"""
    course_id = state.get("course_id")
    if not course_id:
        return None
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == state["user_id"]).first()
        course = db.query(Course).filter(Course.id == course_id).first()
        if not user or not course:
            return None
        return course_id if can_view_course(user, course, db) else None
    finally:
        db.close()


# ---------- 路由函数 ----------

def route_after_router(state: AgentState) -> str:
    """router 之后:block 直接结束,否则进入准备阶段"""
    if state.get("branch") == "block":
        return "block"
    return "prepare"


def route_by_branch(state: AgentState) -> str:
    """按分支路由到业务节点"""
    branch = state.get("branch", "tutor")
    if branch == "team":
        return "collab_plan"
    if branch in BUSINESS_NODES:
        return branch
    return "tutor"


def route_after_collab_plan(state: AgentState) -> str:
    """协作规划之后:有并行计划则执行专家,否则降级到单 Agent 业务节点"""
    if state.get("collab_plan"):
        return "collab_execute"
    branch = state.get("branch", "tutor")
    return branch if branch in BUSINESS_NODES else "tutor"


def route_after_business(state: AgentState) -> str:
    """业务节点之后:有待执行工具调用才进入执行节点,否则直接进入计划调整"""
    return "tool_executor" if state.get("tool_calls") else "plan_patch"


def route_after_reflect(state: AgentState) -> str:
    """反思之后:通过→档案回写,未通过→回业务节点重写"""
    if state.get("reflection_passed", True):
        return "memory_write"
    # 协作分支只需重跑汇总,不重新拆解与执行专家
    if state.get("branch") == "team":
        return "collab_merge"
    # 回到对应业务节点重写(reflect 内部有最大循环控制,不会死循环)
    return route_by_branch(state)


def route_after_plan_patch(state: AgentState) -> str:
    """计划调整之后:有生效调整→带新约束重跑作答;否则进入反思"""
    if not state.get("plan_revisions"):
        return "reflect"
    if state.get("branch") == "team":
        return "collab_merge"
    return route_by_branch(state)


def route_after_planner(state: AgentState) -> str:
    """规划之后:计划/重规划→业务节点;无需重规划或已达上限→反思"""
    status = state.get("plan_status") or ""
    if status in ("planned", "replanned"):
        branch = state.get("branch", "tutor")
        if branch == "team":
            return "collab_merge" if status == "replanned" else "collab_plan"
        return branch if branch in BUSINESS_NODES else "tutor"
    return "reflect"


# ---------- 准备节点 ----------

def prepare_node(state: AgentState) -> dict:
    """准备节点:只做课程可见性校验

    学情、课程资料、班级统计等数据改由各 Agent 在运行时直接调用
    `app.agent.data_api` 获取,不再预加载快照,避免数据过期与越权复用。
    """
    if state.get("branch") == "admin":
        logger.info("admin 分支不绑定课程,跳过课程可见性校验")
        return {"course_id": None}
    return {"course_id": _visible_course_id(state)}


# ---------- 图构建 ----------

def build_graph(checkpointer=None):
    """构建并编译 LangGraph 状态图

    checkpointer: 传入检查点存储时,每个超级步的状态会落盘,支持中断后恢复;
    不传则保持无状态执行(离线评估等一次性场景用)。
    """
    g = StateGraph(AgentState)

    # 注册节点
    g.add_node("router", router_node)
    g.add_node("risk_guard", risk_guard_node)
    g.add_node("prepare", prepare_node)
    g.add_node("planner", planner_node)
    g.add_node("teacher", teacher_node)
    g.add_node("tutor", tutor_node)
    g.add_node("review", review_node)
    g.add_node("interview", interview_node)
    g.add_node("admin", admin_node)
    g.add_node("collab_plan", collab_plan_node)
    g.add_node("collab_execute", collab_execute_node)
    g.add_node("collab_merge", collab_merge_node)
    g.add_node("tool_executor", tool_executor_node)
    g.add_node("plan_patch", plan_patch_node)
    g.add_node("reflect", reflect_node)
    g.add_node("memory_write", memory_write_node)

    # 入口
    g.add_edge(START, "router")

    # router → block: 风控处理 / prepare: 正常流程
    g.add_conditional_edges("router", route_after_router, {
        "block": "risk_guard",
        "prepare": "prepare",
    })

    # 风控处理 → END(输出引导话术 + 记录风控日志)
    g.add_edge("risk_guard", END)

    # prepare → planner(首次生成带依赖的任务图)
    g.add_edge("prepare", "planner")

    # planner → 计划/重规划:业务节点 / 无需重规划或已达上限:反思
    g.add_conditional_edges("planner", route_after_planner, {
        "teacher": "teacher",
        "tutor": "tutor",
        "review": "review",
        "interview": "interview",
        "admin": "admin",
        "collab_plan": "collab_plan",
        "collab_merge": "collab_merge",
        "reflect": "reflect",
    })

    # 业务节点 → 有工具调用:执行 / 无调用:直接计划调整(不进入执行节点)
    for n in BUSINESS_NODES:
        g.add_conditional_edges(n, route_after_business, {
            "tool_executor": "tool_executor",
            "plan_patch": "plan_patch",
        })

    # 多 Agent 协作:规划 → (并行执行专家 | 降级单 Agent) → 汇总 → 统一校验
    g.add_conditional_edges("collab_plan", route_after_collab_plan, {
        "collab_execute": "collab_execute",
        "teacher": "teacher",
        "tutor": "tutor",
        "review": "review",
        "interview": "interview",
        "admin": "admin",
    })
    g.add_edge("collab_execute", "collab_merge")
    g.add_conditional_edges("collab_merge", route_after_business, {
        "tool_executor": "tool_executor",
        "plan_patch": "plan_patch",
    })

    # 工具执行 → 计划调整(用户在生成中途提交的约束在此生效)
    g.add_edge("tool_executor", "plan_patch")

    # 计划调整 → 有调整:带新约束重跑作答 / 无调整:交由 planner 判定是否重规划
    g.add_conditional_edges("plan_patch", route_after_plan_patch, {
        "reflect": "planner",
        "teacher": "teacher",
        "tutor": "tutor",
        "review": "review",
        "interview": "interview",
        "admin": "admin",
        "collab_merge": "collab_merge",
    })

    # 反思 → passed: memory_write / failed: 回业务节点重写
    g.add_conditional_edges("reflect", route_after_reflect, {
        "memory_write": "memory_write",
        "teacher": "teacher",
        "tutor": "tutor",
        "review": "review",
        "interview": "interview",
        "admin": "admin",
        "collab_merge": "collab_merge",
    })

    # 档案回写 → END
    g.add_edge("memory_write", END)

    if checkpointer is not None:
        compiled = g.compile(checkpointer=checkpointer)
    else:
        compiled = g.compile()
    logger.info("LangGraph 状态图构建完成(16 节点, checkpointer=%s)",
                "on" if checkpointer is not None else "off")
    return compiled


# 全局单例(应用启动时构建一次)
_graph_instance = None


def get_graph():
    """获取编译后的图单例(挂载数据库检查点,支持中断恢复)"""
    global _graph_instance
    if _graph_instance is None:
        from app.agent.checkpoint import get_checkpointer

        _graph_instance = build_graph(checkpointer=get_checkpointer())
    return _graph_instance