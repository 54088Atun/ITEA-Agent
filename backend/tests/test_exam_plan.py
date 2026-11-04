"""考试科目/考核项建议(TC-05)

覆盖:
- 建议方案清洗:非法题型/空考核项/空科目被丢弃,题量与分值限制在合理区间
- AI 建议草稿生成、按课程查询
- 草稿仅本人可操作(403)
- 采纳后成为考试配置并写审批审计;重复采纳、丢弃后采纳被拒
- 丢弃后可按状态筛选
- 考试功能关闭时拒绝生成
"""
import asyncio

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.api.exams as exams_api
from app.api.exams import (
    adopt_exam_plan_draft, create_exam_plan_draft, discard_exam_plan_draft,
    list_exam_plan_drafts,
)
from app.db.session import Base
from app.models.course import Course, KnowledgePoint
from app.models.exam import ExamPlanDraft
from app.models.log import SystemConfig, WriteAuditLog
from app.models.user import User
from app.schemas.exam import ExamPlanGenerateRequest
from app.services.exam_plan_generator import normalize_plan
from app.services.feature_flags import seed_defaults


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add_all([
        User(id=1, role="teacher", name="张老师", email="t1@example.com",
             password_hash="x", status="active"),
        User(id=2, role="teacher", name="李老师", email="t2@example.com",
             password_hash="x", status="active"),
        Course(id=10, teacher_id=1, name="软件测试", code="ST101",
               audit_status="approved"),
        Course(id=11, teacher_id=2, name="Web 开发", code="WEB101",
               audit_status="approved"),
        KnowledgePoint(id=30, course_id=10, name="等价类划分"),
        KnowledgePoint(id=31, course_id=10, name="边界值分析"),
    ])
    session.commit()
    seed_defaults(session)
    yield session
    session.close()
    engine.dispose()


RAW_PLAN = {
    "title": "期中组卷建议",
    "summary": "覆盖等价类与边界值",
    "duration_minutes": 90,
    "total_score": 100,
    "subjects": [
        {
            "subject": "等价类划分",
            "kp_names": ["等价类划分"],
            "reason": "基础方法",
            "items": [
                {"type": "single", "count": 4, "score": 5, "difficulty": 2},
                {"type": "not-a-type", "count": 3, "score": 5},
            ],
        },
        {
            "subject": "边界值分析",
            "kp_names": ["边界值分析"],
            "items": [{"type": "short", "count": 2, "score": 10, "difficulty": 4}],
        },
        {"subject": "空考核项", "items": []},
    ],
}


def test_normalize_plan_drops_invalid_items_and_subjects():
    plan = normalize_plan(RAW_PLAN, 60, 80)
    assert [s["subject"] for s in plan["subjects"]] == ["等价类划分", "边界值分析"]
    assert plan["subjects"][0]["items"] == [
        {"type": "single", "count": 4, "score": 5, "difficulty": 2},
    ]
    assert plan["subjects"][0]["question_count"] == 4
    assert plan["subjects"][0]["score"] == 20
    assert plan["subjects"][1]["score"] == 20
    assert plan["planned_score"] == 40
    # 模型给出的时长/总分优先于请求默认值
    assert plan["duration_minutes"] == 90
    assert plan["total_score"] == 100

    fallback = normalize_plan({"subjects": RAW_PLAN["subjects"]}, 60, 80)
    assert fallback["duration_minutes"] == 60
    assert fallback["total_score"] == 80
    assert fallback["title"] == "考试组卷建议"

    with pytest.raises(ValueError):
        normalize_plan({"subjects": []}, 90, 100)


def test_generate_list_adopt_and_discard(db, monkeypatch):
    async def fake_generate(*args, **kwargs):
        return RAW_PLAN

    monkeypatch.setattr(exams_api, "generate_exam_plan", fake_generate)
    draft = asyncio.run(create_exam_plan_draft(
        10, ExamPlanGenerateRequest(duration_minutes=90, total_score=100),
        db.get(User, 1), db,
    ))
    assert draft["status"] == "draft"
    assert len(draft["plan"]["subjects"]) == 2

    rows = list_exam_plan_drafts(10, None, db.get(User, 1), db)
    assert [row["id"] for row in rows] == [draft["id"]]
    assert rows[0]["plan"]["planned_score"] == 40

    # 其他教师不能查看/采纳
    with pytest.raises(HTTPException) as exc:
        list_exam_plan_drafts(10, None, db.get(User, 2), db)
    assert exc.value.status_code == 403
    with pytest.raises(HTTPException) as exc:
        adopt_exam_plan_draft(draft["id"], db.get(User, 2), db)
    assert exc.value.status_code == 403

    adopted = adopt_exam_plan_draft(draft["id"], db.get(User, 1), db)
    assert adopted["status"] == "adopted"
    assert db.get(ExamPlanDraft, draft["id"]).status == "adopted"
    audit = db.query(WriteAuditLog).filter_by(action="exam.plan_adopt").one()
    assert audit.status == "executed"
    assert audit.approval_mode == "auto"
    assert audit.target_type == "exam_plan_draft"

    with pytest.raises(HTTPException) as exc:
        adopt_exam_plan_draft(draft["id"], db.get(User, 1), db)
    assert exc.value.status_code == 400

    assert [row["id"] for row in list_exam_plan_drafts(
        10, "adopted", db.get(User, 1), db,
    )] == [draft["id"]]

    stray = asyncio.run(create_exam_plan_draft(
        10, ExamPlanGenerateRequest(), db.get(User, 1), db,
    ))
    assert discard_exam_plan_draft(
        stray["id"], db.get(User, 1), db,
    )["status"] == "discarded"
    with pytest.raises(HTTPException) as exc:
        adopt_exam_plan_draft(stray["id"], db.get(User, 1), db)
    assert exc.value.status_code == 400


def test_generate_rejects_empty_plan(db, monkeypatch):
    async def empty_plan(*args, **kwargs):
        return {"subjects": []}

    monkeypatch.setattr(exams_api, "generate_exam_plan", empty_plan)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(create_exam_plan_draft(
            10, ExamPlanGenerateRequest(), db.get(User, 1), db,
        ))
    assert exc.value.status_code == 502


def test_generate_requires_owned_course_and_enabled_feature(db, monkeypatch):
    async def fake_generate(*args, **kwargs):
        return RAW_PLAN

    monkeypatch.setattr(exams_api, "generate_exam_plan", fake_generate)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(create_exam_plan_draft(
            11, ExamPlanGenerateRequest(), db.get(User, 1), db,
        ))
    assert exc.value.status_code == 403

    config = db.query(SystemConfig).filter_by(config_key="feature_exams").one()
    config.config_value = "off"
    db.commit()
    with pytest.raises(HTTPException) as exc:
        asyncio.run(create_exam_plan_draft(
            10, ExamPlanGenerateRequest(), db.get(User, 1), db,
        ))
    assert exc.value.status_code == 403
