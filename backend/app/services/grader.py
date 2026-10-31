"""AI 辅助批改:只产出建议分数与评语

约束:
- 本模块不写数据库、不下发学生,由调用方写入 ai_* 字段
- 模型不可用(未配置密钥/超时/解析失败)时降级为规则初评,并标记 source='rule'
- 正式成绩必须由教师确认接口写入
"""
import logging
import re

from app.agent.llm import llm_invoke
from app.agent.nodes.router import _parse_json

logger = logging.getLogger(__name__)

MAX_FEEDBACK = 1500
_SPLIT_RE = re.compile(r"[，。；：、,.;:!?！？\n\t（）()【】\[\]\s]+")


def _rule_grade(answer: str, reference: str | None) -> dict:
    """规则初评:参考答案关键词覆盖率 / 作答长度"""
    ans = (answer or "").strip()
    if not ans:
        return {
            "score": 0,
            "feedback": "未检测到有效作答内容，建议退回重做。",
            "source": "rule",
        }

    ref = (reference or "").strip()
    if ref:
        tokens = [t for t in _SPLIT_RE.split(ref) if len(t) >= 2][:40]
        if tokens:
            hit = sum(1 for t in tokens if t in ans)
            ratio = hit / len(tokens)
            score = max(0, min(95, 40 + int(55 * ratio)))
            feedback = (
                f"规则初评：覆盖参考答案关键点 {hit}/{len(tokens)}。"
                "得分由关键词覆盖与作答完整度估算，请教师结合逻辑与表达复核。"
            )
            return {"score": score, "feedback": feedback, "source": "rule"}

    score = max(0, min(75, 40 + len(ans) // 30))
    return {
        "score": score,
        "feedback": "规则初评：未提供参考答案，评分仅依据作答长度与完整性估算，请教师人工复核。",
        "source": "rule",
    }


async def grade_submission(
    title: str,
    description: str | None,
    answer: str,
    reference: str | None,
) -> dict:
    """返回 {score, feedback, source};失败自动降级为规则初评"""
    system = (
        "你是高校课程作业批改助手。请依据作业要求与参考答案给学生作答打分。\n"
        "严格输出 JSON,不要输出解释或 Markdown 代码围栏:\n"
        '{"score": 0-100 的整数, "feedback": "面向学生的具体评语(指出优点、问题与改进建议)"}\n'
        "评分要客观,不因篇幅给分;未作答记 0 分。"
    )
    user = (
        f"作业标题:{title}\n"
        f"作业要求:{description or '未填写'}\n"
        f"参考答案:{reference or '未提供,请按题意判断'}\n"
        f"学生作答:\n{answer}"
    )
    try:
        resp = await llm_invoke(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0.1,
        )
        data = _parse_json(resp)
        if not isinstance(data, dict):
            raise ValueError("模型返回非对象")
        score = int(round(float(data.get("score"))))
        feedback = str(data.get("feedback") or "").strip()
        if not feedback:
            raise ValueError("模型未返回评语")
        return {
            "score": max(0, min(100, score)),
            "feedback": feedback[:MAX_FEEDBACK],
            "source": "llm",
        }
    except Exception as e:  # noqa: BLE001 模型不可用时降级
        logger.warning("AI 批改降级为规则初评: %s", e)
        return _rule_grade(answer, reference)
