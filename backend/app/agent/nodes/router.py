"""路由节点:意图识别与角色路由"""
import json
import logging
from app.agent.state import AgentState
from app.agent.llm import llm_invoke
from app.agent.prompts import load_prompt
from app.services.answer_guard import check_answer_request

logger = logging.getLogger(__name__)

VALID_INTENTS = {"prepare", "learn", "review", "interview", "violation", "chat"}

# 显式触发多 Agent 协作的短语(与前端开关互补)
COLLAB_HINTS = ("多agent协作", "多 agent 协作", "多智能体协作", "协作模式")


def _parse_json(text: str) -> dict:
    """健壮解析 LLM 输出的 JSON(兼容 markdown 代码块包裹、前后多余文本)"""
    text = text.strip()
    if text.startswith("```"):
        # 去掉 ```json ... ``` 包裹
        lines = text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines).strip()
    # 直接尝试解析
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # 兜底:花括号匹配提取第一个完整 JSON 对象(忽略字符串内的花括号)
    start = text.find("{")
    if start == -1:
        raise json.JSONDecodeError("未找到 JSON 对象", text, 0)
    depth = 0
    in_str = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start:i + 1])
    raise json.JSONDecodeError("JSON 对象不完整", text, start)


async def router_node(state: AgentState) -> dict:
    """识别用户意图,确定业务分支。风控优先级最高。"""
    # 指定分支(教案生成/面试实训等结构化入口)跳过意图识别,直接进入对应业务节点
    forced_branch = state.get("branch")
    if forced_branch:
        return {
            "risk_flag": False,
            "risk_type": "",
            "intent": state.get("intent") or "chat",
            "branch": forced_branch,
        }

    latest_msg = state["messages"][-1]["content"] if state["messages"] else ""

    # ---- 第一道:未截止作业/考试答案保护(AS-10,决策 12)----
    # 确定性判定优先于模型风控:命中题干或显式索要答案即拦截转引导
    guard = check_answer_request(
        state["user_id"], state["user_role"], latest_msg, state.get("course_id"),
    )
    if guard:
        logger.warning(
            "未截止作业答案保护命中(%s): %s", guard.get("reason"), guard.get("title"),
        )
        return {
            "risk_flag": True,
            "risk_type": guard.get("risk_type", "未截止作业答案保护"),
            "risk_target": f"{guard.get('kind', '')}#{guard.get('id', '')}",
            "intent": "violation",
            "branch": "block",
        }

    # ---- 第二道:前置风控(优先级最高)----
    risk_prompt = load_prompt("risk_guard")
    risk_resp = await llm_invoke([
        {"role": "system", "content": risk_prompt},
        {"role": "user", "content": f"用户身份:{state['user_role']}\n用户请求:{latest_msg}"},
    ], temperature=0.0)
    try:
        risk = _parse_json(risk_resp)
    except json.JSONDecodeError:
        risk = {"is_risky": False, "risk_type": "无", "action": "pass", "reason": "解析失败,默认放行"}

    if risk.get("is_risky") and risk.get("action") in ("intercept", "guide"):
        logger.warning("风控命中: type=%s, action=%s", risk.get("risk_type"), risk.get("action"))
        return {
            "risk_flag": True,
            "risk_type": risk.get("risk_type", "未知"),
            "intent": "violation",
            "branch": "block",
        }

    # ---- 多 Agent 协作:显式开关或显式短语,跳过单分支意图识别 ----
    if state.get("collaborate") or any(
        hint in latest_msg.lower() for hint in COLLAB_HINTS
    ):
        logger.info("协作模式启用,进入 team 分支")
        return {
            "risk_flag": False,
            "risk_type": "",
            "intent": "chat",
            "branch": "team",
        }

    # ---- 第二道:意图识别与分支路由 ----
    router_prompt = load_prompt("router")
    route_resp = await llm_invoke([
        {"role": "system", "content": router_prompt},
        {"role": "user", "content": f"用户身份:{state['user_role']}\n用户请求:{latest_msg}"},
    ], temperature=0.0)
    try:
        route = _parse_json(route_resp)
        intent = route.get("intent", "chat")
    except json.JSONDecodeError:
        intent = "chat"

    if intent not in VALID_INTENTS:
        intent = "chat"

    # 意图 → 分支映射
    branch_map = {
        "prepare": "teacher",
        "learn": "tutor",
        "review": "review",
        "interview": "interview",
        "chat": "tutor",       # 默认走助教对话
    }
    branch = branch_map.get(intent, "tutor")

    return {
        "risk_flag": False,
        "risk_type": "",
        "intent": intent,
        "branch": branch,
    }