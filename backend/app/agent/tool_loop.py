"""工具调用循环(P0-1):think → tool_call → observe → answer

模型负责决定是否调用工具,代码负责边界:
- 每轮把工具结果以 tool 消息回灌,模型据此决定继续调用还是直接作答
- 单工具超时、总体步数上限,超限后禁用工具强制收尾,避免无限循环
- 工具执行统一复用 tool_executor 的权限校验、参数校验与范围收口
"""
import asyncio
import json
import logging
import time

from app.agent.llm import ToolPlan, llm_invoke
from app.services.prompt_guard import UNTRUSTED_NOTICE, sanitize_payload

logger = logging.getLogger(__name__)

# 单轮最多 8 步(与清单 P0-1 一致)
MAX_TOOL_STEPS = 8
# 单个工具执行上限:超时按「数据暂不可用」降级,不阻断整轮回答
TOOL_TIMEOUT_SECONDS = 20


def _split_plan(plan) -> tuple[str, list[dict]]:
    """统一模型决策的两种形态:纯文本 / ToolPlan"""
    if isinstance(plan, ToolPlan):
        return plan.content or "", list(plan.tool_calls or [])
    if isinstance(plan, dict):
        return str(plan.get("content") or ""), list(plan.get("tool_calls") or [])
    return ("" if plan is None else str(plan)), []


async def _execute(call: dict, state, approval=None, quota=None) -> dict:
    """执行单个工具,统一超时与异常降级

    权限、确认、参数与配额全部复用 tool_executor 的共享执行边界,
    本函数只负责超时与降级。

    A-13 说明:`asyncio.wait_for` 只能取消 `await`,无法中断 `to_thread`
    里的同步查询。超时后不再立即重试——重试会让同一个慢查询再占一个线程,
    把悬挂线程从 8 个放大到 16 个。这里只等待一次并显式记录"线程仍可能
    在后台完成",把容量风险交给调用方观测。
    """
    # 延迟导入:tool_executor 经由 nodes 包间接依赖 tutor,顶层导入会形成循环
    from app.agent.nodes.tool_executor import _execute_single
    from app.agent.tools.gateway import (
        get_tool_spec, tool_result, tool_timeout_seconds,
    )

    name = str(call.get("name") or "")
    payload = {"name": name, "arguments": dict(call.get("arguments") or {})}
    # 工具级超时与全局上限取最小值:既尊重 ToolSpec,也保留全局兜底
    timeout = tool_timeout_seconds(get_tool_spec(name), TOOL_TIMEOUT_SECONDS)

    started = time.perf_counter()
    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(
                _execute_single, payload, state,
                approval=approval, quota=quota,
            ),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        logger.warning(
            "工具 %s 执行超时(%ss);后台线程仍可能继续直到查询结束",
            name, timeout,
        )
        return tool_result(
            False, None,
            error=f"工具 {name} 执行超时({timeout}s),数据暂不可用",
            latency_ms=(time.perf_counter() - started) * 1000,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("工具 %s 执行异常: %s", name, exc)
        return tool_result(
            False, None,
            error=f"工具 {name} 执行失败: {exc}",
            latency_ms=(time.perf_counter() - started) * 1000,
        )
    return result if isinstance(result, dict) else tool_result(True, result)


# 高危工具的确认卡片文案
TOOL_LABELS = {
    "reminder_scheduler": "创建复习提醒",
    "project.run_tests": "运行预置测试集",
}


async def _emit_confirm(sink, state, item: dict, confirm_sent: set) -> None:
    """高危工具被拒时下发确认卡片:同一工具每轮只发一次,避免重复弹卡"""
    name = item["name"]
    if sink is None or name in confirm_sent:
        return
    confirm_sent.add(name)
    from app.services.tool_approval import issue_tool_token

    token = issue_tool_token(
        state.get("session_id"), state.get("user_id"), name, item["arguments"],
    )
    await sink.put(("confirm_required", {
        "kind": "tool",
        "tool": name,
        "label": TOOL_LABELS.get(name, name),
        "arguments": item["arguments"],
        "confirmation_token": token,
        "message": "该操作会写入数据,确认后才会执行。",
        "risk_level": "medium",
    }))


async def _run_calls(calls: list[dict], history: list[dict], state,
                     trace: list[dict], approval=None, quota=None,
                     sink=None, confirm_sent=None) -> None:
    """批量执行一轮工具调用,按 assistant(tool_calls) + tool 消息回灌"""
    prepared: list[dict] = []
    for index, call in enumerate(calls):
        args = dict(call.get("arguments") or {})
        prepared.append({
            "id": call.get("id") or f"call_{len(trace) + index}",
            "name": str(call.get("name") or ""),
            "arguments": args,
        })

    history.append({
        "role": "assistant",
        "content": "",
        "tool_calls": prepared,
    })

    for item in prepared:
        result = await _execute(item, state, approval=approval, quota=quota)
        if isinstance(result, dict) and result.get("requires_confirmation"):
            await _emit_confirm(sink, state, item, confirm_sent if confirm_sent is not None else set())
        trace.append({
            "name": item["name"],
            "arguments": item["arguments"],
            "result": result,
        })
        # 回灌给模型前先消毒:工具输出属于不可信输入,可能夹带注入指令
        content = json.dumps(
            sanitize_payload(result), ensure_ascii=False, default=str,
        )
        if result.get("untrusted"):
            content = f"{UNTRUSTED_NOTICE}\n{content}"
        history.append({
            "role": "tool",
            "tool_call_id": item["id"],
            "content": content,
        })


async def run_tool_loop(
    messages: list[dict],
    state,
    *,
    planner,
    tools: list[dict],
    forced_call: dict | None = None,
    approval=None,
    max_steps: int = MAX_TOOL_STEPS,
    sink=None,
) -> tuple[str, list[dict]]:
    """执行工具循环,返回 (最终回答, 调用轨迹)

    planner(messages, tools) -> str | ToolPlan:模型决策
    forced_call: 进入模型决策前强制执行的工具(如课程事实题保底检索)
    approval: 服务端可信审批上下文,只有它能放行需确认的高危工具;
              模型给出的 calls/arguments 无法伪造确认。
    """
    from app.agent.tools.gateway import TurnQuota, coerce_tool_approval

    history = [dict(message) for message in messages]
    trace: list[dict] = []
    approved = coerce_tool_approval(approval)
    # 整个工具循环共用一个配额,跨轮次累计,避免分轮绕过单轮上限
    quota = TurnQuota()
    # 同一工具只弹一次确认卡片,避免模型重试导致重复下发
    confirm_sent: set = set()

    if forced_call:
        await _run_calls(
            [forced_call], history, state, trace,
            approval=approved, quota=quota,
            sink=sink, confirm_sent=confirm_sent,
        )

    for _ in range(max_steps):
        plan = await planner(history, tools)
        content, calls = _split_plan(plan)
        if not calls:
            return content, trace
        await _run_calls(
            calls, history, state, trace, approval=approved, quota=quota,
            sink=sink, confirm_sent=confirm_sent,
        )

    logger.warning(
        "工具循环达到步数上限 %s,强制收尾(session=%s)",
        max_steps, state.get("session_id"),
    )
    try:
        text = await llm_invoke(history, sink=sink)
    except Exception as exc:  # noqa: BLE001
        logger.error("工具循环收尾失败: %s", exc)
        text = ""
    if isinstance(text, ToolPlan):
        text = text.content
    if not text:
        text = "本轮工具调用过多,已停止。请缩小问题范围后重试。"
    return text, trace
