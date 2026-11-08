"""Agent 运行时直接调用数据 API(不再依赖 prepare 预加载快照)"""
import asyncio
import json
from datetime import datetime
from types import SimpleNamespace

import pytest

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


def test_teacher_uses_tool_loop(monkeypatch):
    """A-05:teacher 与 tutor 一致,取数交给模型按需调用工具,不再靠关键词分支"""
    captured = {}
    monkeypatch.setattr(teacher_module, "fetch_syllabus", lambda *a, **k: "DIRECT-SYLLABUS")

    async def fake_llm(messages, sink=None, tools=None):
        captured["system"] = messages[0]["content"]
        captured["tools"] = [tool["name"] for tool in (tools or [])]
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
    assert "SNAPSHOT-RAG" not in system
    # 检索、统计、SQL、导出工具全部暴露,由模型决定是否调用
    assert {
        "course_evidence", "stats_analyzer", "sql_query", "doc_generator",
    } <= set(captured["tools"])
    assert result["rag_context"] == ""


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


@pytest.mark.parametrize("mastery,kp_name,delta,expected", [
    ([{"point": "二叉树", "level": 0.8}], "二叉树", -10, 0.7),
    ([{"point": "二叉树", "level": 0.1}], "二叉树", -20, 0.0),
    ([{"point": "二叉树", "level": 0.95}], "二叉树", 10, 1.0),
    ([{"point": "二叉树遍历", "level": 0.7}], "二叉树", -10, 0.6),
    ([{"point": "其他知识点", "level": 0.9}], "二叉树", -10, 0.4),
    ([], "二叉树", 0, 0.5),
])
def test_review_mastery_uses_real_baseline(monkeypatch, mastery, kp_name, delta, expected):
    """掌握度以学情基线计算,仅无历史记录时从 0.5 起算"""
    monkeypatch.setattr(review_module, "fetch_profile",
                        lambda *a, **k: {"mastery": mastery})
    monkeypatch.setattr(
        review_module, "fetch_course_evidence",
        lambda *a, **k: {"context": "", "fragments": []},
    )

    async def fake_llm(messages, temperature=None, sink=None):
        return json.dumps({
            "error_analysis": {"kp_name": kp_name, "error_type": "概念不清", "explanation": ""},
            "mastery_update": {"delta": delta},
            "review_plan": {"next_review_at": "2026-11-01"},
            "variant_question": {},
        })

    monkeypatch.setattr(review_module, "llm_invoke", fake_llm)
    result = asyncio.run(review_module.review_node(
        _state(branch="review", review_submit=True),
    ))

    assert result["profile_updates"]["mastery_updates"][0]["mastery_level"] == pytest.approx(expected)


def test_review_query_does_not_record_wrong_question(monkeypatch):
    """A-08:未显式提交错题时只做诊断,不得把用户提问写进学情"""
    monkeypatch.setattr(review_module, "fetch_profile", lambda *a, **k: {"mastery": []})
    monkeypatch.setattr(
        review_module, "fetch_course_evidence",
        lambda *a, **k: {"context": "", "fragments": []},
    )

    async def fake_llm(messages, temperature=None, sink=None):
        return "你目前的薄弱点是递归,建议先复习基础概念。"

    monkeypatch.setattr(review_module, "llm_invoke", fake_llm)
    result = asyncio.run(review_module.review_node(_state(branch="review")))

    assert result["profile_updates"] == {}
    assert "[AI 辅助参考" in result["final_output"]


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


def test_tutor_prompt_consumes_task_plan(monkeypatch):
    """A-03:计划必须进入业务提示词,不能只用于展示"""
    captured = {}
    monkeypatch.setitem(
        TOOL_REGISTRY, "course_evidence",
        lambda **kw: {"context": "", "fragments": []},
    )

    async def fake_llm(messages, sink=None, tools=None):
        captured["system"] = messages[0]["content"]
        return "回答"

    monkeypatch.setattr(tutor_module, "llm_invoke", fake_llm)
    state = _state(task_plan=[{
        "step": 1, "title": "先检索课程资料", "tool": "course_evidence",
    }])
    asyncio.run(tutor_module.tutor_node(state))

    assert "执行计划" in captured["system"]
    assert "先检索课程资料" in captured["system"]


def test_fetch_profile_merges_recalled_memories(monkeypatch):
    """A-06:学情读取必须并入跨会话情景记忆与语义偏好"""
    from app.services import agent_memory as mem_svc

    monkeypatch.setattr(
        internal_api, "fetch_profile_via_api",
        lambda *a, **k: {"overall_progress": 50.0},
    )
    monkeypatch.setattr(
        mem_svc, "list_recent_episodic",
        lambda *a, **k: [{"summary": "上次复习二叉树", "date": "2026-11-01"}],
    )
    monkeypatch.setattr(
        mem_svc, "search_memory",
        lambda *a, **k: [{"summary": "以后都用中文解释"}],
    )

    profile = data_api.fetch_profile(1, 10)

    assert profile["overall_progress"] == 50.0
    assert profile["episodic_memories"][0]["summary"] == "上次复习二叉树"
    assert profile["semantic_memories"][0]["summary"] == "以后都用中文解释"


def test_fetch_profile_skips_memory_without_profile(monkeypatch):
    """没有学情档案时不额外查记忆库,避免教师等角色产生无效查询"""
    from app.services import agent_memory as mem_svc

    recalled = []
    monkeypatch.setattr(internal_api, "fetch_profile_via_api", lambda *a, **k: {})
    monkeypatch.setattr(
        mem_svc, "list_recent_episodic",
        lambda *a, **k: recalled.append("episodic") or [],
    )
    monkeypatch.setattr(
        mem_svc, "search_memory",
        lambda *a, **k: recalled.append("semantic") or [],
    )

    assert data_api.fetch_profile(1, 10) == {}
    assert recalled == []


def test_tutor_skips_forced_retrieval_without_course(monkeypatch):
    """A-10:未选课程时不得发起 course_evidence 强制检索(必填 course_id 会失败)"""
    called = []
    monkeypatch.setitem(
        TOOL_REGISTRY, "course_evidence",
        lambda **kw: called.append(kw) or {"context": "", "fragments": []},
    )

    async def fake_llm(messages, sink=None, tools=None):
        return "这是通用知识解释。"

    monkeypatch.setattr(tutor_module, "llm_invoke", fake_llm)
    asyncio.run(tutor_module.tutor_node(_state(course_id=None)))

    assert called == []


def test_tutor_injects_semantic_preferences(monkeypatch):
    """A-06:模型未调用 profile_query 时,长期偏好也要常驻提示词"""
    captured = {}
    monkeypatch.setitem(
        TOOL_REGISTRY, "course_evidence",
        lambda **kw: {"context": "", "fragments": []},
    )
    monkeypatch.setattr(
        tutor_module, "fetch_memories",
        lambda *a, **k: {"semantic_memories": [{"summary": "以后都用中文解释"}]},
    )

    async def fake_llm(messages, sink=None, tools=None):
        captured["system"] = messages[0]["content"]
        return "好的。"

    monkeypatch.setattr(tutor_module, "llm_invoke", fake_llm)
    asyncio.run(tutor_module.tutor_node(_state()))

    assert "以后都用中文解释" in captured["system"]


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


def test_teacher_reads_enrolled_student_profile(monkeypatch):
    """A-11:教师必须显式指定学生,且学生需在该课程中;未指定时不得返回他人数据"""
    from app.api import student as student_api
    import app.services.course_access as course_access

    monkeypatch.setattr(internal_api, "SessionLocal", lambda: _FakeSession())
    monkeypatch.setattr(
        course_access, "can_view_course", lambda user, course, db: True,
    )
    monkeypatch.setattr(
        student_api, "get_progress_by_path",
        lambda *a, **k: SimpleNamespace(overall_progress=66.0, mastery=[]),
    )
    monkeypatch.setattr(student_api, "list_wrong_questions", lambda **k: [])
    monkeypatch.setattr(student_api, "list_review_plans", lambda **k: [])
    monkeypatch.setattr(student_api, "list_interview_records", lambda **k: [])

    assert internal_api.fetch_profile_via_api(2, 10, "teacher") == {}

    snapshot = internal_api.fetch_profile_via_api(2, 10, "teacher", student_id=3)

    assert snapshot["overall_progress"] == 66.0


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
