"""Agent 运行时直接调用数据 API(不再依赖 prepare 预加载快照)"""
import asyncio
import json
from datetime import datetime
from types import SimpleNamespace

import app.agent.data_api as data_api
import app.agent.internal_api as internal_api
from app.agent.nodes import collab as collab_module
from app.agent.nodes import interview as interview_module
from app.agent.nodes import review as review_module
from app.agent.nodes import teacher as teacher_module
from app.agent.nodes import tutor as tutor_module
from app.agent.tools import TOOL_REGISTRY


def _state(**overrides):
    state = {
        "messages": [{"role": "user", "content": "解释二叉树的遍历"}],
        "session_id": "data-api-test",
        "user_id": 1,
        "user_role": "student",
        "admin_level": None,
        "user_name": "学生",
        "course_id": 10,
        "intent": "chat",
        "branch": "tutor",
        "task_plan": [],
        "current_step": 0,
        "collaborate": False,
        "collab_plan": [],
        "collab_results": [],
        "tool_calls": [],
        "tool_results": {},
        # 旧快照故意放入哨兵值,节点不应再读取
        "rag_context": "SNAPSHOT-RAG",
        "profile_snapshot": {"mastery": [{"point": "SNAPSHOT-PROFILE", "level": 0.1}]},
        "profile_updates": {},
        "risk_flag": False,
        "risk_type": "",
        "reflection_passed": False,
        "reflection_notes": "",
        "reflection_count": 0,
        "final_output": "",
        "stream_queue": None,
    }
    state.update(overrides)
    return state


def test_tutor_uses_tools_instead_of_snapshot(monkeypatch):
    """P0-2:tutor 不再预取快照,检索改由 course_evidence 工具按需完成"""
    captured = {}

    monkeypatch.setitem(
        TOOL_REGISTRY, "course_evidence",
        lambda **kw: {"context": "DIRECT-RAG", "fragments": []},
    )

    async def fake_llm(messages, sink=None, tools=None):
        captured["system"] = messages[0]["content"]
        captured["tools"] = [tool["name"] for tool in (tools or [])]
        return "指导回答"

    monkeypatch.setattr(tutor_module, "llm_invoke", fake_llm)
    result = asyncio.run(tutor_module.tutor_node(_state()))

    system = captured["system"]
    # 旧快照哨兵不再进入提示词
    assert "SNAPSHOT-PROFILE" not in system
    assert "SNAPSHOT-RAG" not in system
    # 课程事实题保底检索由工具完成,结果进入来源
    assert "course_evidence" in captured["tools"]
    assert "profile_query" in captured["tools"]
    assert result["rag_context"] == "DIRECT-RAG"


def test_teacher_uses_direct_data_api(monkeypatch):
    captured = {}
    monkeypatch.setattr(teacher_module, "fetch_syllabus", lambda *a, **k: "DIRECT-SYLLABUS")
    monkeypatch.setattr(
        teacher_module, "fetch_course_evidence",
        lambda *a, **k: {"context": "DIRECT-RAG", "fragments": []},
    )
    monkeypatch.setattr(teacher_module, "fetch_class_stats",
                        lambda *a, **k: {"weak_points": ["DIRECT-STATS"]})

    async def fake_llm(messages, sink=None):
        captured["system"] = messages[0]["content"]
        return "备课框架"

    monkeypatch.setattr(teacher_module, "llm_invoke", fake_llm)
    state = _state(
        user_role="teacher",
        branch="teacher",
        messages=[{"role": "user", "content": "根据班级学情设计教学框架"}],
    )
    result = asyncio.run(teacher_module.teacher_node(state))

    system = captured["system"]
    assert "DIRECT-SYLLABUS" in system
    assert "DIRECT-RAG" in system
    assert "DIRECT-STATS" in system
    assert "SNAPSHOT-RAG" not in system
    assert result["rag_context"] == "DIRECT-RAG"


def test_review_and_interview_use_direct_profile(monkeypatch):
    monkeypatch.setattr(review_module, "fetch_profile",
                        lambda *a, **k: {"mastery": [{"point": "DIRECT-PROFILE", "level": 0.5}]})
    monkeypatch.setattr(
        review_module, "fetch_course_evidence",
        lambda *a, **k: {"context": "DIRECT-RAG", "fragments": []},
    )
    monkeypatch.setattr(interview_module, "fetch_profile",
                        lambda *a, **k: {"mastery": [{"point": "DIRECT-PROFILE", "level": 0.5}]})
    monkeypatch.setattr(
        interview_module, "fetch_course_evidence",
        lambda *a, **k: {"context": "DIRECT-RAG", "fragments": []},
    )

    captured = {}

    async def fake_review_llm(messages, temperature=None, sink=None):
        captured["review"] = messages[0]["content"]
        return json.dumps({
            "error_analysis": {"kp_name": "二叉树", "error_type": "概念不清", "explanation": "边界遗漏"},
            "mastery_update": {"delta": -10},
            "review_plan": {"next_review_at": "2026-11-01"},
            "variant_question": {"question": "变式题", "hint": "先画图"},
        })

    async def fake_interview_llm(messages, sink=None):
        captured["interview"] = messages[0]["content"]
        return "面试点评"

    monkeypatch.setattr(review_module, "llm_invoke", fake_review_llm)
    monkeypatch.setattr(interview_module, "llm_invoke", fake_interview_llm)

    asyncio.run(review_module.review_node(_state(branch="review")))
    asyncio.run(interview_module.interview_node(_state(branch="interview")))

    assert "DIRECT-PROFILE" in captured["review"]
    assert "SNAPSHOT-PROFILE" not in captured["review"]
    assert "DIRECT-RAG" in captured["interview"]
    assert "DIRECT-PROFILE" in captured["interview"]
    assert "SNAPSHOT-PROFILE" not in captured["interview"]


def test_collab_expert_uses_direct_data_api(monkeypatch):
    monkeypatch.setattr(collab_module, "fetch_profile",
                        lambda *a, **k: {"mastery": [{"point": "DIRECT-PROFILE", "level": 0.4}]})
    monkeypatch.setattr(collab_module, "fetch_course_context", lambda *a, **k: "DIRECT-RAG")
    monkeypatch.setattr(collab_module, "fetch_syllabus", lambda *a, **k: "DIRECT-SYLLABUS")

    persona = collab_module._render_expert_persona("tutor", _state(), "解释遍历")
    assert "DIRECT-PROFILE" in persona
    assert "DIRECT-RAG" in persona
    assert "SNAPSHOT-PROFILE" not in persona

    teacher_persona = collab_module._render_expert_persona(
        "teacher", _state(user_role="teacher"), "设计课程",
    )
    assert "DIRECT-SYLLABUS" in teacher_persona
    assert "SNAPSHOT-PROFILE" not in teacher_persona


def test_data_api_degrades_on_failure(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("数据源不可用")

    monkeypatch.setattr(internal_api, "fetch_profile_via_api", boom)
    monkeypatch.setattr(internal_api, "fetch_course_context_via_api", boom)
    monkeypatch.setattr(internal_api, "fetch_class_stats_via_api", boom)

    assert data_api.fetch_profile(1, 10) == {}
    assert data_api.fetch_course_context("q", 10, 1) == ""
    assert data_api.fetch_class_stats(10, 1) == {}


class _FakeQuery:
    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return SimpleNamespace(id=1, role="student")


class _FakeSession:
    def query(self, *args, **kwargs):
        return _FakeQuery()

    def close(self):
        pass


def test_internal_api_reuses_student_route_functions(monkeypatch):
    from app.api import student as student_api

    monkeypatch.setattr(internal_api, "SessionLocal", lambda: _FakeSession())
    monkeypatch.setattr(
        student_api, "get_progress_by_path",
        lambda course_id, user, db: SimpleNamespace(
            overall_progress=42.0,
            mastery=[SimpleNamespace(kp_name="二叉树", mastery_level=30)],
        ),
    )
    monkeypatch.setattr(
        student_api, "list_wrong_questions",
        lambda **kwargs: [SimpleNamespace(question_content="错题内容", error_type="概念不清")],
    )
    monkeypatch.setattr(
        student_api, "list_review_plans",
        lambda **kwargs: [
            SimpleNamespace(wrong_question_id=9, next_review_at=datetime(2026, 11, 1)),
        ],
    )
    monkeypatch.setattr(
        student_api, "list_interview_records",
        lambda **kwargs: [SimpleNamespace(score=80, feedback="表达清晰")],
    )

    snapshot = internal_api.fetch_profile_via_api(1, 10, "student")

    assert snapshot["overall_progress"] == 42.0
    assert snapshot["mastery"][0] == {"point": "二叉树", "level": 0.3}
    assert snapshot["recent_wrong"][0]["error_type"] == "概念不清"
    assert snapshot["pending_reviews"][0]["next_review_at"] == "2026-11-01"
    assert snapshot["interview"]["latest_score"] == 80


def test_internal_api_reuses_course_search_endpoint(monkeypatch):
    from app.api import course as course_api

    monkeypatch.setattr(internal_api, "SessionLocal", lambda: _FakeSession())
    captured = {}

    def fake_search(course_id, q, top_k, user, db):
        captured.update(course_id=course_id, q=q, top_k=top_k)
        return {"context": "检索上下文", "fragments": []}

    monkeypatch.setattr(course_api, "search_course_materials", fake_search)

    context = internal_api.fetch_course_context_via_api("二叉树", 10, 1, "student", 3)

    assert context == "检索上下文"
    assert captured == {"course_id": 10, "q": "二叉树", "top_k": 3}


def test_internal_api_reuses_class_route_functions(monkeypatch):
    from app.api import classroom as class_api

    monkeypatch.setattr(internal_api, "SessionLocal", lambda: _FakeSession())
    monkeypatch.setattr(
        class_api, "list_classes",
        lambda user, db: [SimpleNamespace(id=5, course_id=10)],
    )
    monkeypatch.setattr(
        class_api, "get_class_report",
        lambda class_id, user, db: SimpleNamespace(
            model_dump=lambda: {"class_id": class_id, "weak_points": []},
        ),
    )

    stats = internal_api.fetch_class_stats_via_api(10, 1, "teacher")

    assert stats["class_id"] == 5
