"""按课程知识点生成针对性练习(用于错题本空态的"生成练习")"""
import logging

from fastapi import HTTPException

from app.agent.llm import llm_invoke
from app.agent.nodes.router import _parse_json

logger = logging.getLogger(__name__)

MAX_COUNT = 5


async def generate_practice(
    course_name: str, points: list[str], count: int = 3,
) -> list[dict]:
    count = max(1, min(count, MAX_COUNT))
    point_text = "、".join(points[:20]) if points else "该课程的基础概念"
    system = (
        "你是高校课程练习出题助手。请围绕给定知识点出题,严格输出 JSON 数组,不要解释:\n"
        '[{"question":"题干","kp_name":"对应知识点","hint":"一句提示"}]'
    )
    user = (
        f"课程:{course_name}\n知识点:{point_text}\n"
        f"请出 {count} 道难度递进的练习,题干完整可作答,不要给出答案。"
    )
    resp = await llm_invoke(
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=0.4,
    )
    try:
        data = _parse_json(resp)
    except Exception as e:  # noqa: BLE001
        logger.warning("练习生成 JSON 解析失败: %s", e)
        raise HTTPException(status_code=502, detail="生成练习失败，请重试")

    if isinstance(data, dict):
        data = data.get("questions") or data.get("items") or []
    if not isinstance(data, list) or not data:
        raise HTTPException(status_code=502, detail="生成练习失败，请重试")

    items = []
    for raw in data[:count]:
        if not isinstance(raw, dict):
            continue
        question = str(raw.get("question") or "").strip()
        if not question:
            continue
        items.append({
            "question": question[:1000],
            "kp_name": str(raw.get("kp_name") or "")[:100],
            "hint": str(raw.get("hint") or "")[:300],
        })
    if not items:
        raise HTTPException(status_code=502, detail="生成练习失败，请重试")
    return items
