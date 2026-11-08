"""profile_query:学情读取工具(P0-2 按需调用)

返回压缩后的学情摘要,避免把完整档案塞进工具结果与对话轮次。
"""
import logging

from app.agent import data_api
from app.agent.context import compress_profile

logger = logging.getLogger(__name__)


def profile_query(
    course_id: int | None = None,
    user_id: int | None = None,
    user_role: str = "student",
    student_id: int | None = None,
) -> dict:
    """读取学情,返回压缩摘要

    Args:
        course_id: 课程 ID(由会话上下文强制收口)
        user_id: 用户 ID(由会话上下文强制收口)
        user_role: 调用者角色
        student_id: 教师/管理员查看指定学生时填写;学生填了也无效

    Returns:
        {"summary": 压缩后的学情文本}
    """
    profile = data_api.fetch_profile(
        user_id or 0, course_id, user_role, student_id,
    )
    if not profile:
        return {"summary": "(暂无学情数据)"}
    return {"summary": compress_profile(profile)}
