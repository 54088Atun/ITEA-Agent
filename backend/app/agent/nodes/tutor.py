"""tutor:课程专属智能助教节点(学生端)

职责:
- 苏格拉底引导式答疑,不直接给答案
- 按需调用 course_evidence / profile_query 取数(P0-2:不再无条件预取)
- 支持流式输出(SSE)
- 代码排错场景自动调 code_executor 沙箱
"""
import logging

from app.agent.state import AgentState
from app.agent.llm import llm_invoke
from app.agent.prompts import load_prompt, render_prompt
from app.agent.context import build_history, build_rag_context
from app.agent.sources import build_sources
from app.agent.tools.code_executor import code_executor
from app.agent.tool_loop import run_tool_loop
from app.agent.nodes.tool_executor import tool_schemas_for_role

logger = logging.getLogger(__name__)

CODE_BLOCK_PATTERN = r"```(\w*)\n(.*?)```"
MAX_HISTORY = 10

# 寒暄与致谢不触发检索,避免打招呼也带一堆无关上下文
SMALL_TALK_PATTERN = (
    "你好", "您好", "hi", "hello", "嗨", "在吗", "谢谢", "多谢", "感谢",
    "再见", "拜拜", "好的", "ok", "嗯", "早上好", "晚上好", "晚安",
)
SMALL_TALK_MAX_LEN = 12


def _build_messages(state: AgentState, system_prompt: str) -> list[dict]:
    """组装对话消息:system + 预算内的最近历史"""
    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(build_history(state.get("messages", []), limit=MAX_HISTORY))
    return messages


def _detect_code_submission(user_input: str) -> tuple[str, str] | None:
    """检测用户是否提交了代码块,返回 (language, code) 或 None"""
    import re
    match = re.search(CODE_BLOCK_PATTERN, user_input, re.DOTALL)
    if match and len(match.group(2).strip()) > 3:
        lang = match.group(1).lower() or "python"
        lang = {"py": "python", "js": "javascript"}.get(lang, lang)
        if lang in ("python", "java", "cpp", "c++"):
            return ("cpp" if lang in ("c++",) else lang), match.group(2)
    return None


def _is_small_talk(user_input: str) -> bool:
    """判断是否为寒暄类短句:这类输入不应触发课程检索"""
    text = (user_input or "").strip().lower()
    if not text:
        return True
    if len(text) > SMALL_TALK_MAX_LEN:
        return False
    return any(word in text for word in SMALL_TALK_PATTERN)


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

    # 1. 工具化取数:检索与学情改为模型按需调用,不再每轮预取
    template = load_prompt("tutor")
    system_prompt = render_prompt(
        template,
        rag_context="(尚未检索:涉及课程内容时先调用 course_evidence 工具)",
        profile_snapshot="(尚未读取:需要个性化参考时先调用 profile_query 工具)",
    )

    # 反思重写:注入上一轮反思意见
    reflection_notes = state.get("reflection_notes", "")
    if reflection_notes:
        system_prompt += (
            "\n\n【反思校验意见】上一轮回答存在以下问题,请修正后重新回答:\n"
            + reflection_notes
        )

    messages = _build_messages(state, system_prompt)

    # 2. 代码排错场景:自动执行沙箱,结果注入对话
    code_match = _detect_code_submission(user_input)
    if code_match:
        lang, code = code_match
        from app.services.capabilities import tool_denied_reason

        denial = tool_denied_reason(state.get("user_role", "student"), "code_executor")
        if denial:
            logger.info("跳过沙箱执行: %s", denial)
        else:
            exec_result = code_executor(code=code, language=lang)
            if exec_result.get("exit_code", 0) != 0 or exec_result.get("stderr"):
                messages.append({
                    "role": "system",
                    "content": (
                        f"学生提交了 {lang} 代码,沙箱执行结果:\n"
                        f"stdout: {exec_result.get('stdout', '')}\n"
                        f"stderr: {exec_result.get('stderr', '')}\n"
                        f"exit_code: {exec_result.get('exit_code')}\n"
                        "请基于报错信息做引导式排错,不要给出修复后的完整代码。"
                    ),
                })
                logger.info(
                    "tutor 检测到代码提交,沙箱结果已注入(exit_code=%s)",
                    exec_result.get("exit_code"),
                )

    # 3. 课程事实题保底检索一次:防止模型跳过检索直接编造课程内容
    forced_call = None
    if not _is_small_talk(user_input):
        forced_call = {
            "id": "forced_course_evidence",
            "name": "course_evidence",
            "arguments": {"query": user_input, "course_id": course_id, "top_k": 5},
        }

    async def planner(history: list[dict], tools: list[dict]):
        """带工具决策;兼容未支持 tools 参数的自定义实现与测试替身"""
        sink = state.get("stream_queue")
        try:
            return await llm_invoke(history, tools=tools, sink=sink)
        except TypeError:
            return await llm_invoke(history, sink=sink)

    try:
        output, trace = await run_tool_loop(
            messages,
            state,
            planner=planner,
            tools=tool_schemas_for_role(user_role),
            forced_call=forced_call,
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
