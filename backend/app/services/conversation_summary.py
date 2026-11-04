"""会话摘要(AG-11):LLM 生成 + 缓存,失败时规则降级"""
import logging
from datetime import datetime

from app.agent.llm import llm_invoke

logger = logging.getLogger(__name__)

MAX_MESSAGES = 40
MAX_CHARS = 6000

SYSTEM_PROMPT = (
    "你是教学对话摘要助手。请用不超过 200 字中文总结以下对话："
    "讨论主题、关键结论、待办事项或仍存在的疑问。"
    "只输出摘要正文，不要标题、不要列表符号。"
)


def build_transcript(messages) -> str:
    lines = []
    for msg in messages[-MAX_MESSAGES:]:
        content = (msg.content or "").strip().replace("\n", " ")
        if not content:
            continue
        role = "学生" if msg.role == "user" else "AI"
        lines.append(f"{role}: {content[:600]}")
    return "\n".join(lines)[:MAX_CHARS]


def fallback_summary(messages) -> str:
    """不依赖模型的可读摘要,保证接口始终有结果"""
    if not messages:
        return "该会话暂无内容。"
    questions = [
        m.content.strip() for m in messages
        if m.role == "user" and (m.content or "").strip()
    ]
    answers = [
        m.content.strip() for m in messages
        if m.role == "assistant" and (m.content or "").strip()
    ]
    first = questions[0][:80] if questions else "（无提问）"
    last = answers[-1][:120].replace("\n", " ") if answers else "（暂无回答）"
    return (
        f"共 {len(messages)} 条消息、{len(questions)} 轮提问。"
        f"首个问题：{first}。最近回答要点：{last}"
    )


async def _llm_summary(transcript: str) -> str:
    return (
        await llm_invoke(
            [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": transcript},
            ],
            temperature=0.2,
        )
    ).strip()


async def summarize_conversation(conv, messages, refresh: bool = False) -> dict:
    """生成或读取摘要;成功后写回 conv 字段,由调用方提交事务"""
    if conv.summary and not refresh:
        return {
            "summary": conv.summary,
            "cached": True,
            "summarized_at": conv.summarized_at,
        }

    transcript = build_transcript(messages)
    summary = ""
    if transcript:
        try:
            summary = await _llm_summary(transcript)
        except Exception as exc:  # noqa: BLE001
            logger.warning("会话摘要生成失败,降级为规则摘要: %s", exc)
    if not summary:
        summary = fallback_summary(messages)

    conv.summary = summary[:2000]
    conv.summarized_at = datetime.utcnow()
    return {
        "summary": conv.summary,
        "cached": False,
        "summarized_at": conv.summarized_at,
    }
