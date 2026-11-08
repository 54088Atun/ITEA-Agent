"""Agent 数据访问门面

所有业务 Agent 运行时通过这里按需取数,内部统一走项目内 API(路由层函数),
不再依赖 prepare 预加载的 profile_snapshot / rag_context。
单个数据源失败统一降级,不阻断回答生成。
"""
import logging

from app.agent import internal_api

logger = logging.getLogger(__name__)


def _safe(name: str, fn, default):
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001
        logger.warning("数据 API 调用失败(%s): %s", name, exc)
        return default


def _recall_memories(user_id: int, course_id: int) -> dict:
    """跨会话记忆召回:情景记忆(近期事件)+ 语义偏好,供上下文压缩注入"""
    from app.services import agent_memory as mem_svc

    recalled: dict = {}
    episodic = mem_svc.list_recent_episodic(
        user_id, course_id, days=mem_svc.DEFAULT_RECALL_DAYS, limit=5,
    )
    if episodic:
        recalled["episodic_memories"] = episodic
    semantic = mem_svc.search_memory(
        user_id, course_id, query="", memory_type="semantic", limit=3,
    )
    if semantic:
        recalled["semantic_memories"] = semantic
    return recalled


def fetch_memories(
    user_id: int, course_id: int | None, role: str = "student",
) -> dict:
    """读取跨会话记忆(情景 + 语义);非学生或无课程时返回空"""
    if role != "student" or not course_id:
        return {}
    return _safe("memory_recall", lambda: _recall_memories(user_id, course_id), {})


def fetch_profile(
    user_id: int, course_id: int | None, role: str = "student",
    student_id: int | None = None,
) -> dict:
    """通过学生端内部 API 读取学情,并并入跨会话记忆

    student_id 仅教师/管理员使用:读取指定学生,归属校验在内部 API 完成。
    """
    profile = _safe(
        "profile_api",
        lambda: internal_api.fetch_profile_via_api(
            user_id, course_id, role, student_id,
        ),
        {},
    )
    # 学情为空时不额外查记忆库:没有档案的调用方(如教师)不需要召回
    if profile:
        memories = fetch_memories(user_id, course_id, role)
        if memories:
            profile = {**profile, **memories}
    return profile


def fetch_course_evidence(
    query: str, course_id: int | None, user_id: int,
    role: str = "student", top_k: int = 5,
) -> dict:
    """获取课程检索上下文与片段元数据(素材 ID/页码,供来源定位)"""
    return _safe(
        "course_search_api",
        lambda: internal_api.fetch_course_evidence_via_api(
            query, course_id, user_id, role, top_k,
        ),
        {},
    )


def fetch_course_context(
    query: str, course_id: int | None, user_id: int,
    role: str = "student", top_k: int = 5,
) -> str:
    """通过课程检索内部 API 获取上下文"""
    return fetch_course_evidence(query, course_id, user_id, role, top_k).get("context", "")


def fetch_syllabus(
    course_id: int | None, user_id: int, role: str = "teacher",
) -> str:
    """通过课程检索内部 API 获取大纲"""
    return _safe(
        "syllabus_api",
        lambda: internal_api.fetch_syllabus_via_api(course_id, user_id, role),
        "(暂无课程大纲,请教师上传教学大纲后使用)",
    )


def fetch_class_stats(
    course_id: int | None, user_id: int, role: str = "teacher",
    metric: str = "weakness", top_n: int = 10,
) -> dict:
    """通过班级内部 API 获取班级统计"""
    return _safe(
        "class_stats_api",
        lambda: internal_api.fetch_class_stats_via_api(
            course_id, user_id, role, metric, top_n,
        ),
        {},
    )


def fetch_interview_history(
    user_id: int, course_id: int | None, role: str = "student",
) -> dict:
    """面试记录包含在学情 API 响应中"""
    profile = fetch_profile(user_id, course_id, role)
    return profile.get("interview", {}) or {}
