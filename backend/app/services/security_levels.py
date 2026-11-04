"""信息分级(AG-05):四级口径 + 人工调整(决策 #4)

四级口径:
- full          公开:公开或低敏内容,直接输出
- auto          内部:内部内容,规则校验后输出
- manual        敏感:敏感内容,仅授权角色可查看
- confidential  机密:机密内容,仅管理员可查看

判定来源:关键词规则 + 模型自评标签 + 数据源标签;取规则与自评的较高者。
人工调整:教师/管理员可对会话设置覆盖级别,上调或下调均覆盖自动判定。
兼容旧三级:public→full、internal→auto、sensitive→manual。
"""
import re
from typing import Optional

LEVELS = ("full", "auto", "manual", "confidential")
LEVEL_RANK = {level: index for index, level in enumerate(LEVELS)}
LEVEL_LABEL = {
    "full": "公开",
    "auto": "内部",
    "manual": "敏感",
    "confidential": "机密",
}
LEVEL_DESC = {
    "full": "公开或低敏内容，直接输出",
    "auto": "内部内容，规则校验后输出",
    "manual": "敏感内容，需授权角色查看",
    "confidential": "机密内容，仅管理员可查看",
}

LEGACY_TO_LEVEL = {
    "public": "full",
    "internal": "auto",
    "sensitive": "manual",
    "confidential": "confidential",
}

ROLE_MAX = {
    "student": "auto",
    "teacher": "manual",
    "admin": "confidential",
}

HINT_PATTERN = re.compile(
    r"\[\[security:(full|auto|manual|confidential|public|internal|sensitive)\]\]",
    re.IGNORECASE,
)

# 从高到低匹配,命中即取最高级别
RULES = (
    ("confidential", re.compile(
        r"机密文件|商业机密|未公开试题|内部审计报告|核心算法源码",
    )),
    ("manual", re.compile(
        r"密钥|secret[_ ]?key|api[_ ]?key|密码|身份证|银行卡|护照号|薪资|工资条|家庭住址"
        r"|手机号|联系方式|个人邮箱|学情|掌握度|错题|成绩|排名|个人档案|面试记录"
        r"|作业提交|学习记录",
        re.IGNORECASE,
    )),
    ("auto", re.compile(
        r"课程资料|内部资料|题库|教案|课件|班级名单|学生名单|考试答案|参考答案",
    )),
)


def normalize_level(level: Optional[str]) -> Optional[str]:
    if not level:
        return None
    value = level.lower()
    if value in LEVEL_RANK:
        return value
    return LEGACY_TO_LEVEL.get(value)


def role_max_level(user) -> str:
    role = getattr(user, "role", "") or ""
    return ROLE_MAX.get(role, "full")


def max_level(left: str, right: str) -> str:
    left_n = normalize_level(left)
    right_n = normalize_level(right)
    if left_n is None:
        return right_n or "full"
    if right_n is None:
        return left_n
    return left_n if LEVEL_RANK[left_n] >= LEVEL_RANK[right_n] else right_n


def detect_level(text: str) -> tuple[str, list[str]]:
    """按关键词规则判定级别,返回 (level, 命中片段)"""
    if not text:
        return "full", []
    for level, pattern in RULES:
        hits = pattern.findall(text)
        if hits:
            return level, sorted(set(hits))[:5]
    return "full", []


def split_hint(text: str) -> tuple[str, Optional[str]]:
    """提取并移除模型自评标签,返回规范化级别"""
    match = HINT_PATTERN.search(text or "")
    if not match:
        return text, None
    return HINT_PATTERN.sub("", text).strip(), normalize_level(match.group(1))


def classify(text: str, hint: Optional[str] = None) -> str:
    rule_level, _ = detect_level(text)
    hint_level = normalize_level(hint)
    return max_level(rule_level, hint_level) if hint_level else rule_level


def can_view(user, level: str) -> bool:
    normalized = normalize_level(level) or "full"
    return LEVEL_RANK[normalized] <= LEVEL_RANK[role_max_level(user)]


def approval_mode(level: str) -> str:
    """返回该级别对应的审批模式:full/auto/manual/confidential"""
    return normalize_level(level) or "full"


def level_meta(level: str) -> dict:
    normalized = approval_mode(level)
    return {
        "level": normalized,
        "label": LEVEL_LABEL[normalized],
        "description": LEVEL_DESC[normalized],
        "approval_mode": normalized,
    }


def mask_message(level: str) -> str:
    normalized = approval_mode(level)
    label = LEVEL_LABEL.get(normalized, "受限")
    return (
        f"该回答包含{label}级别信息，当前角色无权查看，内容已隐藏。"
        "如需了解，请联系教师或管理员。[AI 辅助参考]"
    )


def enforce(
    text: str, user, hint: Optional[str] = None, override: Optional[str] = None,
) -> tuple[str, str, bool]:
    """按角色裁决输出内容;人工覆盖级别优先于自动判定"""
    cleaned, tag_hint = split_hint(text)
    level = normalize_level(override) or classify(cleaned, hint or tag_hint)
    if can_view(user, level):
        return cleaned, level, False
    return mask_message(level), level, True
