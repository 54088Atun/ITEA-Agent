"""tutor:课程专属智能助教节点(学生端)

职责:
- 苏格拉底引导式答疑,不直接给答案
- 按需调用 course_evidence / profile_query 取数(P0-2:不再无条件预取)
- 支持流式输出(SSE)
- 代码排错仅基于用户粘贴的代码与报错做静态分析,不执行代码
"""
import logging

from app.agent.state import AgentState
from app.agent.llm import accepts_tools, llm_invoke
from app.agent.prompts import load_prompt, render_prompt
from app.agent.context import build_history, build_rag_context, render_plan
from app.agent.data_api import fetch_memories
from app.agent.sources import build_sources
from app.agent.tool_loop import run_tool_loop
from app.agent.time_context import time_prompt
from app.agent.nodes.tool_executor import tool_schemas_for_role

logger = logging.getLogger(__name__)

MAX_HISTORY = 10

# 寒暄与致谢不触发检索,避免打招呼也带一堆无关上下文
SMALL_TALK_PATTERN = (
    "你好", "您好", "hi", "hello", "嗨", "在吗", "谢谢", "多谢", "感谢",
    "再见", "拜拜", "好的", "ok", "嗯", "早上好", "晚上好", "晚安",
)
SMALL_TALK_MAX_LEN = 12
RETRIEVAL_TOOLS = ("course_evidence", "rag_search")


def _build_messages(state: AgentState, system_prompt: str) -> list[dict]:
    """组装对话消息:system + 预算内的最近历史"""
    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(build_history(state.get("messages", []), limit=MAX_HISTORY))
    return messages


def _detect_code_submission(user_input: str) -> tuple[str, str] | None:
    """检测用户是否提交了代码块,返回 (language, code) 或 None

    仅用于提示模型按代码排错规则作答,不触发任何执行。
    """
    import re
    match = re.search(r"```(\w*)\n(.*?)```", user_input, re.DOTALL)
    if match and len(match.group(2).strip()) > 3:
        lang = match.group(1).lower() or "python"
        lang = {"py": "python", "js": "javascript", "ts": "typescript"}.get(lang, lang)
        return lang, match.group(2)
    return None


def _is_small_talk(user_input: str) -> bool:
    """判断是否为寒暄类短句:这类输入不应触发课程检索"""
    text = (user_input or "").strip().lower()
    if not text:
        return True
    if len(text) > SMALL_TALK_MAX_LEN:
        return False
    return any(word in text for word in SMALL_TALK_PATTERN)


def _render_preferences(memories: dict) -> str:
    """把语义偏好渲染成常驻提示词片段

    模型未必每轮都调用 profile_query,而"以后都用中文解释"这类偏好必须
    每轮生效,所以这里在 system prompt 中直接注入。
    """
    lines = []
    for memo in (memories or {}).get("semantic_memories") or []:
        if not isinstance(memo, dict):
            continue
        text = str(memo.get("summary") or memo.get("content") or "").strip()
        if text:
            lines.append(f"- {text[:120]}")
    if not lines:
        return ""
    return (
        "\n\n【长期偏好】用户此前明确要求长期遵守以下偏好,请直接沿用:\n"
        + "\n".join(lines[:3])
    )


def _collect_evidence(trace: list[dict]) -> tuple[str, list[dict], bool]:
    """从工具轨迹提取检索上下文、片段与学情标记,供来源页脚使用"""
    contexts: list[str] = []
    fragments: list[dict] = []
    has_profile = False

    for item in trace:
        name = item.get("name")
        payload = item.get("result") or {}
        # 工具返回已统一为 {ok, data, ...};兼容旧扁平结构
        result = payload.get("data") or payload
        if name == "course_evidence" and not payload.get("error"):
            piece_fragments = result.get("fragments") or []
            if piece_fragments:
                fragments.extend(piece_fragments)
                context, _ = build_rag_context(result)
                if context:
                    contexts.append(context)
            elif result.get("context"):
                contexts.append(str(result["context"]))
        elif name == "profile_query":
            summary = str(result.get("summary") or "")
            if summary and summary != "(暂无学情数据)":
                has_profile = True

    return "\n\n".join(contexts), fragments, has_profile


async def tutor_node(state: AgentState) -> dict:
    """课程助教节点:模型按需调用检索与学情工具后作答"""
    user_input = state["messages"][-1]["content"] if state.get("messages") else ""
    course_id = state.get("course_id")
    user_role = state.get("user_role", "student")
    # 课程没有资料/索引时,不再强制检索,也不向模型暴露检索工具
    retrieval_ready = bool(state.get("retrieval_available", True))

    # 1. 工具化取数:检索与学情改为模型按需调用,不再每轮预取
    template = load_prompt("tutor")
    system_prompt = render_prompt(
        template,
        rag_context="(尚未检索:涉及课程内容时先调用 course_evidence 工具)",
        profile_snapshot="(尚未读取:需要个性化参考时先调用 profile_query 工具)",
    )
    # 注入服务端当前时间,支持"明天/本周"类提醒与复习排程
    system_prompt += time_prompt()

    # 反思重写:注入上一轮反思意见
    reflection_notes = state.get("reflection_notes", "")
    if reflection_notes:
        system_prompt += (
            "\n\n【反思校验意见】上一轮回答存在以下问题,请修正后重新回答:\n"
            + reflection_notes
        )

    # 长期偏好常驻:不依赖模型是否调用 profile_query
    system_prompt += _render_preferences(
        fetch_memories(state.get("user_id") or 0, course_id, user_role),
    )
    # 计划消费:把本轮规划注入提示词,避免"计划说检索、实际没检索"
    plan_items = state.get("task_plan") or []
    if not retrieval_ready:
        plan_items = [
            item for item in plan_items
            if (item or {}).get("tool") not in RETRIEVAL_TOOLS
        ]
    system_prompt += render_plan(plan_items)
    if not retrieval_ready:
        system_prompt += (
            "\n\n【检索能力】本课程尚未配置可检索资料，请基于通用知识回答；"
            "不要声称引用了课程讲义、页码或课程原始资料。"
        )

    messages = _build_messages(state, system_prompt)

    # 2. 代码排错:系统不执行用户代码,只提示模型基于粘贴内容做静态分析
    code_match = _detect_code_submission(user_input)
    if code_match:
        lang, _code = code_match
        messages.append({
            "role": "system",
            "content": (
                f"学生提交了 {lang} 代码片段。系统不执行用户代码,也不会返回真实运行时错误;"
                "请基于代码与用户描述做静态分析,指出问题方向并给出排查步骤,"
                "必要时请用户补充完整报错信息。"
            ),
        })

    # 3. 课程事实题保底检索一次:防止模型跳过检索直接编造课程内容
    # 未选课程时不强制检索:course_evidence 的 course_id 必填,强调用必然被网关拒绝
    forced_call = None
    if course_id and retrieval_ready and not _is_small_talk(user_input):
        forced_call = {
            "id": "forced_course_evidence",
            "name": "course_evidence",
            "arguments": {"query": user_input, "course_id": course_id, "top_k": 5},
        }

    async def planner(history: list[dict], tools: list[dict]):
        """带工具决策;仅当调用方确实接受 tools 时才传,避免用异常探测签名"""
        sink = state.get("stream_queue")
        if accepts_tools(llm_invoke):
            return await llm_invoke(history, tools=tools, sink=sink)
        return await llm_invoke(history, sink=sink)

    tools = tool_schemas_for_role(user_role)
    if not retrieval_ready:
        tools = [
            schema for schema in tools
            if schema.get("name") not in RETRIEVAL_TOOLS
        ]

    try:
        output, trace = await run_tool_loop(
            messages,
            state,
            planner=planner,
            tools=tools,
            forced_call=forced_call,
            approval=state.get("tool_approvals"),
            sink=state.get("stream_queue"),
        )
    except Exception as e:  # noqa: BLE001
        logger.error("tutor LLM 调用失败: %s", e)
        output, trace = "抱歉,助教暂时无法响应,请稍后重试。", []

    # 4. 强制补标注(反思层兜底)
    if "[AI 辅助参考" not in output:
        output += "\n\n[AI 辅助参考,请师生审核]"

    # 5. 标注回答依据(由对话层统一渲染页脚,避免被安全分级误判)
    raw_context, fragments, has_profile = _collect_evidence(trace)
    sources = build_sources(
        raw_context, has_profile=has_profile,
        fragments=fragments, course_id=course_id,
    )

    return {
        "final_output": output,
        "rag_context": raw_context,
        "sources": sources,
        # 工具循环轨迹只用于观测(trace / SSE),不参与后续节点执行
        "tool_trace": [
            {
                "name": item.get("name"),
                "arguments": item.get("arguments") or {},
                "result": item.get("result") or {},
            }
            for item in trace
        ],
    }
