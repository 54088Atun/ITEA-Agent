"""teacher:教师备课减负节点(教师端)

职责:
- 教案框架生成(非成品教案,供教师审核修改)
- 通过工具按需取数:课程素材、班级学情、SQL 分析、文档导出
"""
import logging

from app.agent.state import AgentState
from app.agent.llm import accepts_tools, llm_invoke
from app.agent.prompts import load_prompt, render_prompt
from app.agent.context import (
    budget, build_history, build_rag_context, render_plan, select_relevant,
)
from app.agent.data_api import fetch_syllabus
from app.agent.sources import build_sources
from app.agent.tool_loop import run_tool_loop
from app.agent.nodes.tool_executor import tool_schemas_for_role

logger = logging.getLogger(__name__)

MAX_HISTORY = 6


def _collect_evidence(trace: list[dict]) -> tuple[str, list[dict], list[str], list[str]]:
    """从工具轨迹提取检索上下文、片段、来源标签与文档链接"""
    contexts: list[str] = []
    fragments: list[dict] = []
    extra_labels: list[str] = []
    file_links: list[str] = []

    for item in trace:
        name = item.get("name")
        payload = item.get("result") or {}
        result = payload.get("data") or payload
        if payload.get("error"):
            continue
        if not isinstance(result, dict) or result.get("error"):
            continue

        if name == "course_evidence":
            piece_fragments = result.get("fragments") or []
            if piece_fragments:
                fragments.extend(piece_fragments)
                context, _ = build_rag_context(result)
                if context:
                    contexts.append(context)
            elif result.get("context"):
                contexts.append(str(result["context"]))
        elif name == "stats_analyzer":
            extra_labels.append("班级学情统计")
        elif name == "sql_query":
            extra_labels.append("SQL 分析结果")
        elif name == "doc_generator":
            url = str(result.get("file_url") or "")
            filename = str(result.get("file_name") or "生成文件")
            if url:
                file_links.append(f"文件已生成,请下载审核:[{filename}]({url})")

    # 去重但保持出现顺序,避免重复调用工具把标签叠多次
    labels = list(dict.fromkeys(extra_labels))
    return "\n\n".join(contexts), fragments, labels, file_links


async def teacher_node(state: AgentState) -> dict:
    """教师备课节点:模型按需调用检索/统计/导出工具后作答"""
    course_id = state.get("course_id")
    user_id = state["user_id"]
    user_role = state.get("user_role", "teacher")
    user_input = state["messages"][-1]["content"] if state.get("messages") else ""

    # 1. 大纲是课程级固定上下文,每次备课都需要,保留预取
    syllabus = fetch_syllabus(course_id, user_id, user_role)
    syllabus_context = select_relevant(
        syllabus, user_input, budget("CONTEXT_SYLLABUS_CHARS", 1200),
    )

    template = load_prompt("teacher")
    system_prompt = render_prompt(
        template,
        syllabus=syllabus_context,
        rag_context="(尚未检索:涉及课程素材、班级学情或统计时,先调用相应工具)",
    )

    # 反思重写:注入上一轮反思意见
    reflection_notes = state.get("reflection_notes", "")
    if reflection_notes:
        system_prompt += (
            "\n\n【反思校验意见】上一轮回答存在以下问题,请修正后重新回答:\n"
            + reflection_notes
        )
    # 计划消费:让模型按本轮规划决定取数顺序
    system_prompt += render_plan(state.get("task_plan") or [])

    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(build_history(state.get("messages", []), limit=MAX_HISTORY))

    async def planner(history: list[dict], tools: list[dict]):
        """带工具决策;仅当调用方确实接受 tools 时才传"""
        sink = state.get("stream_queue")
        if accepts_tools(llm_invoke):
            return await llm_invoke(history, tools=tools, sink=sink)
        return await llm_invoke(history, sink=sink)

    # 2. 工具循环按需取数(检索/统计/SQL/导出),不再用关键词判断任务类型
    try:
        output, trace = await run_tool_loop(
            messages,
            state,
            planner=planner,
            tools=tool_schemas_for_role(user_role),
            approval=state.get("tool_approvals"),
            sink=state.get("stream_queue"),
        )
    except Exception as e:  # noqa: BLE001
        logger.error("teacher LLM 调用失败: %s", e)
        output, trace = "抱歉,备课助手暂时无法响应,请稍后重试。[AI 辅助参考,请教师审核修改]", []

    # 3. 强制补标注(反思层兜底)
    if "[AI 辅助参考" not in output:
        output += "\n\n[AI 辅助参考,请教师审核修改]"

    # 4. 文档生成由工具完成,模型可能只提到"已生成",这里补齐可点击链接
    raw_context, fragments, extra_labels, file_links = _collect_evidence(trace)
    for line in file_links:
        if line not in output:
            output += f"\n\n{line}"

    # 5. 标注回答依据(由对话层统一渲染页脚,避免被安全分级误判)
    sources = build_sources(
        f"{raw_context}\n{syllabus}", extra_labels=extra_labels,
        fragments=fragments, course_id=course_id,
    )

    return {
        "final_output": output,
        "rag_context": raw_context,
        "sources": sources,
        "tool_trace": [
            {
                "name": item.get("name"),
                "arguments": item.get("arguments") or {},
                "result": item.get("result") or {},
            }
            for item in trace
        ],
    }
