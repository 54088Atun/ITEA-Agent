"""确定性风控规则:LLM 风控不可用时的兜底,并放行教师正常备课。"""
import re

# 教师/管理员的正常备课措辞:命中后不再交给 LLM 误判为"成品教案"
TEACHER_PREP_HINTS = (
    "教案", "备课", "课堂", "教学", "课时", "90分钟", "课程设计",
    "教学设计", "教学框架", "课堂活动", "授课", "讲稿",
)


def is_teacher_prep(text: str, role: str) -> bool:
    """教师/管理员的备课类请求视为正常业务,避免被成品教案规则误拦。"""
    if role not in ("teacher", "admin"):
        return False
    lowered = (text or "").lower()
    return any(hint in lowered for hint in TEACHER_PREP_HINTS)


def rule_risk(text: str, role: str) -> dict | None:
    """规则风控:只命中确定的高风险措辞,返回与 LLM 风控相同的结构。"""
    value = text or ""
    if re.search(r"替考|代考|考试(时)?(帮我|替我)答", value):
        return _risk("替考", "intercept", "出现替考/代考意图")
    if re.search(r"代写简历|帮我写(一份)?简历", value):
        return _risk("代写简历", "guide", "要求代写简历")
    if re.search(r"代写教案|直接上交的教案", value):
        return _risk("代写教案", "guide", "要求可直接上交的成品教案")
    if re.search(r"直接给(我)?(标准)?答案|给(我)?标准答案|索要.*标准答案", value):
        return _risk("索要标准答案", "guide", "要求直接给标准答案")
    if re.search(
        r"代写|代做|替我写|帮我写(一份|一篇)?(作业|论文|报告|代码)|"
        r"写完整代码|完整代码给我",
        value,
    ):
        return _risk("代写作业代码", "intercept", "要求代写作业/代码")
    return None


def _risk(risk_type: str, action: str, reason: str) -> dict:
    return {
        "is_risky": True,
        "risk_type": risk_type,
        "action": action,
        "reason": reason,
    }
