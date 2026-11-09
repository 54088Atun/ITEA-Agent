"""interview:简历诊断与模拟面试实训节点(学生端三级分支)

职责:
- 简历诊断:只给优化思路,绝不代写简历
- 模拟面试:基于薄弱知识点定向出题,多轮对话追问
- 面试结束后输出评分 + 薄弱点总结 → 写入 profile_updates
"""
import json
import logging
import re

from app.agent.state import AgentState
from app.agent.llm import llm_invoke
from app.agent.prompts import load_prompt, render_prompt
from app.agent.context import build_history, build_rag_context, compress_profile
from app.agent.data_api import fetch_course_evidence, fetch_profile
from app.agent.sources import build_sources

logger = logging.getLogger(__name__)

MAX_HISTORY = 12


def _is_resume_request(user_input: str) -> bool:
    """判断是否简历诊断请求"""
    return any(kw in user_input for kw in ["简历", "求职", "实习经历", "项目经历描述"])


def _is_session_end(user_input: str) -> bool:
    """判断是否面试结束请求"""
    return any(kw in user_input for kw in ["结束面试", "面试结束", "总结一下", "打分", "结束吧"])


def _output_score(output: str, label: str) -> int | None:
    """只提取模型明确给出的 0-100 分数,缺失或越界均留空"""
    match = re.search(
        rf"{re.escape(label)}(?:评分)?\s*[:：]?\s*(?:为\s*)?(\d{{1,3}})(?!\d)",
        output,
    )
    if not match:
        return None
    score = int(match.group(1))
    return score if 0 <= score <= 100 else None


async def interview_node(state: AgentState) -> dict:
    """面试实训节点:运行时直接读取学情与课程资料"""
    user_input = state["messages"][-1]["content"] if state.get("messages") else ""
    course_id = state.get("course_id")

    # 1. 直接调用数据 API
    user_role = state.get("user_role", "student")
    profile = fetch_profile(state["user_id"], course_id, user_role)
    snapshot_str = compress_profile(profile)
    evidence = (
        fetch_course_evidence(user_input, course_id, state["user_id"], user_role)
        if state.get("retrieval_available", True) else {}
    )
    raw_context = evidence.get("context", "")
    rag_context, _ = build_rag_context(evidence, user_input)
    sources = build_sources(
        raw_context, has_profile=bool(profile),
        fragments=evidence.get("fragments"), course_id=course_id,
    )

    template = load_prompt("interview")
    system_prompt = render_prompt(template, profile_snapshot=snapshot_str)
    if rag_context:
        system_prompt += f"\n\n【课程资料参考】\n{rag_context}"

    # 反思重写:注入上一轮反思意见
    reflection_notes = state.get("reflection_notes", "")
    if reflection_notes:
        system_prompt += (
            "\n\n【反思校验意见】上一轮回答存在以下问题,请修正后重新回答:\n"
            + reflection_notes
        )

    messages = [{"role": "system", "content": system_prompt}]
    history = build_history(state.get("messages", []), limit=MAX_HISTORY)
    messages.extend(history)

    # 2. 面试结束场景:追加总结指令
    if _is_session_end(user_input):
        messages.append({
            "role": "system",
            "content": (
                "面试已结束,请输出本次模拟面试总结,包含:\n"
                "1. 各轮回答的亮点与改进点\n"
                "2. 专业知识、逻辑表达、岗位匹配、沟通应答四个维度评分(各0-100)\n"
                "3. 综合评分(0-100)\n"
                "4. 薄弱知识点总结与推荐复习方向\n"
                "评分按以下独立行输出:专业知识：X分、逻辑表达：X分、"
                "岗位匹配：X分、沟通应答：X分、综合评分：X分。\n"
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
            "rag_context": raw_context,
            "sources": sources,
        }

    # 4. 面试结束时生成档案更新
    profile_updates: dict = {}
    if _is_session_end(user_input):
        # 从学情快照提取薄弱知识点作为面试记录
        weak_points = [
            m.get("point", "") for m in profile.get("mastery", [])
            if m.get("level", 1) < 0.6
        ][:5]
        dimensions = {
            label: _output_score(output, label)
            for label in ("专业知识", "逻辑表达", "岗位匹配", "沟通应答")
        }
        profile_updates["interview_records"] = [{
            "topic": "模拟面试",
            "question_history": json.dumps(
                [m.get("content", "")[:100] for m in history[-6:]],
                ensure_ascii=False,
            ),
            "overall_score": _output_score(output, "综合评分"),
            "score_dimensions": json.dumps(dimensions, ensure_ascii=False),
            "feedback": output,
            "weakness_summary": ";".join(weak_points) if weak_points else "暂无",
            "assignment_id": state.get("interview_assignment_id"),
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

    # 7. 标注回答依据(由对话层统一渲染页脚,避免被安全分级误判)
    return {
        "final_output": output, "profile_updates": profile_updates,
        "rag_context": raw_context, "sources": sources,
    }