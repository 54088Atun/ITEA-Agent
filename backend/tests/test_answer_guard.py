"""未截止作业/考试答案保护(AS-10,决策 12)

口径:学生命中未截止作业/考试题干或显式索要答案 → risk_guard 拦截转引导;
已提交但未截止仍拦截;截止后放行。
"""
import asyncio
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.agent.nodes import risk_guard as risk_guard_module
from app.agent.nodes import router as router_module
from app.db.session import Base
from app.models.assignment import Assignment, Submission
from app.models.classroom import CourseEnrollment
from app.models.course import Course
from app.models.exam import Exam, ExamQuestion
from app.models.question import Question
from app.models.user import User
from app.services.answer_guard import check_answer_protection

STEM = "请写出二叉树的中序遍历结果，并说明遍历顺序的递归定义"
EXAM_STEM = "快速排序的平均时间复杂度是多少，请说明推导过程"


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    now = datetime.utcnow()
    session.add_all([
        User(id=1, role="student", name="小明", email="s1@example.com",
             password_hash="x", status="active"),
        User(id=2, role="teacher", name="张老师", email="t1@example.com",
             password_hash="x", status="active"),
        User(id=3, role="student", name="小红", email="s2@example.com",
             password_hash="x", status="active"),
        Course(id=10, teacher_id=2, name="数据结构", code="CS101", audit_status="approved"),
        Course(id=11, teacher_id=2, name="算法", code="CS102", audit_status="approved"),
        CourseEnrollment(course_id=10, student_id=1, source="self"),
        CourseEnrollment(course_id=11, student_id=3, source="self"),
        Assignment(id=100, teacher_id=2, course_id=10, title="第一次作业",
                   kind="homework", description=STEM, status="published",
                   due_at=now + timedelta(days=1)),
        Assignment(id=101, teacher_id=2, course_id=10, title="往期作业",
                   kind="homework", description="请证明哈希冲突的链地址法解决方法",
                   status="published", due_at=now - timedelta(hours=1)),
        Exam(id=200, teacher_id=2, course_id=10, title="期中测验",
             status="published", due_at=now + timedelta(days=1)),
        Question(id=300, teacher_id=2, course_id=10, type="short",
                 stem=EXAM_STEM, answer="O(n log n)", status="active"),
        ExamQuestion(exam_id=200, question_id=300, score=10, sort=1),
    ])
    session.commit()
    yield session
    session.close()
    engine.dispose()


def _student(db):
    return db.get(User, 1)


def test_unexpired_assignment_stem_is_blocked(db):
    hit = check_answer_protection(db, _student(db), f"老师这题怎么写：{STEM}")

    assert hit is not None
    assert hit["kind"] == "作业"
    assert hit["id"] == 100
    assert "题干" in hit["reason"]


def test_unexpired_exam_stem_is_blocked(db):
    hit = check_answer_protection(db, _student(db), EXAM_STEM)

    assert hit is not None
    assert hit["kind"] == "考试"
    assert hit["id"] == 200


def test_explicit_answer_request_is_blocked(db):
    hit = check_answer_protection(db, _student(db), "第一次作业的答案是什么")

    assert hit is not None
    assert hit["risk_type"] == "未截止作业答案保护"
    assert "显式索要" in hit["reason"]


def test_expired_assignment_is_allowed(db):
    hit = check_answer_protection(db, _student(db), "请证明哈希冲突的链地址法解决方法")

    assert hit is None


def test_submitted_but_unexpired_is_still_blocked(db):
    db.add(Submission(assignment_id=100, student_id=1, content="我的作答"))
    db.commit()

    hit = check_answer_protection(db, _student(db), STEM)

    assert hit is not None
    assert hit["id"] == 100


def test_teacher_is_not_limited(db):
    assert check_answer_protection(db, db.get(User, 2), STEM) is None


def test_student_without_active_assignment_is_allowed(db):
    assert check_answer_protection(db, db.get(User, 3), "作业答案是什么") is None


def test_course_scope_limits_candidates(db):
    # 学生 1 只看课程 10;指定课程 11 时不再命中课程 10 的作业
    assert check_answer_protection(db, _student(db), STEM, course_id=11) is None
    assert check_answer_protection(db, _student(db), STEM, course_id=10) is not None


def test_router_blocks_before_llm(monkeypatch):
    async def fail_llm(*args, **kwargs):
        raise AssertionError("命中答案保护时不应再调用模型风控")

    monkeypatch.setattr(router_module, "check_answer_request", lambda *a, **k: {
        "risk_type": "未截止作业答案保护", "kind": "作业", "id": 100,
        "title": "第一次作业", "reason": "命中未截止作业题干",
    })
    monkeypatch.setattr(router_module, "llm_invoke", fail_llm)

    result = asyncio.run(router_module.router_node({
        "messages": [{"role": "user", "content": STEM}],
        "user_id": 1, "user_role": "student", "course_id": 10,
        "branch": "", "intent": "",
    }))

    assert result["branch"] == "block"
    assert result["risk_flag"] is True
    assert result["risk_type"] == "未截止作业答案保护"
    assert result["risk_target"] == "作业#100"


def test_forced_branch_is_still_blocked_by_answer_guard(monkeypatch):
    """A-01 回归:助教/备课/面试页面都带固定 branch,答案保护不得被旁路"""
    async def fail_llm(*args, **kwargs):
        raise AssertionError("命中答案保护时不应再调用模型风控")

    monkeypatch.setattr(router_module, "check_answer_request", lambda *a, **k: {
        "risk_type": "未截止作业答案保护", "kind": "作业", "id": 100,
        "title": "第一次作业", "reason": "命中未截止作业题干",
    })
    monkeypatch.setattr(router_module, "llm_invoke", fail_llm)

    result = asyncio.run(router_module.router_node({
        "messages": [{"role": "user", "content": STEM}],
        "user_id": 1, "user_role": "student", "course_id": 10,
        "branch": "tutor", "intent": "chat",
    }))

    assert result["branch"] == "block"


def test_forced_branch_is_still_checked_by_risk_gate(monkeypatch):
    """A-01 回归:指定分支也必须先过模型风控"""
    async def fake_risk(state, message):
        return {"is_risky": True, "action": "intercept", "risk_type": "代写"}

    monkeypatch.setattr(router_module, "check_answer_request", lambda *a, **k: None)
    monkeypatch.setattr(router_module, "_risk_gate", fake_risk)

    result = asyncio.run(router_module.router_node({
        "messages": [{"role": "user", "content": "帮我写一份课程论文"}],
        "user_id": 1, "user_role": "student", "course_id": 10,
        "branch": "teacher", "intent": "chat",
    }))

    assert result["branch"] == "block"
    assert result["risk_flag"] is True


def test_risk_guard_guides_and_logs_target(monkeypatch):
    class _FakeSession:
        def __init__(self):
            self.added = []

        def add(self, obj):
            self.added.append(obj)

        def commit(self):
            pass

        def close(self):
            pass

    fake = _FakeSession()
    monkeypatch.setattr(risk_guard_module, "SessionLocal", lambda: fake)

    result = asyncio.run(risk_guard_module.risk_guard_node({
        "messages": [{"role": "user", "content": STEM}],
        "user_id": 1,
        "risk_type": "未截止作业答案保护",
        "risk_target": "作业#100",
    }))

    assert "尚未截止" in result["final_output"]
    assert result["reflection_passed"] is True
    assert fake.added[0].risk_type == "未截止作业答案保护"
    assert fake.added[0].action_taken == "拦截转引导(作业#100)"
