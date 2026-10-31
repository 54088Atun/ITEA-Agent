"""tutor:课程专属智能助教节点(学生端)

职责:
- 苏格拉底引导式答疑,不直接给答案
- 注入 RAG 检索上下文 + 学情快照个性化回答
- 支持流式输出(SSE)
- 代码排错场景自动调 code_executor 沙箱
"""
import json
import logging

from app.agent.state import AgentState
from app.agent.llm import llm_invoke, llm_stream
from app.agent.prompts import load_prompt, render_prompt
from app.agent.tools.code_executor import code_executor

logger = logging.getLogger(__name__)

CODE_BLOCK_PATTERN = r"```(\w*)\n(.*?)```"
MAX_HISTORY = 10


def _build_messages(state: AgentState, system_prompt: str) -> list[dict]:
    """组装对话消息:system + 最近 N 轮历史"""
    messages = [{"role": "system", "content": system_prompt}]
    history = state.get("messages", [])[-MAX_HISTORY:]
    for m in history:
        messages.append({"role": m.get("role", "user"), "content": m.get("content", "")})
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


async def tutor_node(state: AgentState) -> dict:
    """课程助教节点"""
    # 1. 组装 system prompt(注入 RAG 上下文 + 学情快照)
    template = load_prompt("tutor")
    rag_context = state.get("rag_context", "(暂无知识库检索结果)")
    snapshot = state.get("profile_snapshot", {})
    snapshot_str = json.dumps(snapshot, ensure_ascii=False, indent=2) if snapshot else "(暂无学情数据)"
    system_prompt = render_prompt(
        template,
        rag_context=rag_context,
        profile_snapshot=snapshot_str,
    )

    # 反思重写:注入上一轮反思意见
    reflection_notes = state.get("reflection_notes", "")
    if reflection_notes:
        system_prompt += (
            "\n\n【反思校验意见】上一轮回答存在以下问题,请修正后重新回答:\n"
            + reflection_notes
        )

    messages = _build_messages(state, system_prompt)
    user_input = state["messages"][-1]["content"] if state.get("messages") else ""

    # 2. 代码排错场景:自动执行沙箱,结果注入对话
    code_match = _detect_code_submission(user_input)
    if code_match:
        lang, code = code_match
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
            logger.info("tutor 检测到代码提交,沙箱结果已注入(exit_code=%s)", exec_result.get("exit_code"))

    # 3. 调 LLM 生成回答(有流式通道则边生成边推送)
    try:
        output = await llm_invoke(messages, sink=state.get("stream_queue"))
    except Exception as e:
        logger.error("tutor LLM 调用失败: %s", e)
        output = "抱歉,助教暂时无法响应,请稍后重试。[AI 辅助参考,请师生审核]"

    # 4. 强制补标注(反思层兜底)
    if "[AI 辅助参考" not in output:
        output += "\n\n[AI 辅助参考,请师生审核]"

    return {"final_output": output}