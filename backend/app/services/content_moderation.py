"""上传内容审核(NF-02)

确定性关键词审核:命中即拒绝,避免违规内容进入解析、检索或对话上下文。
- 默认词表内置常见违规类别,可在系统配置 `moderation_keywords`(JSON: 分类→词表)
  中追加;同分类词表合并去重
- 审核开关为 `feature_content_moderation`,关闭后直接放行
- 只记录命中的关键词,不把违规原文写入风控日志
"""
import json
import logging
import re
from typing import Optional

from sqlalchemy.orm import Session

from app.models.log import RiskLog, SystemConfig
from app.services.feature_flags import is_enabled

logger = logging.getLogger(__name__)

DEFAULT_KEYWORDS: dict[str, list[str]] = {
    "violence": ["血腥", "虐杀", "肢解", "凶杀现场"],
    "terror": ["恐怖袭击", "制作炸弹", "自制炸药", "爆炸物制作"],
    "porn": ["色情视频", "裸照", "成人视频", "性交易"],
    "illegal": ["赌博", "毒品交易", "冰毒", "枪支买卖", "代考", "代写论文"],
}

MAX_SCAN_CHARS = 20000
_SEPARATOR = re.compile(r"[\s\-_*·.。,，;；:：!！?？'\"“”‘’()（）\[\]【】/\\|]+")


def moderation_enabled(db: Session) -> bool:
    return is_enabled(db, "feature_content_moderation")


def _normalize(text: str) -> str:
    """去掉空白与常见分隔符并转小写,防止「赌 博」这类简单规避"""
    return _SEPARATOR.sub("", text or "").lower()


def load_keywords(db: Optional[Session] = None) -> dict[str, list[str]]:
    merged = {key: list(words) for key, words in DEFAULT_KEYWORDS.items()}
    if db is None:
        return merged

    row = db.query(SystemConfig).filter(
        SystemConfig.config_key == "moderation_keywords",
    ).first()
    raw = (row.config_value or "").strip() if row else ""
    if not raw:
        return merged
    try:
        extra = json.loads(raw)
    except (TypeError, ValueError):
        logger.warning("审核关键词配置不是合法 JSON，已忽略")
        return merged
    if not isinstance(extra, dict):
        return merged

    for category, words in extra.items():
        if not isinstance(words, list):
            continue
        bucket = merged.setdefault(str(category)[:50], [])
        for word in words:
            term = str(word).strip()
            if term and term not in bucket:
                bucket.append(term)
    return merged


def screen_text(
    text: str, keywords: Optional[dict[str, list[str]]] = None,
) -> dict:
    """纯函数审核:返回 {flagged, categories, hits},不做数据库读写"""
    if not text or not text.strip():
        return {"flagged": False, "categories": [], "hits": []}

    normalized = _normalize(text[:MAX_SCAN_CHARS])
    hits: list[str] = []
    categories: list[str] = []
    for category, words in (keywords or DEFAULT_KEYWORDS).items():
        matched = [word for word in words if word and _normalize(word) in normalized]
        if not matched:
            continue
        categories.append(category)
        hits.extend(matched)
    return {"flagged": bool(hits), "categories": categories, "hits": hits[:20]}


def screen_with_config(db: Session, text: str) -> dict:
    return screen_text(text, load_keywords(db))


def record_rejection(
    db: Session, user_id: int, content: str, result: dict, source: str,
) -> RiskLog:
    """写入风控日志:仅记录命中词与内容长度"""
    detail = f"{source}：命中 {','.join(result.get('hits') or [])}"
    if content:
        detail += f"（内容长度 {len(content)}）"
    row = RiskLog(
        user_id=user_id,
        request_content=detail[:1000],
        risk_type="上传内容违规",
        action_taken="拒绝上传",
    )
    db.add(row)
    return row
