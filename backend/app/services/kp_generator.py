"""用 LLM 把课程目录/大纲文本解析为结构化草稿

输出契约:
{
  "syllabus": "整理后的课程大纲文本",
  "knowledge_points": [
    {"name": "...", "description": "...", "children": [{"name": "...", "description": "..."}]}
  ]
}
草稿只入库、不直接写正式知识点表,由教师选择性采纳。
"""
import json
import logging

from fastapi import HTTPException

from app.agent.llm import llm_invoke
from app.agent.nodes.router import _parse_json

logger = logging.getLogger(__name__)

MAX_ITEMS = 80


def _prompt(course_name: str, text: str) -> list[dict]:
    system = (
        "你是课程结构分析助手。请从教师提供的课程目录/大纲文本中提取知识点树与课程大纲。\n"
        "严格输出 JSON,不要输出解释或 Markdown 代码围栏:\n"
        '{"syllabus":"整理后的课程大纲(可含章节与课时)","knowledge_points":['
        '{"name":"一级知识点","description":"简述","children":[{"name":"二级知识点","description":"简述"}]}]}\n'
        f"约束:一级+二级知识点总数不超过 {MAX_ITEMS} 个;名称精简;不要编造原文没有的章节;"
        "文本不足以判断时保留原始层级名称。"
    )
    user = f"课程名称:{course_name}\n\n课程目录/大纲原文:\n{text}"
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _normalize(data: dict) -> dict:
    syllabus = str(data.get("syllabus") or "").strip()
    raw_items = data.get("knowledge_points")
    if not isinstance(raw_items, list):
        raise HTTPException(status_code=502, detail="模型返回格式不正确，请重试")

    def clean(node, depth=0):
        if not isinstance(node, dict):
            return None
        name = str(node.get("name") or "").strip()[:100]
        if not name:
            return None
        item = {
            "name": name,
            "description": str(node.get("description") or "").strip()[:500],
        }
        children = []
        if depth < 1 and isinstance(node.get("children"), list):
            for child in node["children"][:40]:
                cleaned = clean(child, depth + 1)
                if cleaned:
                    children.append(cleaned)
        if children:
            item["children"] = children
        return item

    items = []
    for raw in raw_items[:40]:
        cleaned = clean(raw)
        if cleaned:
            items.append(cleaned)
    if not items:
        raise HTTPException(status_code=502, detail="未能从文件中提取到知识点，请检查内容")
    return {"syllabus": syllabus, "knowledge_points": items}


async def generate_draft(course_name: str, text: str) -> dict:
    resp = await llm_invoke(_prompt(course_name, text), temperature=0.2)
    try:
        data = _parse_json(resp)
    except Exception as e:  # noqa: BLE001
        logger.warning("知识点草稿 JSON 解析失败: %s", e)
        raise HTTPException(status_code=502, detail="模型返回无法解析，请重试")
    if not isinstance(data, dict):
        raise HTTPException(status_code=502, detail="模型返回格式不正确，请重试")
    return _normalize(data)


def dumps(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False)
