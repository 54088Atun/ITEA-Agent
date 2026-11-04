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
from app.agent.context import (
    budget, build_history, build_rag_context, select_relevant, trim_text,
)
from app.agent.data_api import fetch_class_stats, fetch_course_evidence, fetch_syllabus
from app.agent.sources import build_sources
from app.agent.tools.doc_generator import doc_generator
from app.agent.tools.sql_query import sql_query
from app.services.sql_analytics import extract_sql, render_table, view_catalog_text

logger = logging.getLogger(__name__)

# 需要组合查询的分析类请求;命中后先生成只读 SQL 再回答
SQL_HINTS = (
    "提交率", "按班级", "近4周", "近 4 周", "近四周", "趋势", "排名", "对比", "环比",
)


async def _run_sql_analysis(user_input: str, course_id, user_id) -> str:
    """自然语言 → 只读 SQL → Markdown 结果表;失败静默降级到固定统计"""
    try:
        raw = await llm_invoke([
            {"role": "system", "content": render_prompt(
                load_prompt("sql_query"), views=view_catalog_text(),
            )},
            {"role": "user", "content": user_input},
        ], temperature=0.0)
        result = sql_query(
            sql=extract_sql(raw), course_id=course_id, user_id=user_id,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("SQL 分析生成失败: %s", exc)
        return ""

    if not result.get("ok") or not result.get("row_count"):
        logger.info("SQL 分析未执行: %s", result.get("error"))
        return ""
    return render_table(result)


async def teacher_node(state: AgentState) -> dict:
    """教师备课节点:运行时直接调用课程/学情数据 API"""
    course_id = state.get("course_id")
    user_id = state["user_id"]
    user_role = state.get("user_role", "teacher")
    user_input = state["messages"][-1]["content"] if state.get("messages") else ""

    # 1. 判断任务类型:备课 / 学情看板 / 导出
    is_stats_request = any(
        kw in user_input for kw in ["学情", "看板", "薄弱", "统计", "分布", "进度"]
    )
    is_export_request = any(
        kw in user_input for kw in ["导出", "下载", "生成教案文件", "报表"]
    )

    # 2. 按需直接调用数据 API(学情统计按需触发)
    stats_context = ""
    if is_stats_request:
        stats = fetch_class_stats(course_id, user_id, user_role, metric="weakness")
        if stats and "error" not in stats:
            stats_context = trim_text(
                json.dumps(stats, ensure_ascii=False, separators=(",", ":")), 900,
            )

    evidence = fetch_course_evidence(user_input, course_id, user_id, user_role)
    raw_context = evidence.get("context", "")
    rag_context, _ = build_rag_context(evidence, user_input)
    syllabus = fetch_syllabus(course_id, user_id, user_role)
    syllabus_context = select_relevant(
        syllabus, user_input, budget("CONTEXT_SYLLABUS_CHARS", 1200),
    )

    # 组合分析请求:先生成只读 SQL 结果表,失败则退回固定统计
    sql_context = ""
    if any(keyword in user_input for keyword in SQL_HINTS):
        from app.services.capabilities import tool_denied_reason

        if not tool_denied_reason(user_role, "sql_query"):
            sql_context = await _run_sql_analysis(user_input, course_id, user_id)

    # 3. 组装 system prompt
    template = load_prompt("teacher")
    prompt_context = rag_context
    if sql_context:
        prompt_context += f"\n\nSQL 查询结果(只读):\n{sql_context}"
    if stats_context:
        prompt_context += f"\n\n班级学情统计:\n{stats_context}"
    system_prompt = render_prompt(
        template,
        syllabus=syllabus_context,
        rag_context=prompt_context or "(暂无知识库检索结果)",
    )

    # 反思重写:注入上一轮反思意见
    reflection_notes = state.get("reflection_notes", "")
    if reflection_notes:
        system_prompt += (
            "\n\n【反思校验意见】上一轮回答存在以下问题,请修正后重新回答:\n"
            + reflection_notes
        )

    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(build_history(state.get("messages", []), limit=6))

    # 4. 调 LLM 生成
    try:
        output = await llm_invoke(messages, sink=state.get("stream_queue"))
    except Exception as e:
        logger.error("teacher LLM 调用失败: %s", e)
        output = "抱歉,备课助手暂时无法响应,请稍后重试。[AI 辅助参考,请教师审核修改]"

    # 5. 导出场景:解析 LLM 输出生成文档
    file_url = ""
    if is_export_request and "教案" in user_input:
        from app.services.capabilities import tool_denied_reason

        denial = tool_denied_reason(user_role, "doc_generator")
        if denial:
            logger.info("跳过文档生成: %s", denial)
        else:
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

    # 7. 标注回答依据(由对话层统一渲染页脚,避免被安全分级误判)
    extra_labels = []
    if stats_context:
        extra_labels.append("班级学情统计")
    if sql_context:
        extra_labels.append("SQL 分析结果")
    sources = build_sources(
        f"{raw_context}\n{syllabus}", extra_labels=extra_labels,
        fragments=evidence.get("fragments"), course_id=course_id,
    )

    return {"final_output": output, "rag_context": raw_context, "sources": sources}