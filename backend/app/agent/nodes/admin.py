"""admin:管理后台只读数据解读与治理指引节点"""
import json
import logging

from sqlalchemy import func

from app.agent.llm import llm_invoke
from app.agent.prompts import load_prompt, render_prompt
from app.agent.state import AgentState
from app.db.session import SessionLocal
from app.models.course import Course, CourseMaterial, KnowledgePoint
from app.models.log import InteractionLog, RiskLog
from app.models.user import User

logger = logging.getLogger(__name__)

AI_TAG = "[AI 辅助参考,请管理员复核]"


def _load_platform_stats() -> dict:
    """使用独立会话只读聚合平台数据,不写业务表。"""
    db = SessionLocal()
    try:
        role_counts = dict(
            db.query(User.role, func.count(User.id)).group_by(User.role).all()
        )
        course_counts = dict(
            db.query(Course.audit_status, func.count(Course.id))
            .group_by(Course.audit_status)
            .all()
        )
        return {
            "users_by_role": role_counts,
            "courses_by_audit_status": course_counts,
            "knowledge_points": db.query(func.count(KnowledgePoint.id)).scalar() or 0,
            "materials": db.query(func.count(CourseMaterial.id)).scalar() or 0,
            "risk_logs": db.query(func.count(RiskLog.id)).scalar() or 0,
            "interaction_logs": db.query(func.count(InteractionLog.id)).scalar() or 0,
        }
    finally:
        db.close()


async def admin_node(state: AgentState) -> dict:
    """聚合平台快照并流式生成只读管理建议。"""
    try:
        stats = _load_platform_stats()
    except Exception as e:
        logger.warning("管理员平台统计读取失败: %s", e)
        stats = {"error": "平台统计暂时不可用,请仅提供通用操作指引"}

    system_prompt = render_prompt(
        load_prompt("admin"),
        admin_level=state.get("admin_level") or "super",
        platform_stats=json.dumps(stats, ensure_ascii=False, indent=2),
    )
    reflection_notes = state.get("reflection_notes", "")
    if reflection_notes:
        system_prompt += (
            "\n\n【反思校验意见】上一轮回答存在以下问题,请修正后重新回答:\n"
            + reflection_notes
        )

    messages = [{"role": "system", "content": system_prompt}]
    for message in state.get("messages", [])[-6:]:
        messages.append({
            "role": message.get("role", "user"),
            "content": message.get("content", ""),
        })

    try:
        output = await llm_invoke(messages, sink=state.get("stream_queue"))
    except Exception as e:
        logger.error("admin LLM 调用失败: %s", e)
        output = f"抱歉,管理助手暂时无法响应,请稍后重试。{AI_TAG}"

    if AI_TAG not in output:
        output += f"\n\n{AI_TAG}"
    return {"final_output": output}
