"""interview:简历诊断与模拟面试实训节点(学生端三级分支)

职责:
- 简历诊断:只给优化思路,绝不代写简历
- 模拟面试:基于薄弱知识点定向出题,多轮对话追问
- 面试结束后输出评分 + 薄弱点总结 → 写入 profile_updates
"""
import json
import logging

from app.agent.state import AgentState
from app.agent.llm import llm_invoke
from app.agent.prompts import load_prompt, render_prompt

logger = logging.getLogger(__name__)

MAX_HISTORY = 12


def _is_resume_request(user_input: str) -> bool:
    """判断是否简历诊断请求"""
    return any(kw in user_input for kw in ["简历", "求职", "实习经历", "项目经历描述"])


def _is_session_end(user_input: str) -> bool:
    """判断是否面试结束请求"""
    return any(kw in user_input for kw in ["结束面试", "面试结束", "总结一下", "打分", "结束吧"])


async def interview_node(state: AgentState) -> dict:
    """面试实训节点"""
    user_input = state["messages"][-1]["content"] if state.get("messages") else ""
    snapshot = state.get("profile_snapshot", {})
    snapshot_str = json.dumps(snapshot, ensure_ascii=False, indent=2) if snapshot else "(暂无学情数据)"

    # 1. 组装 system prompt
    template = load_prompt("interview")
    system_prompt = render_prompt(template, profile_snapshot=snapshot_str)

    # 反思重写:注入上一轮反思意见
    reflection_notes = state.get("reflection_notes", "")
    if reflection_notes:
        system_prompt += (
            "\n\n【反思校验意见】上一轮回答存在以下问题,请修正后重新回答:\n"
            + reflection_notes
        )

    messages = [{"role": "system", "content": system_prompt}]
    history = state.get("messages", [])[-MAX_HISTORY:]
    for m in history:
        messages.append({"role": m.get("role", "user"), "content": m.get("content", "")})

    # 2. 面试结束场景:追加总结指令
    if _is_session_end(user_input):
        messages.append({
            "role": "system",
            "content": (
                "面试已结束,请输出本次模拟面试总结,包含:\n"
                "1. 各轮回答的亮点与改进点\n"
                "2. 综合评分(0-100)\n"
                "3. 薄弱知识点总结\n"
                "4. 推荐复习方向\n"
                "格式用 Markdown,最后追加 [AI 辅助参考,请师生审核]"
            ),
        })

    # 3. 调 LLM
    try:
        output = await llm_invoke(messages, sink=state.get("stream_queue"))
    except Exception as e:
        logger.error("interview LLM 调用失败: %s", e)
        return {
            "final_output": "面试实训服务暂时不可用,请稍后重试。[AI 辅助参考,请师生审核]",
            "profile_updates": {},
        }

    # 4. 面试结束时生成档案更新
    profile_updates: dict = {}
    if _is_session_end(user_input):
        # 从学情快照提取薄弱知识点作为面试记录
        weak_points = [
            m.get("point", "") for m in snapshot.get("mastery", [])
            if m.get("level", 1) < 0.6
        ][:5]
        profile_updates["interview_records"] = [{
            "topic": "模拟面试",
            "question_history": json.dumps(
                [m.get("content", "")[:100] for m in history[-6:]],
                ensure_ascii=False,
            ),
            "overall_score": None,  # MVP:不自动解析评分,由教师端复核
            "weakness_summary": ";".join(weak_points) if weak_points else "暂无",
        }]
        logger.info("面试实训记录已生成(weak=%s)", weak_points)

    # 5. 简历诊断场景:确保不代写(风控兜底)
    if _is_resume_request(user_input):
        if "修改后的简历" in output or "以下是修改后的" in output:
            logger.warning("interview 简历诊断疑似代写,已触发风控兜底")
            output = (
                "根据合规要求,我不能代写简历。以下是优化思路:\n\n"
                + output.split("以下是修改后的")[0]
                + "\n\n[AI 辅助参考,请师生审核]"
            )

    # 6. 强制补标注
    if "[AI 辅助参考" not in output:
        output += "\n\n[AI 辅助参考,请师生审核]"

    return {"final_output": output, "profile_updates": profile_updates}