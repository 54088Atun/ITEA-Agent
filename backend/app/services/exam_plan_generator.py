"""AI 考试科目/考核项建议(仅草稿)

输出契约(JSON 对象):
{"title": "建议试卷标题", "summary": "组卷思路", "duration_minutes": 90,
 "total_score": 100,
 "subjects": [{"subject": "科目/章节", "kp_names": ["知识点"], "reason": "考核理由",
               "items": [{"type": "single|multiple|judge|short",
                          "count": 5, "score": 2, "difficulty": 2}]}]}

LLM 输出先经 normalize_plan 清洗(丢弃非法题型/空考核项),再由调用方写入草稿;
解析失败或无可用科目时抛 HTTPException 502。
"""
import logging

from fastapi import HTTPException

from app.agent.llm import llm_invoke
from app.agent.nodes.router import _parse_json

logger = logging.getLogger(__name__)

MAX_SUBJECTS = 8
QUESTION_TYPES = {"single", "multiple", "judge", "short"}


def _clamp_int(value, default: int, low: int, high: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(low, min(high, number))


def _clean_items(raw_items) -> list[dict]:
    """清洗考核项:丢弃未知题型,题量/分值/难度限制在合理区间"""
    items = []
    for raw in raw_items or []:
        if not isinstance(raw, dict):
            continue
        qtype = str(raw.get("type") or "").strip().lower()
        if qtype not in QUESTION_TYPES:
            continue
        items.append({
            "type": qtype,
            "count": _clamp_int(raw.get("count"), 1, 1, 50),
            "score": _clamp_int(raw.get("score"), 2, 1, 100),
            "difficulty": _clamp_int(raw.get("difficulty"), 3, 1, 5),
        })
    return items


def _clean_subject(raw) -> dict | None:
    """清洗单个科目;没有名称或考核项时视为无效"""
    if not isinstance(raw, dict):
        return None
    name = str(raw.get("subject") or raw.get("name") or "").strip()[:80]
    if not name:
        return None
    items = _clean_items(raw.get("items"))
    if not items:
        return None
    kp_names = [
        str(item).strip()[:50]
        for item in (raw.get("kp_names") or [])
        if str(item).strip()
    ][:10]
    return {
        "subject": name,
        "kp_names": kp_names,
        "reason": str(raw.get("reason") or "").strip()[:200],
        "items": items,
        "question_count": sum(item["count"] for item in items),
        "score": sum(item["count"] * item["score"] for item in items),
    }


def normalize_plan(raw, duration_default: int, total_default: int) -> dict:
    """清洗建议方案;没有可用科目时抛 ValueError"""
    if not isinstance(raw, dict):
        raise ValueError("建议格式不正确")
    subjects = []
    for item in raw.get("subjects") or raw.get("items") or []:
        subject = _clean_subject(item)
        if subject:
            subjects.append(subject)
    subjects = subjects[:MAX_SUBJECTS]
    if not subjects:
        raise ValueError("建议中没有可用的科目/考核项")

    return {
        "title": str(raw.get("title") or "").strip()[:120] or "考试组卷建议",
        "summary": str(raw.get("summary") or "").strip()[:500],
        "duration_minutes": _clamp_int(
            raw.get("duration_minutes"), duration_default, 5, 300,
        ),
        "total_score": _clamp_int(raw.get("total_score"), total_default, 10, 500),
        "planned_score": sum(subject["score"] for subject in subjects),
        "subjects": subjects,
    }


def _prompt(
    course_name: str, points: list[str], duration_minutes: int, total_score: int,
) -> list[dict]:
    system = (
        "你是高校课程考试设计助手。请根据课程与知识点给出考试科目/考核项建议,"
        "严格输出 JSON 对象,不要解释:\n"
        '{"title":"建议试卷标题","summary":"组卷思路(120字内)","duration_minutes":90,'
        '"total_score":100,"subjects":[{"subject":"科目/章节","kp_names":["知识点"],'
        '"reason":"考核理由","items":[{"type":"single|multiple|judge|short",'
        '"count":5,"score":2,"difficulty":2}]}]}\n'
        "约束:科目 3-6 个,优先覆盖给定知识点;每个科目至少一个考核项;"
        "各考核项「题量 × 每题分值」之和应接近建议总分;difficulty 为 1-5;"
        "不要编造课程外内容。"
    )
    point_text = "、".join(points[:30]) if points else "该课程的核心知识点"
    user = (
        f"课程:{course_name}\n知识点:{point_text}\n"
        f"建议时长:{duration_minutes} 分钟,建议总分:{total_score} 分。"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


async def generate_exam_plan(
    course_name: str,
    points: list[str],
    duration_minutes: int = 90,
    total_score: int = 100,
) -> dict:
    """调用模型生成建议方案原始 JSON;清洗由调用方执行"""
    resp = await llm_invoke(
        _prompt(course_name, points, duration_minutes, total_score),
        temperature=0.4,
    )
    try:
        data = _parse_json(resp)
    except Exception as e:  # noqa: BLE001
        logger.warning("AI 科目建议 JSON 解析失败: %s", e)
        raise HTTPException(status_code=502, detail="AI 科目建议生成失败，请重试")
    if not isinstance(data, dict):
        raise HTTPException(status_code=502, detail="AI 科目建议生成失败，请重试")
    return data
