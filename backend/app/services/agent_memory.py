"""Agent 三层记忆服务(P1-1)

- 工作记忆:由 LangGraph state 承担,不落本表
- 情景记忆(episodic):一次会话的结论与薄弱点,带 session_id / run_id 来源
- 语义记忆(semantic):用户与课程偏好,长期有效

写入统一过 prompt_guard(不可信输入防护);检索优先向量,embedding 不可用时
降级为关键词 + 重要度/时间窗口,保证无模型环境(测试)也能工作。
"""
import logging
import re
from datetime import datetime, timedelta

from sqlalchemy import or_, select

from app.db.session import SessionLocal
from app.models.agent_memory import AgentMemory
from app.services.prompt_guard import scan_untrusted

logger = logging.getLogger(__name__)

VALID_TYPES = ("episodic", "semantic")
MIN_TTL_DAYS = 1
MAX_TTL_DAYS = 365
MAX_CONTENT_CHARS = 2000
MAX_SUMMARY_CHARS = 300
DEFAULT_RECALL_DAYS = 14
# 向量检索只对候选集重排,避免全表加载
MAX_VECTOR_CANDIDATES = 50


def _clean(text, limit: int) -> str:
    """记忆内容按不可信数据处理:命中指令覆盖等高危项则放弃"""
    scanned = scan_untrusted(str(text or ""))
    if scanned["blocked"]:
        logger.warning("记忆写入被拦截(labels=%s)", ",".join(scanned["labels"]))
        return ""
    return scanned["sanitized"].strip()[:limit]


def _expiry(ttl_days: int | None) -> datetime | None:
    """TTL 校验(1-365 天)并换算过期时间"""
    if ttl_days is None:
        return None
    try:
        days = int(ttl_days)
    except (TypeError, ValueError):
        raise ValueError("ttl_days 必须是整数")
    if days < MIN_TTL_DAYS or days > MAX_TTL_DAYS:
        raise ValueError(f"ttl_days 需在 {MIN_TTL_DAYS}-{MAX_TTL_DAYS} 之间")
    return datetime.utcnow() + timedelta(days=days)


def write_memory(
    user_id: int,
    course_id: int | None,
    memory_type: str,
    content: str,
    source_type: str = "conversation",
    source_id: str | None = None,
    session_id: str | None = None,
    run_id: int | None = None,
    summary: str | None = None,
    ttl_days: int | None = None,
    importance: int = 1,
) -> int | None:
    """写入一条记忆,返回新记忆 id;内容被拦截时返回 None

    来源(source_type/source_id/session_id/run_id)必须由调用方提供,
    用于回答「这条记忆来自哪次会话」。
    """
    kind = memory_type if memory_type in VALID_TYPES else "semantic"
    safe_content = _clean(content, MAX_CONTENT_CHARS)
    if not safe_content:
        return None
    safe_summary = _clean(summary, MAX_SUMMARY_CHARS) or safe_content[:120]
    expires_at = _expiry(ttl_days)
    level = max(1, min(5, int(importance or 1)))

    db = SessionLocal()
    try:
        row = AgentMemory(
            user_id=user_id,
            course_id=course_id,
            memory_type=kind,
            content=safe_content,
            source_type=(str(source_type or "conversation"))[:30],
            source_id=(str(source_id or "")[:100] or None) if source_id is not None else None,
            session_id=(str(session_id or "")[:64] or None) if session_id is not None else None,
            run_id=run_id,
            summary=safe_summary,
            importance=level,
            expires_at=expires_at,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        logger.info(
            "记忆已写入(type=%s, user=%s, course=%s, session=%s, id=%s)",
            kind, user_id, course_id, session_id, row.id,
        )
        return row.id
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.error("记忆写入失败(user=%s): %s", user_id, exc)
        return None
    finally:
        db.close()


# ---------- 读 ----------

def _base_filters(user_id: int, course_id: int | None, memory_type: str | None):
    """有效记忆过滤:未删除、未过期,课程维度包含用户级(course_id 为空)记忆"""
    conditions = [
        AgentMemory.user_id == user_id,
        AgentMemory.deleted_at.is_(None),
        or_(AgentMemory.expires_at.is_(None), AgentMemory.expires_at > datetime.utcnow()),
    ]
    if course_id is not None:
        conditions.append(
            or_(AgentMemory.course_id == course_id, AgentMemory.course_id.is_(None))
        )
    if memory_type:
        conditions.append(AgentMemory.memory_type == memory_type)
    return conditions


def _memory_dict(row: AgentMemory) -> dict:
    created = row.created_at
    return {
        "id": row.id,
        "memory_type": row.memory_type,
        "summary": row.summary or (row.content or "")[:120],
        "content": row.content,
        "source_type": row.source_type,
        "source_id": row.source_id,
        "session_id": row.session_id,
        "run_id": row.run_id,
        "importance": row.importance or 1,
        "created_at": created,
        "date": created.strftime("%Y-%m-%d") if created else "",
    }


def _vector_order(query: str, rows: list[AgentMemory]) -> list[AgentMemory]:
    """向量相似度重排;embedding 不可用时抛异常由调用方降级"""
    import numpy as np

    from app.agent.tools.rag_search import get_manager

    model = get_manager().embedding_model  # 无模型环境会 raise
    texts = [row.summary or row.content or "" for row in rows]
    vectors = np.array(
        model.encode([query] + texts, normalize_embeddings=True), dtype="float32",
    )
    scores = vectors[1:] @ vectors[0]
    order = scores.argsort()[::-1]
    return [rows[i] for i in order]


def _keyword_order(query: str, rows: list[AgentMemory]) -> list[AgentMemory]:
    """关键词命中数重排(中文按二元切分),全不命中时保持原顺序"""
    terms = [t for t in re.split(r"[\s,，。;；、]+", query or "") if len(t) >= 1]
    if not terms:
        return rows

    def score(row: AgentMemory) -> int:
        text = f"{row.summary or ''}{row.content or ''}"
        return sum(text.count(term) for term in terms)

    scored = [(score(row), idx, row) for idx, row in enumerate(rows)]
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [item[2] for item in scored]


def search_memory(
    user_id: int,
    course_id: int | None,
    query: str,
    memory_type: str | None = None,
    days: int | None = None,
    limit: int = 5,
) -> list[dict]:
    """检索记忆:向量优先,失败降级关键词;按重要度/时间兜底"""
    limit = max(1, int(limit or 5))
    conditions = _base_filters(user_id, course_id, memory_type)
    if days:
        conditions.append(AgentMemory.created_at >= datetime.utcnow() - timedelta(days=int(days)))

    db = SessionLocal()
    try:
        rows = db.execute(
            select(AgentMemory)
            .where(*conditions)
            .order_by(AgentMemory.importance.desc(), AgentMemory.updated_at.desc())
            .limit(MAX_VECTOR_CANDIDATES)
        ).scalars().all()
        if not rows:
            return []

        if query:
            try:
                rows = _vector_order(query, list(rows))
            except Exception as exc:  # noqa: BLE001
                logger.warning("记忆向量检索降级为关键词(user=%s): %s", user_id, exc)
                rows = _keyword_order(query, list(rows))
        return [_memory_dict(row) for row in rows[:limit]]
    except Exception as exc:  # noqa: BLE001
        logger.warning("记忆检索失败(user=%s): %s", user_id, exc)
        return []
    finally:
        db.close()


def list_recent_episodic(
    user_id: int,
    course_id: int | None = None,
    days: int = DEFAULT_RECALL_DAYS,
    limit: int = 5,
) -> list[dict]:
    """最近的跨会话情景记忆(带来源会话),供新会话引用历史薄弱点"""
    limit = max(1, int(limit or 5))
    since = datetime.utcnow() - timedelta(days=max(1, int(days or DEFAULT_RECALL_DAYS)))
    conditions = _base_filters(user_id, course_id, "episodic")
    conditions.append(AgentMemory.created_at >= since)

    db = SessionLocal()
    try:
        rows = db.execute(
            select(AgentMemory)
            .where(*conditions)
            .order_by(AgentMemory.importance.desc(), AgentMemory.created_at.desc())
            .limit(limit)
        ).scalars().all()
        return [_memory_dict(row) for row in rows]
    except Exception as exc:  # noqa: BLE001
        logger.warning("情景记忆读取失败(user=%s): %s", user_id, exc)
        return []
    finally:
        db.close()
