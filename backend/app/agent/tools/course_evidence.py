"""course_evidence:课程资料检索工具(P0-2 按需调用)

与业务主链路同源:内部复用 `app.agent.data_api.fetch_course_evidence`,
走课程检索内部 API,避免与本地 FAISS 索引形成两套不一致的检索结果。
"""
import logging

from app.agent import data_api

logger = logging.getLogger(__name__)


def course_evidence(
    query: str,
    course_id: int,
    top_k: int = 5,
    user_id: int | None = None,
    user_role: str = "student",
) -> dict:
    """检索课程资料,返回带来源标注的上下文与片段元数据

    Args:
        query: 检索问题或关键词
        course_id: 课程 ID(由会话上下文强制收口)
        top_k: 返回条数
        user_id: 调用者 ID(由会话上下文强制收口),用于课程可见性校验
        user_role: 调用者角色

    Returns:
        {"context": 带来源标注的文本, "fragments": [{text, source, page, ...}]}
    """
    if not query or not course_id:
        return {"context": "(缺少课程或检索词,未检索)", "fragments": []}

    evidence = data_api.fetch_course_evidence(
        query, course_id, user_id or 0, user_role, top_k,
    )
    if not evidence:
        return {"context": "(未检索到相关内容)", "fragments": []}

    return {
        "context": evidence.get("context", "") or "",
        "fragments": evidence.get("fragments", []) or [],
    }
