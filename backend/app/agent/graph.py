"""LangGraph 状态图构建

流转:
START → router(含前置风控)
  ├─ block → END(风控拦截直接输出引导话术)
  └─ prepare(学情快照 + 强制RAG检索,admin 跳过) → 业务节点(teacher/tutor/review/interview/admin)
       → tool_executor → reflect
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
    memory_load_node,
    memory_write_node,
    tool_executor_node,
    teacher_node,
    tutor_node,
    review_node,
    interview_node,
    admin_node,
)
from app.agent.tools.rag_search import rag_search
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
    if branch in BUSINESS_NODES:
        return branch
    return "tutor"


def route_after_reflect(state: AgentState) -> str:
    """反思之后:通过→档案回写,未通过→回业务节点重写"""
    if state.get("reflection_passed", True):
        return "memory_write"
    # 回到对应业务节点重写(reflect 内部有最大循环控制,不会死循环)
    return route_by_branch(state)


# ---------- 准备节点 ----------

def prepare_node(state: AgentState) -> dict:
    """准备节点:业务分支加载学情与 RAG,admin 仅使用平台只读聚合。"""
    if state.get("branch") == "admin":
        logger.info("admin 分支跳过课程学情与课程 RAG")
        return {"profile_snapshot": {}, "rag_context": "", "course_id": None}

    # 1. 学情快照(课程不可见时按无课程处理,不读取他人学情)
    course_id = _visible_course_id(state)
    scope_state = {**state, "course_id": course_id}
    updates = memory_load_node(scope_state)

    # 2. 强制 RAG 检索:基于用户最新消息;无可见课程时不做课程检索
    user_input = ""
    messages = state.get("messages", [])
    if messages:
        user_input = messages[-1].get("content", "")

    if user_input and course_id:
        try:
            rag_result = rag_search(query=user_input, course_id=course_id, top_k=5)
            updates["rag_context"] = rag_result.get("context", "")
            logger.info("RAG 检索完成(course=%s, fragments=%d)",
                        course_id, len(rag_result.get("fragments", [])))
        except Exception as e:
            logger.warning("RAG 检索失败(降级为空上下文): %s", e)
            updates["rag_context"] = ""
    else:
        updates["rag_context"] = ""

    # 回写可见课程,供反思与档案回写使用;不可见时置空,避免越权
    updates["course_id"] = course_id
    return updates


# ---------- 图构建 ----------

def build_graph():
    """构建并编译 LangGraph 状态图"""
    g = StateGraph(AgentState)

    # 注册节点
    g.add_node("router", router_node)
    g.add_node("risk_guard", risk_guard_node)
    g.add_node("prepare", prepare_node)
    g.add_node("teacher", teacher_node)
    g.add_node("tutor", tutor_node)
    g.add_node("review", review_node)
    g.add_node("interview", interview_node)
    g.add_node("admin", admin_node)
    g.add_node("tool_executor", tool_executor_node)
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

    # prepare → 业务节点(按分支路由)
    g.add_conditional_edges("prepare", route_by_branch, {
        "teacher": "teacher",
        "tutor": "tutor",
        "review": "review",
        "interview": "interview",
        "admin": "admin",
    })

    # 业务节点 → 工具执行
    for n in BUSINESS_NODES:
        g.add_edge(n, "tool_executor")

    # 工具执行 → 反思
    g.add_edge("tool_executor", "reflect")

    # 反思 → passed: memory_write / failed: 回业务节点重写
    g.add_conditional_edges("reflect", route_after_reflect, {
        "memory_write": "memory_write",
        "teacher": "teacher",
        "tutor": "tutor",
        "review": "review",
        "interview": "interview",
        "admin": "admin",
    })

    # 档案回写 → END
    g.add_edge("memory_write", END)

    compiled = g.compile()
    logger.info("LangGraph 状态图构建完成(11 节点)")
    return compiled


# 全局单例(应用启动时构建一次)
_graph_instance = None


def get_graph():
    """获取编译后的图单例"""
    global _graph_instance
    if _graph_instance is None:
        _graph_instance = build_graph()
    return _graph_instance