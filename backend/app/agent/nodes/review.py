"""review:错题复盘自适应学习节点(学生端二级分支)

职责:
- 识别错题知识点 + 错误类型
- 基于遗忘曲线规划复习节点(1→2→4→7→15→30 天)
- 生成同考点变式练习题
- 输出掌握度更新 → 写入 profile_updates 供 memory_write_node 持久化
"""
import logging
from datetime import datetime, timedelta

from app.agent.state import AgentState
from app.agent.llm import llm_invoke
from app.agent.prompts import load_prompt, render_prompt
from app.agent.context import build_rag_context, compress_profile
from app.agent.data_api import fetch_course_evidence, fetch_profile
from app.agent.nodes.router import _parse_json
from app.agent.sources import build_sources

logger = logging.getLogger(__name__)

FORGETTING_INTERVALS = [1, 2, 4, 7, 15, 30]


async def review_node(state: AgentState) -> dict:
    """错题复盘节点:运行时直接读取学情与课程资料"""
    user_input = state["messages"][-1]["content"] if state.get("messages") else ""
    course_id = state.get("course_id")

    # 1. 直接调用数据 API
    user_role = state.get("user_role", "student")
    profile = fetch_profile(state["user_id"], course_id, user_role)
    snapshot_str = compress_profile(profile)
    evidence = fetch_course_evidence(user_input, course_id, state["user_id"], user_role)
    raw_context = evidence.get("context", "")
    rag_context, _ = build_rag_context(evidence, user_input)
    sources = build_sources(
        raw_context, has_profile=bool(profile),
        fragments=evidence.get("fragments"), course_id=course_id,
    )

    template = load_prompt("review")
    system_prompt = render_prompt(
        template,
        submission=user_input,
        profile_snapshot=snapshot_str,
    )
    if rag_context:
        system_prompt += f"\n\n【课程资料参考】\n{rag_context}"

    # 反思重写:注入上一轮反思意见
    reflection_notes = state.get("reflection_notes", "")
    if reflection_notes:
        system_prompt += (
            "\n\n【反思校验意见】上一轮回答存在以下问题,请修正后重新回答:\n"
            + reflection_notes
        )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": "请对以上提交内容进行错题复盘,严格按 JSON 格式输出。"},
    ]

    # 2. 调 LLM
    try:
        raw_output = await llm_invoke(messages, temperature=0.1)
    except Exception as e:
        logger.error("review LLM 调用失败: %s", e)
        return {
            "final_output": "复盘服务暂时不可用,请稍后重试。[AI 辅助参考,请师生审核]",
            "profile_updates": {},
            "rag_context": raw_context,
            "sources": sources,
        }

    # 3. 解析结构化 JSON
    result = _parse_json(raw_output)
    if not result or "error_analysis" not in result:
        # JSON 解析失败,直接输出原文(兜底)
        logger.warning("review JSON 解析失败,输出原文")
        output = raw_output
        if "[AI 辅助参考" not in output:
            output += "\n\n[AI 辅助参考,请师生审核]"
        return {
            "final_output": output,
            "profile_updates": {}, "rag_context": raw_context, "sources": sources,
        }

    # 4. 组装 profile_updates(供 memory_write_node 持久化)
    error_analysis = result.get("error_analysis", {})
    mastery_update = result.get("mastery_update", {})
    review_plan = result.get("review_plan", {})
    variant = result.get("variant_question", {})

    profile_updates: dict = {}

    # 4.1 错题录入
    if error_analysis:
        profile_updates["wrong_questions"] = [{
            "knowledge_point": error_analysis.get("kp_name", ""),
            "question_summary": user_input[:200],
            "error_type": error_analysis.get("error_type", "概念不清"),
            "ai_analysis": error_analysis.get("explanation", ""),
        }]

    # 4.2 掌握度更新
    if mastery_update:
        delta = mastery_update.get("delta", -20)
        current = 0.5  # MVP:默认当前掌握度,生产应从快照读取
        new_level = max(0.0, min(1.0, current + delta / 100))
        profile_updates["mastery_updates"] = [{
            "knowledge_point": error_analysis.get("kp_name", ""),
            "mastery_level": round(new_level, 2),
        }]

    # 4.3 复习计划(遗忘曲线)
    if review_plan:
        profile_updates["review_plans"] = [{
            "wrong_question_id": None,  # 由 memory_write_node 关联
        }]

    # 5. 组装自然语言复盘输出
    output_parts = ["## 错题复盘报告\n"]
    if error_analysis:
        output_parts.append(f"**知识点**:{error_analysis.get('kp_name', '未知')}")
        output_parts.append(f"**错误类型**:{error_analysis.get('error_type', '未知')}")
        output_parts.append(f"**原因分析**:{error_analysis.get('explanation', '')}\n")
    if variant:
        output_parts.append("## 变式练习")
        output_parts.append(f"{variant.get('question', '')}")
        output_parts.append(f"*提示*:{variant.get('hint', '')}\n")
    if review_plan:
        next_date = review_plan.get("next_review_at", "")
        output_parts.append(f"## 复习计划\n下次复习时间:{next_date}")
        output_parts.append("复习节点:1天 → 2天 → 4天 → 7天 → 15天 → 30天\n")
    output_parts.append("[AI 辅助参考,请师生审核]")

    output = "\n".join(output_parts)
    logger.info("错题复盘完成(kp=%s, updates=%s)",
                error_analysis.get("kp_name"), list(profile_updates.keys()))

    return {
        "final_output": output, "profile_updates": profile_updates,
        "rag_context": raw_context, "sources": sources,
    }