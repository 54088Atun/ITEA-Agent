"""反思校验节点:幻觉自查、合规复核、标注检查"""
import re
import logging
from app.agent.state import AgentState
from app.agent.llm import llm_invoke
from app.core.config import settings

logger = logging.getLogger(__name__)

AI_TAG = "[AI 辅助参考"

MAX_CODE_BLOCK_LINES = 30


def _has_long_code_block(output: str, max_lines: int = MAX_CODE_BLOCK_LINES) -> bool:
    """线性扫描代码块行数,避免正则灾难性回溯阻塞事件循环"""
    in_block = False
    lines = 0
    for line in output.splitlines():
        if line.startswith("```"):
            if in_block:
                if lines > max_lines:
                    return True
                in_block = False
                lines = 0
            else:
                in_block = True
                lines = 0
            continue
        if in_block:
            lines += 1
    return in_block and lines > max_lines


def _quick_checks(output: str, rag_context: str, require_rag: bool = True) -> list[str]:
    """规则快检,返回问题列表"""
    issues = []

    # 1. 标注检查:必须包含 AI 辅助参考标识
    if AI_TAG not in output:
        issues.append("输出缺少 [AI 辅助参考] 标识")

    # 2. 合规快检:超长完整代码块疑似代写
    if _has_long_code_block(output):
        issues.append("输出包含超长完整代码块(>30行),疑似代写作业代码")

    # 3. 幻觉快检:专业内容场景下无知识库支撑
    has_technical_terms = bool(re.search(r"[A-Za-z]{6,}|算法|数据结构|复杂度|指针|递归", output))
    if require_rag and has_technical_terms and not rag_context.strip():
        issues.append("输出包含专业内容但无知识库检索支撑,存在幻觉风险")

    return issues


async def reflect_node(state: AgentState) -> dict:
    """反思校验:先规则快检,再 LLM 深度复核"""
    output = state.get("final_output", "")
    rag_context = state.get("rag_context", "")
    count = state.get("reflection_count", 0)

    # 达到最大循环次数,直接放行(避免死循环)
    if count >= settings.MAX_REFLECTION_ROUNDS:
        logger.warning("反思达到最大循环次数 %d,强制放行", count)
        # 强制补标注
        if AI_TAG not in output:
            output += "\n\n[AI 辅助参考,请师生审核]"
        return {
            "reflection_passed": True,
            "reflection_count": count + 1,
            "final_output": output,
        }

    # ---- 第一道:规则快检 ----
    # admin 分支与"无可见课程"的通用问答不做 RAG 必备检查,否则会反复重写
    is_admin = state.get("branch") == "admin"
    has_course = bool(state.get("course_id"))
    issues = _quick_checks(output, rag_context, require_rag=not (is_admin or not has_course))

    # ---- 第二道:LLM 深度复核(仅当快检有疑点或专业输出时触发)----
    if issues or rag_context.strip():
        if is_admin:
            hallucination_rule = "平台解读是否有给定统计快照依据"
        elif not has_course:
            hallucination_rule = "是否避免编造课程事实与个人学情(当前无课程资料)"
        else:
            hallucination_rule = "专业知识点是否有知识库依据(下方提供检索上下文)"
        reflect_prompt = (
            "你是 ITEA-Agent 的反思校验器。请检查以下 AI 输出是否存在问题,严格输出 JSON:\n"
            '{"passed": true|false, "issues": ["问题1", "问题2"], "suggestion": "修改建议"}\n\n'
            "校验项:\n"
            f"1. 幻觉:{hallucination_rule}\n"
            "2. 合规:是否包含完整作业代码/完整教案/代写简历/主观题标准答案\n"
            "3. 风格:是否符合角色(学生端应引导式、教师端应框架式)\n"
            "4. 标注:是否包含 [AI 辅助参考] 标识\n\n"
            f"知识库上下文:\n{rag_context[:2000] if rag_context else '(无)'}\n\n"
            f"待校验输出:\n{output[:3000]}\n\n"
            f"规则快检已发现的问题:{issues if issues else '无'}"
        )
        try:
            from app.agent.nodes.router import _parse_json
            resp = await llm_invoke(
                [{"role": "user", "content": reflect_prompt}], temperature=0.0
            )
            result = _parse_json(resp)
            if not result.get("passed", True):
                issues.extend(result.get("issues", []))
        except Exception as e:
            logger.warning("LLM 反思复核异常,按规则快检结果处理: %s", e)

    # ---- 判定 ----
    if not issues:
        return {"reflection_passed": True, "reflection_count": count + 1}

    # 不通过:补标注 + 生成反思意见,交由上层路由决定是否重写
    logger.info("反思未通过(第 %d 轮): %s", count + 1, issues)
    patched = output
    if AI_TAG not in patched:
        patched += "\n\n[AI 辅助参考,请师生审核]"

    return {
        "reflection_passed": False,
        "reflection_count": count + 1,
        "reflection_notes": ";".join(issues),
        "final_output": patched,  # 若重写次数用尽,此补丁版本作为兜底输出
    }