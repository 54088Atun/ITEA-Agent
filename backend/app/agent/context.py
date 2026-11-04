"""上下文工程(P1-2)

统一按预算组装模型上下文,避免每个节点把学情、大纲、检索结果全量拼进 prompt:
- token 估算:中文按字计,英文按 4 字符计
- 学情压缩:只保留进度、最低掌握度 TOP5、最近错题 TOP5、待复习数量、面试摘要,
  以及跨会话情景记忆(带日期与会话来源)与语义偏好
- 大纲筛选:按提问关键词挑相关段落,超预算时回退到前若干段
- 检索整理:片段去重并按 [S1]..[Sn] 编号,超预算截断
- 历史裁剪:去掉相邻重复消息,按 token 预算从旧到新丢弃
"""
import json
import re

from app.core.config import settings
from app.services.prompt_guard import UNTRUSTED_NOTICE, sanitize_untrusted

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_WORD_RE = re.compile(r"[a-zA-Z0-9_]{2,}")


def budget(name: str, default: int) -> int:
    """读取上下文预算;关闭开关时返回近似无限,便于回退旧行为"""
    if not getattr(settings, "CONTEXT_BUDGET_ENABLED", True):
        return 10 ** 9
    return int(getattr(settings, name, default))


def estimate_tokens(text: str) -> int:
    """轻量 token 估算:不引入分词依赖,用于预算控制与评估"""
    if not text:
        return 0
    cjk = len(_CJK_RE.findall(text))
    return cjk + max(1, (len(text) - cjk) // 4)


def trim_text(text: str, max_chars: int, keep_tail: bool = False) -> str:
    """按字符预算截断;keep_tail 保留结尾(错误堆栈等场景)"""
    value = str(text or "")
    if max_chars <= 0 or len(value) <= max_chars:
        return value
    if keep_tail:
        return "..." + value[-(max_chars - 3):]
    return value[: max(0, max_chars - 3)] + "..."


def _query_terms(query: str) -> set[str]:
    """检索关键词:中文双字组合 + 英文/数字词"""
    text = (query or "").strip()
    terms = {word.lower() for word in _WORD_RE.findall(text)}
    chinese = "".join(_CJK_RE.findall(text))
    terms.update(chinese[i:i + 2] for i in range(max(0, len(chinese) - 1)))
    return {term for term in terms if term}


def select_relevant(text: str, query: str, max_chars: int) -> str:
    """按与问题的相关度挑选段落,拼回时保持原文顺序"""
    value = str(text or "")
    if not value or max_chars <= 0 or len(value) <= max_chars:
        return value

    paragraphs = [p.strip() for p in re.split(r"\n{2,}", value) if p.strip()]
    if len(paragraphs) <= 1:
        paragraphs = [line.strip() for line in value.splitlines() if line.strip()]
    if len(paragraphs) <= 1:
        return trim_text(value, max_chars)

    terms = _query_terms(query)
    scored = [
        (sum(1 for term in terms if term in paragraph), index, paragraph)
        for index, paragraph in enumerate(paragraphs)
    ]
    scored.sort(key=lambda item: (-item[0], item[1]))

    kept: list[tuple[int, str]] = []
    used = 0
    for score, index, paragraph in scored:
        if used and used + len(paragraph) + 1 > max_chars:
            continue
        kept.append((index, paragraph))
        used += len(paragraph) + 1
    if not kept:
        return trim_text(value, max_chars)
    kept.sort()
    return trim_text("\n".join(paragraph for _, paragraph in kept), max_chars)


def _episodic_line(memo) -> str:
    """情景记忆压成一行:日期 + 来源会话 + 摘要,便于回答说明来自哪次会话"""
    if not isinstance(memo, dict):
        return ""
    summary = str(memo.get("summary") or memo.get("content") or "").strip()
    if not summary:
        return ""
    day = str(memo.get("date") or "").strip()
    source = str(memo.get("session_id") or memo.get("source_id") or "").strip()
    prefix = " ".join(
        part for part in (day, f"会话 {source}" if source else "") if part
    )
    return f"{prefix}:{summary}" if prefix else summary


def compress_profile(profile: dict, max_chars: int | None = None) -> str:
    """压缩学情快照:保留回答真正需要的最弱掌握度与最近错题"""
    limit = max_chars if max_chars is not None else budget("CONTEXT_PROFILE_CHARS", 900)
    if not profile:
        return "(暂无学情数据)"

    compact: dict = {}
    if profile.get("overall_progress") is not None:
        compact["overall_progress"] = profile["overall_progress"]

    mastery = profile.get("mastery") or []
    if isinstance(mastery, list) and mastery:
        ordered = sorted(
            (item for item in mastery if isinstance(item, dict)),
            key=lambda item: item.get("level", 0),
        )
        compact["weak_mastery"] = ordered[:5]

    wrong = profile.get("recent_wrong") or []
    if isinstance(wrong, list) and wrong:
        compact["recent_wrong"] = wrong[:5]

    reviews = profile.get("pending_reviews") or []
    if reviews:
        compact["pending_reviews"] = len(reviews)

    if profile.get("interview"):
        compact["interview"] = profile["interview"]

    # 跨会话情景记忆:压成「日期 会话 xxx:薄弱点」短句,便于回答引用来源会话
    episodic = profile.get("episodic_memories") or []
    if isinstance(episodic, list) and episodic:
        turns = [
            line for line in (_episodic_line(memo) for memo in episodic[:5]) if line
        ]
        if turns:
            compact["history"] = turns

    semantic = profile.get("semantic_memories") or []
    if isinstance(semantic, list) and semantic:
        preferences = []
        for memo in semantic[:3]:
            if not isinstance(memo, dict):
                continue
            text = str(memo.get("summary") or memo.get("content") or "").strip()
            if text:
                preferences.append(text[:120])
        if preferences:
            compact["preferences"] = preferences

    if not compact:
        # 结构未知时保底输出,但仍受预算约束
        return trim_text(json.dumps(profile, ensure_ascii=False), limit)
    return trim_text(
        json.dumps(compact, ensure_ascii=False, separators=(",", ":")), limit,
    )


def build_rag_context(
    evidence: dict,
    query: str = "",
    max_chars: int | None = None,
    max_fragments: int | None = None,
) -> tuple[str, list[dict]]:
    """把检索结果整理为带引用编号的上下文

    返回 (上下文文本, 去重后的片段列表)。没有结构化片段时回退到拼接文本。
    """
    limit = max_chars if max_chars is not None else budget("CONTEXT_RAG_CHARS", 2400)
    frag_limit = (
        max_fragments if max_fragments is not None
        else budget("CONTEXT_MAX_FRAGMENTS", 4)
    )
    fragments = (evidence or {}).get("fragments") or []

    items: list[dict] = []
    seen: set[tuple] = set()
    for fragment in fragments:
        if not isinstance(fragment, dict):
            continue
        text = str(fragment.get("text") or fragment.get("content") or "").strip()
        if not text:
            continue
        key = (fragment.get("material_id"), fragment.get("page"), text[:120])
        if key in seen:
            continue
        seen.add(key)
        items.append({
            "source": str(fragment.get("source") or "课程资料"),
            "page": fragment.get("page"),
            "material_id": fragment.get("material_id"),
            "text": trim_text(text, 500),
        })
        if len(items) >= frag_limit:
            break

    if not items:
        legacy, _ = sanitize_untrusted(
            trim_text((evidence or {}).get("context", "") or "", limit),
        )
        return legacy, []

    lines = []
    for index, item in enumerate(items, 1):
        page = f" 第 {item['page']} 页" if item.get("page") else ""
        # 检索片段来自用户上传资料:按不可信数据处理,命中高危指令就地中和
        safe_text, _ = sanitize_untrusted(item["text"])
        lines.append(f"[S{index}] 《{item['source']}》{page}\n{safe_text}")
    body = "\n\n".join(lines)
    # 预算允许时补一句不可信声明;空间不足则跳过,避免挤掉正文
    if limit <= 0 or len(body) + len(UNTRUSTED_NOTICE) + 2 <= limit:
        body = f"{body}\n\n{UNTRUSTED_NOTICE}"
    return trim_text(body, limit), items


def build_history(
    messages: list[dict], limit: int = 6, max_tokens: int | None = None,
) -> list[dict]:
    """裁剪对话历史:去掉相邻重复,保留最近 N 条,再按 token 预算从旧到新丢弃"""
    token_limit = (
        max_tokens if max_tokens is not None
        else budget("CONTEXT_HISTORY_TOKENS", 900)
    )
    cleaned: list[dict] = []
    for message in messages or []:
        role = message.get("role", "user")
        content = str(message.get("content") or "").strip()
        if not content:
            continue
        if cleaned and cleaned[-1]["role"] == role and cleaned[-1]["content"] == content:
            continue
        cleaned.append({"role": role, "content": trim_text(content, 1200)})

    cleaned = cleaned[-max(1, limit):]
    while len(cleaned) > 1 and (
        sum(estimate_tokens(item["content"]) for item in cleaned) > token_limit
    ):
        cleaned.pop(0)
    return cleaned
