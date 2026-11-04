"""P1-2 上下文工程:预算、压缩、去重、引用编号与历史裁剪"""
import json

from app.agent import context
from app.agent.sources import build_sources


def _large_profile():
    return {
        "overall_progress": 62.5,
        "mastery": [
            {"point": f"知识点{i}", "level": round(0.1 + i * 0.02, 2)}
            for i in range(40)
        ],
        "recent_wrong": [
            {"question": f"错题{i}：这是一道很长的题目描述，用于占用上下文预算",
             "error_type": "概念不清"}
            for i in range(20)
        ],
        "pending_reviews": [
            {"wrong_question_id": i, "next_review_at": "2026-11-01"}
            for i in range(12)
        ],
        "interview": {"total_sessions": 3, "latest_score": 72, "latest_weakness": "表达不清晰"},
    }


def _fragments():
    items = [
        {"source": f"课件{i}.pdf", "material_id": i, "page": i,
         "text": "测试知识片段" * 40}
        for i in range(1, 6)
    ]
    items.append(dict(items[0]))
    return items


def test_compress_profile_keeps_weakest_and_drops_bulk():
    compressed = context.compress_profile(_large_profile(), max_chars=900)
    data = json.loads(compressed)

    assert len(data["weak_mastery"]) == 5
    assert data["weak_mastery"][0]["level"] <= data["weak_mastery"][-1]["level"]
    assert len(data["recent_wrong"]) == 5
    assert data["pending_reviews"] == 12
    assert data["interview"]["latest_score"] == 72
    assert len(compressed) <= 900


def test_rag_context_dedupes_and_numbers_sources():
    evidence = {"fragments": _fragments(), "context": "legacy context"}
    text, items = context.build_rag_context(
        evidence, "测试", max_chars=2400, max_fragments=4,
    )

    assert len(items) == 4
    assert text.startswith("[S1]")
    assert "[S4]" in text
    assert "[S5]" not in text


def test_history_dedupes_adjacent_and_respects_budget():
    messages = [{"role": "user", "content": "重复消息"}] * 3
    messages += [
        {"role": "assistant", "content": f"回答{i}：" + "内容" * 20}
        for i in range(6)
    ]
    trimmed = context.build_history(messages, limit=10, max_tokens=120)

    assert len(trimmed) < len(messages)
    assert sum(1 for item in trimmed if item["content"] == "重复消息") <= 1
    assert sum(context.estimate_tokens(item["content"]) for item in trimmed) <= 120


def test_context_budget_reduces_prompt_tokens_by_30_percent():
    profile = _large_profile()
    syllabus = "\n\n".join(
        f"第{i}章 教学大纲：本章讲解测试方法、用例设计与缺陷管理。" * 6
        for i in range(1, 31)
    )
    evidence = {"fragments": _fragments(), "context": "课程原文" * 3000}
    query = "等价类划分和边界值分析有什么区别"
    messages = [
        {"role": "user", "content": f"历史问题{i}：" + "背景" * 30}
        for i in range(20)
    ]

    before = context.estimate_tokens(
        json.dumps(profile, ensure_ascii=False, indent=2)
        + syllabus + evidence["context"]
        + "".join(item["content"] for item in messages)
    )
    after = context.estimate_tokens(
        context.compress_profile(profile)
        + context.select_relevant(syllabus, query, 1200)
        + context.build_rag_context(evidence, query)[0]
        + "".join(
            item["content"] for item in context.build_history(messages, limit=6)
        )
    )

    assert before > 0
    assert after <= before * 0.7, f"token 未下降 30%: before={before}, after={after}"


def test_sources_stay_complete_after_compression():
    sources = build_sources("课程原文" * 10, fragments=_fragments(), course_id=10)
    course_sources = [item for item in sources if item["type"] == "course"]

    assert len(course_sources) == 5
    assert all(item.get("url") for item in course_sources)


def test_budget_switch_disables_truncation(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "CONTEXT_BUDGET_ENABLED", False)
    long_text = "长" * 5000

    limit = context.budget("CONTEXT_RAG_CHARS", 2400)
    assert context.trim_text(long_text, limit) == long_text
