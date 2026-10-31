"""teacher:教师备课减负节点(教师端)

职责:
- 教案框架生成(非成品教案,供教师审核修改)
- 班级学情汇总(调 stats_analyzer 聚合统计)
- 预习任务设计 + 分层习题生成
- 文档导出(doc_generator)
"""
import json
import logging

from app.agent.state import AgentState
from app.agent.llm import llm_invoke
from app.agent.prompts import load_prompt, render_prompt
from app.agent.tools.stats_analyzer import stats_analyzer
from app.agent.tools.doc_generator import doc_generator

logger = logging.getLogger(__name__)


def _load_syllabus(state: AgentState) -> str:
    """从工具结果或数据库获取课程大纲"""
    tool_results = state.get("tool_results") or {}
    if "rag_search" in tool_results:
        context = tool_results["rag_search"].get("context", "")
        if context and context != "(未检索到相关内容)":
            return context
    return "(暂无课程大纲,请教师上传教学大纲后使用)"


async def teacher_node(state: AgentState) -> dict:
    """教师备课节点"""
    course_id = state.get("course_id") or 1
    user_input = state["messages"][-1]["content"] if state.get("messages") else ""

    # 1. 判断任务类型:备课 / 学情看板 / 导出
    is_stats_request = any(
        kw in user_input for kw in ["学情", "看板", "薄弱", "统计", "分布", "进度"]
    )
    is_export_request = any(
        kw in user_input for kw in ["导出", "下载", "生成教案文件", "报表"]
    )

    # 2. 学情统计场景:先调 stats_analyzer
    stats_context = ""
    if is_stats_request:
        stats = stats_analyzer(course_id=course_id, metric="weakness")
        if "error" not in stats:
            stats_context = json.dumps(stats, ensure_ascii=False, indent=2)

    # 3. 组装 system prompt
    template = load_prompt("teacher")
    rag_context = state.get("rag_context", "")
    if stats_context:
        rag_context += f"\n\n班级学情统计:\n{stats_context}"
    system_prompt = render_prompt(
        template,
        syllabus=_load_syllabus(state),
        rag_context=rag_context or "(暂无知识库检索结果)",
    )

    # 反思重写:注入上一轮反思意见
    reflection_notes = state.get("reflection_notes", "")
    if reflection_notes:
        system_prompt += (
            "\n\n【反思校验意见】上一轮回答存在以下问题,请修正后重新回答:\n"
            + reflection_notes
        )

    messages = [{"role": "system", "content": system_prompt}]
    history = state.get("messages", [])[-6:]
    for m in history:
        messages.append({"role": m.get("role", "user"), "content": m.get("content", "")})

    # 4. 调 LLM 生成
    try:
        output = await llm_invoke(messages, sink=state.get("stream_queue"))
    except Exception as e:
        logger.error("teacher LLM 调用失败: %s", e)
        output = "抱歉,备课助手暂时无法响应,请稍后重试。[AI 辅助参考,请教师审核修改]"

    # 5. 导出场景:解析 LLM 输出生成文档
    file_url = ""
    if is_export_request and "教案" in user_input:
        doc_result = doc_generator(
            doc_type="lesson_plan",
            data={"course_name": f"课程{course_id}", "sections": {"AI 生成框架": output[:2000]}},
        )
        file_url = doc_result.get("file_url", "")
        if file_url:
            output += f"\n\n教案文件已生成,请下载审核:[{doc_result['file_name']}]({file_url})"

    # 6. 强制补标注
    if "[AI 辅助参考" not in output:
        output += "\n\n[AI 辅助参考,请教师审核修改]"

    return {"final_output": output}