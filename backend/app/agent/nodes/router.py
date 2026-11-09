"""路由节点:意图识别与角色路由"""
import json
import logging
from app.agent.state import AgentState
from app.agent.llm import llm_invoke
from app.agent.prompts import load_prompt
from app.services.answer_guard import check_answer_request
from app.services.risk_rules import is_teacher_prep, rule_risk

logger = logging.getLogger(__name__)

VALID_INTENTS = {"prepare", "learn", "review", "interview", "violation", "chat"}

# 显式触发多 Agent 协作的短语(与前端开关互补)
COLLAB_HINTS = ("多agent协作", "多 agent 协作", "多智能体协作", "协作模式")

# 不参与协作的入口:面试有计时/评分状态机,管理端有写操作确认流程
COLLAB_EXCLUDED_BRANCHES = ("interview", "admin")

# 提醒类请求统一交给 tutor(该分支暴露 reminder_scheduler),避免被"复习"关键词带到 review
REMINDER_HINTS = ("提醒", "闹钟", "定时", "日程", "remind", "schedule")


def _is_reminder_request(text: str) -> bool:
    lowered = (text or "").lower()
    return any(hint in lowered for hint in REMINDER_HINTS)



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


async def _risk_gate(state: AgentState, latest_msg: str) -> dict | None:
    """模型风控闸门:命中返回风控结论,放行或不可用时返回 None

    先跑确定性规则:高风险措辞直接拦截;教师/管理员正常备课直接放行,
    避免把"安排一次 90 分钟课堂"误判为成品教案。LLM 不可用时回退规则库,
    不再对已知高风险请求静默放行。
    """
    role = state.get("user_role", "")
    rule = rule_risk(latest_msg, role)
    if rule:
        logger.warning("规则风控命中: %s", rule.get("risk_type"))
        return rule
    if is_teacher_prep(latest_msg, role):
        logger.info("教师备课请求按规则放行")
        return None

    try:
        risk_resp = await llm_invoke([
            {"role": "system", "content": load_prompt("risk_guard")},
            {"role": "user", "content": f"用户身份:{role}\n用户请求:{latest_msg}"},
        ], temperature=0.0)
    except Exception as exc:  # noqa: BLE001
        logger.error("前置风控调用失败,回退规则库: %s", exc)
        return rule_risk(latest_msg, role)
    try:
        risk = _parse_json(risk_resp)
    except ValueError:
        return rule_risk(latest_msg, role)
    if (
        isinstance(risk, dict)
        and risk.get("is_risky")
        and risk.get("action") in ("intercept", "guide")
    ):
        return risk
    return None


async def router_node(state: AgentState) -> dict:
    """识别用户意图,确定业务分支。风控优先级最高。"""
    latest_msg = state["messages"][-1]["content"] if state["messages"] else ""

    # ---- 第一道:未截止作业/考试答案保护(AS-10,决策 12)----
    # 确定性判定优先于模型风控:命中题干或显式索要答案即拦截转引导。
    # 必须放在 forced branch 之前:助教/备课/面试/管理入口都带指定分支,
    # 若先 return 会整体旁路答案保护与风控。
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
    risk = await _risk_gate(state, latest_msg)
    if risk:
        logger.warning("风控命中: type=%s, action=%s", risk.get("risk_type"), risk.get("action"))
        return {
            "risk_flag": True,
            "risk_type": risk.get("risk_type", "未知"),
            "intent": "violation",
            "branch": "block",
        }

    # ---- 多 Agent 协作:显式开关或显式短语,优先于指定分支 ----
    # 指定分支的页面(助教/备课)同样尊重协作开关;面试与管理端排除在外
    forced_branch = state.get("branch")
    wants_collab = bool(state.get("collaborate")) or any(
        hint in latest_msg.lower() for hint in COLLAB_HINTS
    )
    if (
        wants_collab
        and forced_branch not in COLLAB_EXCLUDED_BRANCHES
        and not state.get("review_submit")
    ):
        logger.info("协作模式启用,进入 team 分支")
        return {
            "risk_flag": False,
            "risk_type": "",
            "intent": "chat",
            "branch": "team",
        }

    # ---- 指定分支(教案生成/面试实训等结构化入口):风控已通过,跳过意图识别 ----
    if forced_branch:
        return {
            "risk_flag": False,
            "risk_type": "",
            "intent": state.get("intent") or "chat",
            "branch": forced_branch,
        }

    # ---- 提醒类请求:交给 tutor,保证 reminder_scheduler 可用 ----
    if _is_reminder_request(latest_msg):
        return {
            "risk_flag": False,
            "risk_type": "",
            "intent": "chat",
            "branch": "tutor",
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