"""计划调整节点:把用户中途追加的约束并入下一超级步

执行位置在工具执行之后、反思之前:
- 有 pending 调整时,把约束追加到当前提问末尾并回写任务计划,随后重新执行业务节点;
- 没有调整时直接进入反思,不改变原有链路。
"""
import logging

from app.agent.state import AgentState
from app.services.agent_runs import take_pending_plan_revisions

logger = logging.getLogger(__name__)

PLAN_NOTE_PREFIX = "【计划调整,请优先满足】"


def merge_instruction(messages: list[dict], instruction: str) -> list[dict]:
    """把调整要求并入最后一条用户消息,保留原问题作为检索与作答主体"""
    text = f"{PLAN_NOTE_PREFIX}{instruction}"
    merged = list(messages or [])
    if not merged:
        return [{"role": "user", "content": text}]
    last = merged[-1] or {}
    if last.get("role") != "user":
        merged.append({"role": "user", "content": text})
        return merged
    merged[-1] = {
        **last,
        "content": f"{last.get('content') or ''}\n\n{text}",
    }
    return merged


async def plan_patch_node(state: AgentState) -> dict:
    """消费本次运行的待生效调整;没有调整时清空标记,避免重复重跑"""
    revisions = take_pending_plan_revisions(state.get("run_id"))
    if not revisions:
        # 必须覆盖上一轮的生效标记,否则条件边会再次判定为"有调整"
        return {"plan_revisions": []}

    messages = state.get("messages") or []
    plan = list(state.get("task_plan") or [])
    cursor = int(state.get("current_step") or 0)
    for item in revisions:
        messages = merge_instruction(messages, item["instruction"])
        cursor += 1
        plan.append({
            "step": cursor,
            "action": "revise",
            "instruction": item["instruction"],
        })

    logger.info(
        "计划调整已生效 run=%s 条数=%s", state.get("run_id"), len(revisions),
    )
    return {
        "messages": messages,
        "task_plan": plan,
        "current_step": cursor,
        "plan_revisions": revisions,
    }
