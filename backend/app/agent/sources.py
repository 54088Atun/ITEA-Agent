"""回答来源标注(ST-02 / AG-12)

Agent 回答统一在结尾标注本轮依据,避免把通用知识误当作课程资料:
- 课程资料:来自 RAG 检索命中的课程素材,按来源标题去重
- 学情数据:本轮读取了学生掌握度、错题、复习或面试记录
- 通用知识:未检索到课程资料时的兜底说明
"""
import re

_SOURCE_PATTERN = re.compile(r"\(来源:\s*([^)]+?)\s*\)")
MAX_COURSE_SOURCES = 5
FOOTER_MARK = "**参考来源**"


def collect_course_sources(rag_context: str, limit: int = MAX_COURSE_SOURCES) -> list[str]:
    """从带来源标注的检索上下文中提取素材名,去重保序"""
    names: list[str] = []
    for name in _SOURCE_PATTERN.findall(rag_context or ""):
        name = name.strip()
        if name and name not in names:
            names.append(name)
        if len(names) >= limit:
            break
    return names


def _fragment_label(fragment: dict) -> str:
    title = str(fragment.get("source") or "课程资料").strip()
    page = fragment.get("page")
    return f"{title} 第 {page} 页" if page else title


def _fragment_url(fragment: dict, course_id: int | None) -> str:
    """素材预览链接:PDF 追加 #page=N,便于点击定位到页"""
    material_id = fragment.get("material_id")
    if not material_id or not course_id:
        return ""
    url = f"/api/course/{course_id}/materials/{material_id}/preview"
    page = fragment.get("page")
    return f"{url}#page={page}" if page else url


def _course_items(
    rag_context: str, fragments: list[dict] | None, course_id: int | None,
) -> list[dict]:
    """优先用检索片段的素材 ID/页码生成可点击来源,缺失时回退到标题解析"""
    items: list[dict] = []
    seen = set()
    for fragment in (fragments or []):
        if not isinstance(fragment, dict):
            continue
        label = _fragment_label(fragment)
        key = (fragment.get("material_id"), fragment.get("page"), label)
        if key in seen:
            continue
        seen.add(key)
        item = {"type": "course", "label": label}
        url = _fragment_url(fragment, course_id)
        if url:
            item["url"] = url
        items.append(item)
        if len(items) >= MAX_COURSE_SOURCES:
            break
    if items:
        return items
    return [
        {"type": "course", "label": name}
        for name in collect_course_sources(rag_context)
    ]


def build_sources(
    rag_context: str = "",
    has_profile: bool = False,
    extra_labels: tuple[str, ...] | list[str] = (),
    fragments: list[dict] | None = None,
    course_id: int | None = None,
) -> list[dict]:
    """生成本轮回答的来源清单:course / profile / extra / general"""
    items: list[dict] = _course_items(rag_context, fragments, course_id)
    if has_profile:
        items.append({"type": "profile", "label": "学情数据：掌握度 / 错题 / 复习记录"})
    for label in extra_labels:
        items.append({"type": "data", "label": label})
    if any(item["type"] == "course" for item in items):
        items.append({"type": "general", "label": "通用知识：课程资料未覆盖的部分为通用知识补充"})
    else:
        items.append({"type": "general", "label": "通用知识：未检索到本课程资料，以下内容为通用知识"})
    return items


def render_footer(sources: list[dict]) -> str:
    """渲染为 Markdown 页脚;无来源时返回空串"""
    if not sources:
        return ""
    lines = ["---", FOOTER_MARK]
    for item in sources:
        label = str(item["label"]).replace("[", "［").replace("]", "］")
        url = item.get("url")
        lines.append(f"- [{label}]({url})" if url else f"- {label}")
    return "\n".join(lines)


def append_sources_footer(output: str, sources: list[dict]) -> str:
    """在回答末尾追加来源页脚(幂等:已存在则不重复追加)"""
    text = (output or "").rstrip()
    if not text or FOOTER_MARK in text:
        return text
    footer = render_footer(sources)
    return f"{text}\n\n{footer}" if footer else text
