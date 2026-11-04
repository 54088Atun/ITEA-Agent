"""Agent 步骤 span:逐节点记录参数、结果、token 与耗时

埋点在对话编排层(api/chat.py)完成,不侵入图节点与 AgentState。
与运行记录一致:独立会话写入,失败只告警,绝不打断主链路。
"""
import json
import logging
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.log import AgentRunSpan

logger = logging.getLogger(__name__)

MAX_TEXT = 2000


def _dump(value: Any, limit: int = MAX_TEXT) -> Optional[str]:
    """把入参/结果序列化为可读文本,超长截断"""
    if value is None:
        return None
    if isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(value, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            text = str(value)
    return text if len(text) <= limit else text[:limit] + "..."


def write_span(
    run_id: Optional[int],
    seq: int,
    kind: str,
    name: str,
    *,
    status: str = "ok",
    payload: Any = None,
    result: Any = None,
    tokens: Optional[int] = None,
    duration_ms: Optional[int] = None,
    error: Optional[str] = None,
) -> None:
    """写入一条 span;失败只告警,不影响对话"""
    if not run_id:
        return
    db = SessionLocal()
    try:
        db.add(AgentRunSpan(
            run_id=run_id,
            seq=seq,
            kind=(kind or "")[:20],
            name=(name or "")[:60],
            status=(status or "ok")[:20],
            payload=_dump(payload),
            result=_dump(result),
            tokens=tokens,
            duration_ms=duration_ms,
            error=_dump(error, 500) if error else None,
        ))
        db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.warning("Agent span 写入失败: %s", exc)
    finally:
        db.close()


def list_spans(db: Session, run_id: int) -> list[dict]:
    """按步骤顺序返回一次运行的全部 span,用于失败回放"""
    rows = (
        db.query(AgentRunSpan)
        .filter(AgentRunSpan.run_id == run_id)
        .order_by(AgentRunSpan.seq.asc(), AgentRunSpan.id.asc())
        .all()
    )
    return [
        {
            "id": span.id,
            "seq": span.seq,
            "kind": span.kind,
            "name": span.name,
            "status": span.status,
            "payload": span.payload,
            "result": span.result,
            "tokens": span.tokens,
            "duration_ms": span.duration_ms,
            "error": span.error,
            "created_at": span.created_at,
        }
        for span in rows
    ]
