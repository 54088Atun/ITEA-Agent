"""admin:管理后台助手节点

- 写动作(P0-6):先返回「将影响 N 个对象」的预览卡片,确认后才执行并写审计;
- 一句话确认/取消:短句「确认/取消」直接结算上一轮的待确认动作;
- 只读数据:不再预取平台快照,改由模型按需调用 `admin.*` 工具(P0-5);
- 最后把动作结果与工具结果交给模型生成回答。
"""
import json
import logging
import time
import uuid

from app.agent.llm import llm_invoke
from app.agent.nodes.router import _parse_json
from app.agent.nodes.tool_executor import tool_schemas_for_role
from app.agent.prompts import load_prompt, render_prompt
from app.agent.state import AgentState
from app.agent.tool_loop import run_tool_loop
from app.db.session import SessionLocal
from app.models.user import User
from app.services.admin_actions import (
    ADMIN_ACTIONS, action_catalog_text, execute_action, execute_previewed_action,
    preview_action,
)

logger = logging.getLogger(__name__)

AI_TAG = "[AI 辅助参考,请管理员复核]"

CONFIRM_WORDS = ("确认", "确定", "执行", "同意", "可以", "confirm", "yes", "ok")
CANCEL_WORDS = ("取消", "不执行", "算了", "不要", "撤销", "cancel", "no")
INTENT_MAX_LEN = 8


async def _emit(queue, event_type: str, data: dict) -> None:
    """向 SSE 队列写一条事件(与 chat._stream_graph 的 event 分支兼容)"""
    if queue is None:
        return
    payload = json.dumps({"type": event_type, "data": data}, ensure_ascii=False)
    await queue.put(("event", f"data: {payload}\n\n"))


def _latest_user_text(state: AgentState) -> str:
    for message in reversed(state.get("messages", [])):
        if message.get("role") == "user":
            return message.get("content", "") or ""
    return ""


async def _decide_action(state: AgentState) -> dict | None:
    """让模型把用户请求映射成一个已登记动作;不是任务时返回 None"""
    latest = _latest_user_text(state)
    if not latest.strip():
        return None

    prompt = render_prompt(
        load_prompt("admin_action"),
        action_catalog=action_catalog_text(),
        admin_level=state.get("admin_level") or "super",
    )
    try:
        resp = await llm_invoke([
            {"role": "system", "content": prompt},
            {"role": "user", "content": latest},
        ])
        decision = _parse_json(resp)
    except Exception as exc:  # noqa: BLE001
        logger.info("管理动作识别跳过: %s", exc)
        return None

    key = str(decision.get("action") or "none").strip()
    if key in ("", "none", "null"):
        return None
    if key not in ADMIN_ACTIONS:
        logger.warning("模型返回未登记的管理动作: %s", key)
        return None
    args = decision.get("args")
    return {"key": key, "args": args if isinstance(args, dict) else {}}


def _with_admin(state: AgentState, handler) -> dict:
    """在独立会话里以当前管理员身份执行;查不到账号时返回结构化失败"""
    db = SessionLocal()
    try:
        admin = db.query(User).filter(User.id == state.get("user_id")).first()
        if admin is None:
            return {"ok": False, "message": "当前管理员账号不存在", "data": {}}
        return handler(db, admin)
    finally:
        db.close()


def _run_action(state: AgentState, decision: dict) -> dict:
    """执行动作;权限与审计在 execute_action 内统一处理"""
    return _with_admin(
        state,
        lambda db, admin: execute_action(
            db, admin, decision["key"], decision.get("args"),
        ),
    )


def _preview_action(state: AgentState, decision: dict) -> dict:
    """预览动作影响范围,返回确认令牌;不写库"""
    return _with_admin(
        state,
        lambda db, admin: preview_action(
            db, admin, decision["key"], decision.get("args") or {},
        ),
    )


def _write_intent(text: str) -> str:
    """识别短句确认/取消;长句按新任务处理,避免误触发"""
    value = (text or "").strip().lower()
    if not value or len(value) > INTENT_MAX_LEN:
        return ""
    if any(word in value for word in CANCEL_WORDS):
        return "cancel"
    if any(word in value for word in CONFIRM_WORDS):
        return "confirm"
    return ""


def _pending_valid(pending: dict) -> bool:
    """待确认动作是否仍可结算:动作已登记、令牌齐全且未过期"""
    if not isinstance(pending, dict):
        return False
    if pending.get("action") not in ADMIN_ACTIONS:
        return False
    if not pending.get("confirmation_token") or not pending.get("idempotency_key"):
        return False
    return float(pending.get("expires_at") or 0) > time.time()


def _execute_pending(state: AgentState, pending: dict) -> dict:
    """凭预览阶段签发的令牌执行,幂等键保证重复确认只执行一次"""
    return _with_admin(
        state,
        lambda db, admin: execute_previewed_action(
            db, admin, pending["action"], pending.get("params") or {},
            pending["confirmation_token"], pending["idempotency_key"],
        ),
    )


async def _settle_pending(state: AgentState, pending: dict, intent: str) -> dict:
    """结算上一轮待确认动作:取消不写库,确认才执行"""
    queue = state.get("stream_queue")
    if intent == "cancel":
        label = pending.get("label") or pending.get("action")
        result = {
            "ok": False, "cancelled": True,
            "message": f"已取消「{label}」,未做任何变更",
            "data": {"action": pending.get("action"), "cancelled": True},
        }
    else:
        result = _execute_pending(state, pending)
    await _emit(queue, "tool_result", {
        "ok": bool(result.get("ok")),
        "message": result.get("message", ""),
    })
    return result


async def _preview_write_action(state: AgentState, decision: dict) -> tuple[dict, dict]:
    """写动作只返回预览卡片与确认令牌,不执行;返回(动作结果, 待确认动作)"""
    action = ADMIN_ACTIONS[decision["key"]]
    preview = _preview_action(state, decision)
    if not preview.get("ok"):
        return preview, {}

    data = preview.get("data") or {}
    pending = {
        "action": decision["key"],
        "params": decision.get("args") or {},
        "label": action.label,
        "confirmation_token": data.get("confirmation_token"),
        "idempotency_key": uuid.uuid4().hex,
        "expires_at": time.time() + float(data.get("expires_in") or 0),
    }
    await _emit(state.get("stream_queue"), "tool_call", {
        "name": action.label, "preview": f"预览动作 {action.key}",
    })
    await _emit(state.get("stream_queue"), "confirm_required", {
        "action": decision["key"],
        "params": pending["params"],
        "label": action.label,
        "message": preview.get("message", ""),
        "count": data.get("count"),
        "shown": data.get("shown"),
        "truncated": bool(data.get("truncated")),
        "risk_level": data.get("risk_level") or "medium",
        "items": data.get("items") or [],
        "skipped": data.get("skipped") or [],
        "confirmation_token": pending["confirmation_token"],
        "idempotency_key": pending["idempotency_key"],
        "expires_in": data.get("expires_in"),
    })

    # 令牌不进入模型上下文,避免被复述到回答里
    model_data = {
        key: value for key, value in data.items()
        if key != "confirmation_token"
    }
    return {
        "ok": False,
        "preview": True,
        "requires_confirmation": True,
        "message": preview.get("message", ""),
        "data": model_data,
    }, pending


async def _handle_action(state: AgentState) -> tuple[dict, dict]:
    """按「结算待确认 → 识别新动作 → 预览或执行」的顺序处理本轮动作"""
    pending = state.get("pending_action") or {}
    intent = _write_intent(_latest_user_text(state))
    if intent and _pending_valid(pending):
        result = await _settle_pending(state, pending, intent)
        return result, ({} if result.get("ok") or intent == "cancel" else pending)

    decision = await _decide_action(state)
    if not decision:
        return {"ok": False, "message": "本轮未执行任务", "data": {}}, pending

    action = ADMIN_ACTIONS[decision["key"]]
    if action.requires_write:
        return await _preview_write_action(state, decision)

    await _emit(state.get("stream_queue"), "tool_call", {
        "name": action.label, "preview": f"动作 {action.key}",
    })
    result = _run_action(state, decision)
    await _emit(state.get("stream_queue"), "tool_result", {
        "ok": bool(result.get("ok")),
        "message": result.get("message", ""),
    })
    return result, {}


async def admin_node(state: AgentState) -> dict:
    """写动作先预览再执行,只读数据由模型调用 admin.* 工具后生成回答"""
    action_result, pending = await _handle_action(state)

    system_prompt = render_prompt(
        load_prompt("admin"),
        admin_level=state.get("admin_level") or "super",
        platform_stats="(未预置快照:需要数据时调用 admin.* 只读工具查询)",
        action_result=json.dumps(action_result, ensure_ascii=False, indent=2),
    )
    reflection_notes = state.get("reflection_notes", "")
    if reflection_notes:
        system_prompt += (
            "\n\n【反思校验意见】上一轮回答存在以下问题,请修正后重新回答:\n"
            + reflection_notes
        )

    messages = [{"role": "system", "content": system_prompt}]
    for message in state.get("messages", [])[-6:]:
        messages.append({
            "role": message.get("role", "user"),
            "content": message.get("content", ""),
        })

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
            tools=tool_schemas_for_role("admin"),
            sink=state.get("stream_queue"),
        )
    except Exception as e:  # noqa: BLE001
        logger.error("admin LLM 调用失败: %s", e)
        output, trace = f"抱歉,管理助手暂时无法响应,请稍后重试。{AI_TAG}", []

    if AI_TAG not in output:
        output += f"\n\n{AI_TAG}"

    return {
        "final_output": output,
        # 待确认动作随状态下发,供下一轮「确认/取消」与断点恢复使用
        "pending_action": pending,
        "tool_trace": [
            {
                "name": item.get("name"),
                "arguments": item.get("arguments") or {},
                "result": item.get("result") or {},
            }
            for item in trace
        ],
    }
