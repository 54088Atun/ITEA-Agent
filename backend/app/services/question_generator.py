"""AI 出题:按课程知识点生成题目草稿(仅草稿,不直接入库)

输出契约:JSON 数组,每项 {type, stem, options, answer, analysis, difficulty}
失败时由调用方决定降级或报错。
"""
import logging

from fastapi import HTTPException

from app.agent.llm import llm_invoke
from app.agent.nodes.router import _parse_json

logger = logging.getLogger(__name__)

MAX_COUNT = 20


def _prompt(course_name: str, points: str, count: int, types: list[str]) -> list[dict]:
    system = (
        "你是高校课程题库出题助手。请围绕给定知识点出题,严格输出 JSON 数组,不要解释:\n"
        '[{"type":"single|multiple|judge","stem":"题干","options":[{"key":"A","text":"选项"}],'
        '"answer":"A 或 A,C 或 true/false","analysis":"解析","difficulty":1-5}]\n'
        "约束:单选 4 个选项且答案唯一;多选至少 2 个正确项,答案用英文逗号分隔;"
        "判断题 options 固定为 [{\"key\":\"true\",\"text\":\"正确\"},{\"key\":\"false\",\"text\":\"错误\"}],"
        "answer 为 true 或 false;题干完整可作答;不要编造课程外内容。"
    )
    user = (
        f"课程:{course_name}\n知识点:{points}\n"
        f"题型限定:{','.join(types)}\n请出 {count} 道难度递进的题目。"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


async def generate_questions(
    course_name: str, points: list[str], count: int, types: list[str],
) -> list[dict]:
    count = max(1, min(count, MAX_COUNT))
    point_text = "、".join(points[:20]) if points else "该课程的核心知识点"
    resp = await llm_invoke(
        _prompt(course_name, point_text, count, types or ["single"]),
        temperature=0.5,
    )
    try:
        data = _parse_json(resp)
    except Exception as e:  # noqa: BLE001
        logger.warning("AI 出题 JSON 解析失败: %s", e)
        raise HTTPException(status_code=502, detail="AI 出题失败，请重试")
    if isinstance(data, dict):
        data = data.get("questions") or data.get("items") or []
    if not isinstance(data, list) or not data:
        raise HTTPException(status_code=502, detail="AI 出题失败，请重试")
    return [item for item in data[:MAX_COUNT] if isinstance(item, dict)]
