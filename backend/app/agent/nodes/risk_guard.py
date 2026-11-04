"""风控拦截节点:branch=block 时生成拦截/引导话术并记录日志"""
import logging
from datetime import datetime, timezone
from app.agent.state import AgentState
from app.db.session import SessionLocal
from app.models.log import RiskLog

logger = logging.getLogger(__name__)

# 风险类型 → 引导话术模板
GUIDE_TEMPLATES = {
    "代写作业代码": (
        "检测到您的请求可能涉及代写作业代码,这超出了助教的合规边界。\n\n"
        "我可以换一种方式帮助您:\n"
        "1. 如果您卡在思路上,请描述您目前的想法,我用引导式提问帮您打通;\n"
        "2. 如果代码报错,请贴出报错信息,我帮您分析错误类型和排查方向;\n"
        "3. 如果概念不清楚,可以直接问我,我会结合课件为您讲解。\n\n"
        "[AI 辅助参考,请师生审核]"
    ),
    "代写教案": (
        "检测到您的请求可能涉及生成可直接上交的成品教案。\n\n"
        "按照合规要求,我只能生成**教案框架初稿**,包含教学目标、重难点、课时安排、"
        "课堂互动思考题和分层习题,供您审核修改。\n\n"
        "您可以这样说:“帮我生成《XX章节》的教案框架”,我来协助您。\n\n"
        "[AI 辅助参考,请教师审核修改]"
    ),
    "代写简历": (
        "检测到您的请求可能涉及代写简历。\n\n"
        "我可以为您提供**简历优化思路**:\n"
        "1. 逐段分析现有简历,指出描述不够量化、技能表述模糊的地方;\n"
        "2. 给出改进方向,如“将‘熟悉Python’改为具体项目经历描述”;\n"
        "3. 结合您的学情档案,推荐值得突出的项目与技能。\n\n"
        "请上传或粘贴您的现有简历,我来给出诊断建议。\n\n"
        "[AI 辅助参考,请师生审核]"
    ),
    "替考": (
        "检测到您的请求涉及考试作弊意图,这违反学术诚信底线,我必须拒绝。\n\n"
        "如果您对考试内容感到焦虑,我可以帮您:\n"
        "1. 梳理课程核心知识点,制定复习优先级;\n"
        "2. 针对薄弱知识点生成变式练习题;\n"
        "3. 规划考前的复习时间表。\n\n"
        "[AI 辅助参考,请师生审核]"
    ),
    "未截止作业答案保护": (
        "这道题属于尚未截止的作业/考试,为保护考核公平,我不能直接给出标准答案。\n\n"
        "可以这样帮您:\n"
        "1. 把涉及的概念讲清楚,您再自己推导;\n"
        "2. 用引导性问题帮您定位卡点;\n"
        "3. 截止后我可以陪您复盘这道题。\n\n"
        "[AI 辅助参考,请师生审核]"
    ),
    "索要标准答案": (
        "这道题更适合通过引导来掌握。直接给标准答案不利于您真正理解知识点。\n\n"
        "我们可以这样推进:\n"
        "1. 您先说说目前的思路,哪怕只是初步想法;\n"
        "2. 我用几个引导性问题帮您找到突破口;\n"
        "3. 您自己推导出答案后,记忆会更牢固。\n\n"
        "[AI 辅助参考,请师生审核]"
    ),
}

DEFAULT_BLOCK_MSG = (
    "您的请求触发了安全风控拦截。请换一种方式描述您的需求,"
    "例如描述思路、提问概念、贴出报错信息等,我会用引导式方式协助您。\n\n"
    "[AI 辅助参考,请师生审核]"
)


async def risk_guard_node(state: AgentState) -> dict:
    """风控分支处理:生成拦截/引导话术,记录风控日志"""
    risk_type = state.get("risk_type", "")
    latest_msg = state["messages"][-1]["content"] if state["messages"] else ""

    # 选择引导话术
    output = GUIDE_TEMPLATES.get(risk_type, DEFAULT_BLOCK_MSG)

    # 命中未截止作业/考试时,把目标写入动作摘要,便于教师/管理员追溯
    target = state.get("risk_target") or ""
    action = f"拦截转引导({target})" if target else "拦截转引导"

    # 记录风控日志(独立会话,避免影响主请求事务)
    try:
        db = SessionLocal()
        log = RiskLog(
            user_id=state["user_id"],
            request_content=latest_msg[:2000],
            risk_type=risk_type or "未知",
            action_taken=action[:50],
        )
        db.add(log)
        db.commit()
        db.close()
    except Exception as e:
        logger.error("风控日志写入失败: %s", e)

    return {
        "final_output": output,
        "reflection_passed": True,  # 拦截话术无需反思循环
        "messages": state["messages"] + [{"role": "assistant", "content": output}],
    }