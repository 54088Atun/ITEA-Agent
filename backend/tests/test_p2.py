"""P2:学习/发布记录、数据导出、账号注销、灰度开关与配额

覆盖:
- 学习记录时间线只含本人数据,包含课程/练习/错题/复习/面试/作业
- 教师发布记录含提交与已批改统计,可按班级筛选
- 导出 JSON 不含密码与他人数据
- 学生注销:删除学习数据、匿名化账号、不能再用原密码登录
- 教师名下有课程时禁止注销;管理员不支持自助注销
- 关闭作业/分享开关后写操作 403
- 图片上传配额:开关、大小、每日次数
"""
import asyncio
import json
from datetime import datetime

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.responses import Response

import app.api.student as student_api
from app.api.assignments import create_assignment
from app.api.auth import (
    AUTH_COOKIE, AUTH_REFRESH_COOKIE, login as auth_login, refresh as auth_refresh,
)
from app.api.course_share import create_share
from app.api.me import DeactivateRequest, deactivate_account, export_my_data
from app.api.records import student_records, teacher_publish_records
from app.core.security import (
    create_refresh_token, decode_access_token, decode_refresh_token,
    hash_password, verify_password,
)
from app.schemas.auth import LoginRequest, RegisterRequest
from app.db.session import Base
from app.models.assignment import Assignment, Submission
from app.models.classroom import Classroom, ClassMember, CourseEnrollment
from app.models.conversation import ChatMessage, Conversation
from app.models.course import Course, KnowledgePoint
from app.models.interview import InterviewRecord
from app.models.log import OperationLog, SystemConfig
from app.models.practice import PracticeRecord
from app.models.profile import MasteryRecord, ReviewPlan, StudentProfile, WrongQuestion
from app.models.upload_event import UploadEvent
from app.models.user import User
from app.schemas.assignment import AssignmentCreate, CourseShareCreate
from app.schemas.student import PracticeGenerateRequest
from app.services.feature_flags import public_features, seed_defaults
from app.services.quotas import assert_image_upload_allowed

PASSWORD = "Test@123456"


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    seed(session)
    seed_defaults(session)
    yield session
    session.close()
    engine.dispose()


def seed(db):
    pwd = hash_password(PASSWORD)
    teacher = User(id=1, role="teacher", name="张老师", email="t1@example.com",
                   password_hash=pwd, status="active")
    teacher2 = User(id=2, role="teacher", name="李老师", email="t2@example.com",
                    password_hash=pwd, status="active")
    student = User(id=3, role="student", name="小明", email="s1@example.com",
                   password_hash=pwd, status="active")
    other = User(id=4, role="student", name="小红", email="s2@example.com",
                 password_hash=pwd, status="active")
    admin = User(id=5, role="admin", name="管理员", email="a@example.com",
                 password_hash=pwd, status="active")
    course = Course(id=10, teacher_id=1, name="软件测试", code="ST101",
                    audit_status="approved")
    kp = KnowledgePoint(id=30, course_id=10, name="等价类划分")
    classroom = Classroom(id=20, teacher_id=1, course_id=10, name="测试 1 班",
                          invite_code="ABCD1234")
    profile = StudentProfile(id=50, user_id=3, course_id=10, overall_progress=60)
    other_profile = StudentProfile(id=51, user_id=4, course_id=10)
    db.add_all([teacher, teacher2, student, other, admin, course, kp, classroom,
                profile, other_profile])
    db.add(ClassMember(class_id=20, student_id=3, status="active"))
    db.add(ClassMember(class_id=20, student_id=4, status="active"))
    db.add(CourseEnrollment(course_id=10, student_id=3, source="class", class_id=20))
    db.add(MasteryRecord(profile_id=50, kp_id=30, mastery_level=70))
    db.add(PracticeRecord(profile_id=50, kp_id=30, type="in_class", content="练习内容 A"))
    wq = WrongQuestion(profile_id=50, kp_id=30, question_content="错题内容 A",
                       error_type="概念不清")
    db.add(wq)
    db.flush()
    db.add(ReviewPlan(wrong_question_id=wq.id, next_review_at=datetime.utcnow(),
                      review_count=1, interval_days=1, status="pending"))
    db.add(InterviewRecord(profile_id=50, round=1, question="讲讲等价类", score=80))
    asg = Assignment(id=60, teacher_id=1, course_id=10, class_id=20, title="第一次作业",
                     description="要求", reference_answer="答案", status="published")
    db.add(asg)
    db.flush()
    db.add(Submission(assignment_id=60, student_id=3, content="我的作答 A",
                      score=85, feedback="不错", confirmed_at=datetime.utcnow(),
                      confirmed_by=1))
    db.add(Submission(assignment_id=60, student_id=4, content="他人作答 B"))
    conv = Conversation(session_id="sess-student", user_id=3, title="我的会话",
                        branch="tutor")
    other_conv = Conversation(session_id="sess-other", user_id=4, title="他人会话",
                              branch="tutor")
    db.add_all([conv, other_conv])
    db.flush()
    db.add(ChatMessage(conversation_id=conv.id, role="user", content="学生提问 A"))
    db.add(ChatMessage(conversation_id=other_conv.id, role="user", content="他人提问 B"))
    db.commit()


def test_student_timeline_only_own_data(db):
    events = student_records(80, db.get(User, 3), db)
    types = {e["type"] for e in events}
    assert {"enrollment", "practice", "wrong", "review", "interview", "assignment"} <= types
    titles = " ".join(e["title"] for e in events)
    assert "第一次作业" in titles
    assert "练习内容 A" in " ".join(e.get("detail") or "" for e in events)
    # 他人数据不可见
    assert "他人作答 B" not in json.dumps(events, ensure_ascii=False)
    assert "他人会话" not in json.dumps(events, ensure_ascii=False)


def test_generate_practice_recommendation_references_real_wrong_question(db, monkeypatch):
    wq = db.query(WrongQuestion).filter_by(profile_id=50).one()
    wq.created_at = datetime(2026, 1, 2, 3, 4, 5)
    db.commit()
    captured = {}

    async def fake_generate(course_name, points, count):
        captured["points"] = points
        return [{"question": "针对性练习", "kp_name": points[0], "hint": "复习错题"}]

    monkeypatch.setattr(student_api, "generate_practice", fake_generate)
    result = asyncio.run(student_api.generate_practice_api(
        PracticeGenerateRequest(course_id=10), db.get(User, 3), db,
    ))

    assert result["course_id"] == 10
    assert result["items"][0]["question"] == "针对性练习"
    recommendation = result["recommendation"]
    assert "错题" in recommendation["reason"]
    assert "等价类划分" in recommendation["reason"]
    assert recommendation["record_refs"] == [{
        "type": "wrong_question",
        "id": wq.id,
        "title": "等价类划分",
        "created_at": wq.created_at,
    }]
    assert captured["points"] == ["等价类划分"]


def test_generate_practice_recommendation_references_real_low_mastery(db, monkeypatch):
    db.query(ReviewPlan).delete()
    db.query(WrongQuestion).filter_by(profile_id=50).delete()
    mastery = db.query(MasteryRecord).filter_by(profile_id=50, kp_id=30).one()
    mastery.mastery_level = 35
    mastery.last_assessed_at = datetime(2026, 2, 3, 4, 5, 6)
    db.commit()
    captured = {}

    async def fake_generate(course_name, points, count):
        captured["points"] = points
        return [{"question": "补强练习", "kp_name": points[0], "hint": "巩固基础"}]

    monkeypatch.setattr(student_api, "generate_practice", fake_generate)
    result = asyncio.run(student_api.generate_practice_api(
        PracticeGenerateRequest(course_id=10), db.get(User, 3), db,
    ))

    recommendation = result["recommendation"]
    assert "低掌握" in recommendation["reason"]
    assert "等价类划分" in recommendation["reason"]
    assert recommendation["record_refs"] == [{
        "type": "mastery",
        "id": mastery.id,
        "title": "等价类划分",
        "created_at": mastery.last_assessed_at,
    }]
    assert captured["points"] == ["等价类划分"]


def test_generate_practice_without_learning_records_is_course_based(db, monkeypatch):
    db.query(ReviewPlan).delete()
    for model in (WrongQuestion, MasteryRecord, PracticeRecord, InterviewRecord):
        db.query(model).filter_by(profile_id=50).delete()
    db.commit()

    async def fake_generate(course_name, points, count):
        return [{"question": "基础练习", "kp_name": points[0], "hint": "课程基础"}]

    monkeypatch.setattr(student_api, "generate_practice", fake_generate)
    result = asyncio.run(student_api.generate_practice_api(
        PracticeGenerateRequest(course_id=10), db.get(User, 3), db,
    ))

    assert "课程基础推荐" in result["recommendation"]["reason"]
    assert result["recommendation"]["record_refs"] == []
    assert result["items"][0]["kp_name"] == "等价类划分"


def test_student_timeline_has_record_ids_and_excludes_drafts(db):
    enrollment = db.query(CourseEnrollment).filter_by(student_id=3).one()
    practice = db.query(PracticeRecord).filter_by(profile_id=50).one()
    wrong = db.query(WrongQuestion).filter_by(profile_id=50).one()
    review = db.query(ReviewPlan).join(WrongQuestion).filter(WrongQuestion.id == wrong.id).one()
    interview = db.query(InterviewRecord).filter_by(profile_id=50).one()
    submission = db.query(Submission).filter_by(student_id=3, content="我的作答 A").one()
    submission.created_at = datetime(2026, 3, 1, 8, 0, 0)
    submission.submitted_at = datetime(2026, 3, 1, 9, 30, 0)
    db.add(Assignment(
        id=61, teacher_id=1, course_id=10, class_id=20,
        title="仅草稿作业", description="要求", status="published",
    ))
    db.add(Submission(
        assignment_id=61, student_id=3, content="私有草稿", status="draft",
    ))
    db.commit()

    events = student_records(80, db.get(User, 3), db)
    expected_ids = {
        "enrollment": enrollment.id,
        "practice": practice.id,
        "wrong": wrong.id,
        "review": review.id,
        "interview": interview.id,
        "assignment": submission.id,
    }
    for event_type, record_id in expected_ids.items():
        assert next(e for e in events if e["type"] == event_type)["record_id"] == record_id
    assert all(isinstance(e.get("record_id"), int) for e in events)
    assignment_event = next(e for e in events if e["type"] == "assignment")
    assert assignment_event["created_at"] == submission.submitted_at.isoformat()
    assert "仅草稿作业" not in json.dumps(events, ensure_ascii=False)


def test_teacher_publish_records_and_filter(db):
    rows = teacher_publish_records(None, 50, db.get(User, 1), db)
    assert len(rows) == 1
    assert rows[0]["submission_count"] == 2
    assert rows[0]["graded_count"] == 1
    assert rows[0]["pending_count"] == 1
    assert teacher_publish_records(999, 50, db.get(User, 1), db) == []
    assert teacher_publish_records(None, 50, db.get(User, 2), db) == []


def test_export_contains_own_data_without_secrets(db):
    resp = export_my_data(db.get(User, 3), db)
    body = resp.body.decode("utf-8")
    data = json.loads(body)
    assert data["account"]["email"] == "s1@example.com"
    assert "password_hash" not in body
    assert "我的作答 A" in body
    assert "他人作答 B" not in body
    assert "他人提问 B" not in body
    assert data["student"]["learning"][0]["wrong_questions"][0]["question"] == "错题内容 A"
    assert "他人会话" not in body


def test_student_deactivate_deletes_data_and_anonymizes(db):
    student = db.get(User, 3)
    resp = deactivate_account(
        DeactivateRequest(password=PASSWORD, confirm="注销"), student, db,
    )
    assert resp["deactivated"] is True

    user = db.get(User, 3)
    assert user.status == "disabled"
    assert user.name == "已注销用户"
    assert user.email.startswith("deleted_3@")
    assert verify_password(PASSWORD, user.password_hash) is False

    assert db.query(StudentProfile).filter_by(user_id=3).count() == 0
    for model in (MasteryRecord, PracticeRecord, WrongQuestion, InterviewRecord):
        assert db.query(model).filter_by(profile_id=50).count() == 0
    assert db.query(ReviewPlan).count() == 0
    assert db.query(Submission).filter_by(student_id=3).count() == 0
    assert db.query(Conversation).filter_by(user_id=3).count() == 0
    assert db.query(ChatMessage).count() == 1  # 仅剩他人会话消息
    assert db.query(CourseEnrollment).filter_by(student_id=3).count() == 0
    assert db.query(ClassMember).filter_by(student_id=3).count() == 0
    assert db.query(UploadEvent).filter_by(user_id=3).count() == 0


def test_deactivate_guards(db):
    student = db.get(User, 3)
    with pytest.raises(HTTPException) as exc:
        deactivate_account(DeactivateRequest(password="bad-password", confirm="注销"), student, db)
    assert exc.value.status_code == 400

    with pytest.raises(HTTPException) as exc:
        deactivate_account(DeactivateRequest(password=PASSWORD, confirm="确认"), student, db)
    assert exc.value.status_code == 400

    with pytest.raises(HTTPException) as exc:
        deactivate_account(DeactivateRequest(password=PASSWORD, confirm="注销"), db.get(User, 1), db)
    assert exc.value.status_code == 400
    assert "课程" in exc.value.detail

    with pytest.raises(HTTPException) as exc:
        deactivate_account(DeactivateRequest(password=PASSWORD, confirm="注销"), db.get(User, 5), db)
    assert exc.value.status_code == 403

    # 无课程/班级的教师可注销
    resp = deactivate_account(
        DeactivateRequest(password=PASSWORD, confirm="注销"), db.get(User, 2), db,
    )
    assert resp["deactivated"] is True
    assert db.get(User, 2).status == "disabled"
    assert db.query(OperationLog).filter_by(action="deactivate").count() == 1


def test_feature_switches_block_writes(db):
    teacher = db.get(User, 1)
    assert public_features(db)["feature_assignments"] is True

    cfg = db.query(SystemConfig).filter_by(config_key="feature_assignments").first()
    cfg.config_value = "off"
    db.commit()
    assert public_features(db)["feature_assignments"] is False
    with pytest.raises(HTTPException) as exc:
        create_assignment(AssignmentCreate(title="关闭期作业", course_id=10), teacher, db)
    assert exc.value.status_code == 403

    cfg.config_value = "on"
    share_cfg = db.query(SystemConfig).filter_by(config_key="feature_course_share").first()
    share_cfg.config_value = "off"
    db.commit()
    with pytest.raises(HTTPException) as exc:
        create_share(10, CourseShareCreate(), teacher, db)
    assert exc.value.status_code == 403


def test_image_upload_quotas(db):
    student = db.get(User, 3)
    assert_image_upload_allowed(db, student, 1024)

    size_cfg = db.query(SystemConfig).filter_by(config_key="upload_image_max_mb").first()
    size_cfg.config_value = "1"
    db.commit()
    with pytest.raises(HTTPException) as exc:
        assert_image_upload_allowed(db, student, 2 * 1024 * 1024)
    assert exc.value.status_code == 400

    limit_cfg = db.query(SystemConfig).filter_by(config_key="vision_daily_limit").first()
    limit_cfg.config_value = "1"
    db.commit()
    db.add(UploadEvent(user_id=3, kind="image", size=100))
    db.commit()
    with pytest.raises(HTTPException) as exc:
        assert_image_upload_allowed(db, student, 100)
    assert exc.value.status_code == 429

    vision_cfg = db.query(SystemConfig).filter_by(config_key="feature_image_vision").first()
    vision_cfg.config_value = "off"
    db.commit()
    with pytest.raises(HTTPException) as exc:
        assert_image_upload_allowed(db, student, 100)
    assert exc.value.status_code == 403


def test_image_upload_limit_capped_at_8mb(db):
    """后台即使配置到 20MB,对外口径与落盘校验都按 8MB 收口"""
    cfg = db.query(SystemConfig).filter_by(config_key="upload_image_max_mb").first()
    cfg.config_value = "20"
    db.commit()

    assert public_features(db)["upload_image_max_mb"] == 8
    with pytest.raises(HTTPException) as exc:
        assert_image_upload_allowed(db, db.get(User, 3), 9 * 1024 * 1024)
    assert exc.value.status_code == 400
    assert "图片过大" in exc.value.detail


def _cookie_value(response, name: str) -> str:
    for key, value in response.raw_headers:
        if key.lower() != b"set-cookie":
            continue
        text = value.decode("latin-1")
        if text.startswith(f"{name}="):
            return text.split(";", 1)[0].split("=", 1)[1]
    return ""


def test_login_sets_access_and_refresh_cookies(db):
    response = Response()
    payload = auth_login(
        LoginRequest(email="s1@example.com", password=PASSWORD), response, db,
    )
    access = _cookie_value(response, AUTH_COOKIE)
    refresh = _cookie_value(response, AUTH_REFRESH_COOKIE)
    assert access == payload.access_token
    assert refresh
    assert payload.expires_in > 0

    # 刷新令牌不能当访问令牌使用
    assert decode_access_token(refresh) is None
    assert decode_refresh_token(access) is None
    assert decode_refresh_token(refresh)["sub"] == "3"


def test_refresh_rotates_access_token(db):
    from types import SimpleNamespace

    token = create_refresh_token(3, 0)
    request = SimpleNamespace(cookies={AUTH_REFRESH_COOKIE: token})
    response = Response()
    payload = auth_refresh(request, response, db)

    assert payload.access_token != token
    assert decode_access_token(payload.access_token)["sub"] == "3"
    assert _cookie_value(response, AUTH_COOKIE) == payload.access_token
    assert _cookie_value(response, AUTH_REFRESH_COOKIE)


def test_refresh_rejects_access_token_and_missing_cookie(db):
    from types import SimpleNamespace

    access = create_refresh_token(3, 0)
    with pytest.raises(HTTPException) as exc:
        auth_refresh(SimpleNamespace(cookies={}), Response(), db)
    assert exc.value.status_code == 401

    # 访问令牌放错位置同样拒绝
    with pytest.raises(HTTPException) as exc:
        auth_refresh(
            SimpleNamespace(cookies={AUTH_REFRESH_COOKIE: "not-a-token"}),
            Response(), db,
        )
    assert exc.value.status_code == 401
    assert decode_refresh_token(access) is not None


def test_tool_loop_reuses_identical_calls(monkeypatch):
    """同参工具调用只执行一次,第二次直接复用本轮结果"""
    import app.agent.tool_loop as loop

    executed: list[str] = []

    async def fake_execute(item, state, approval=None, quota=None):
        executed.append(item["name"])
        return {"ok": True, "data": {"count": 1}}

    monkeypatch.setattr(loop, "_execute", fake_execute)

    history: list[dict] = []
    trace: list[dict] = []
    state = {"user_role": "admin", "user_id": 5, "session_id": "sess-cache"}
    call = {"name": "admin.course_list", "arguments": {"limit": 10}, "id": "c1"}
    other = {"name": "admin.course_list", "arguments": {"limit": 5}, "id": "c2"}
    cache: dict = {}

    asyncio.run(loop._run_calls([call], history, state, trace, cache=cache))
    asyncio.run(loop._run_calls([call], history, state, trace, cache=cache))
    asyncio.run(loop._run_calls([other], history, state, trace, cache=cache))

    # 同参复用,换参重新执行
    assert executed == ["admin.course_list", "admin.course_list"]
    assert trace[0]["cached"] is False
    assert trace[1]["cached"] is True
    assert trace[2]["cached"] is False


def test_collab_single_plan_not_empty(monkeypatch):
    """降级为单 Agent 时也回填实际执行计划,避免 plan 为空"""
    import app.agent.nodes.collab as collab

    async def fake_llm(messages, **kwargs):
        return '{"primary_agent": "tutor", "tasks": []}'

    monkeypatch.setattr(collab, "llm_invoke", fake_llm)
    queue = asyncio.Queue()
    state = {
        "user_role": "student",
        "messages": [{"role": "user", "content": "这道题怎么写"}],
        "stream_queue": queue,
    }

    async def run_and_collect():
        result = await collab.collab_plan_node(state)
        return result, await asyncio.wait_for(queue.get(), timeout=1)

    out, (_, payload) = asyncio.run(run_and_collect())

    assert out["branch"] == "tutor"
    assert out["collab_tasks"] == []
    assert payload["source"] == "single"
    assert payload["plan"][0]["agent"] == "tutor"
    assert payload["plan"][0]["task"]


def test_login_failure_rate_limit(db):
    """同一账号连续失败达到阈值后返回 429,成功登录后计数清零"""
    from app.api import auth as auth_api

    auth_api._login_failures.clear()
    email = "rate-limit@example.com"
    try:
        for _ in range(auth_api.LOGIN_MAX_FAILURES):
            with pytest.raises(HTTPException) as exc:
                auth_login(LoginRequest(email=email, password="wrong-pass1"), Response(), db)
            assert exc.value.status_code == 401

        with pytest.raises(HTTPException) as exc:
            auth_login(LoginRequest(email=email, password="wrong-pass1"), Response(), db)
        assert exc.value.status_code == 429

        # 其他账号不受影响
        other = LoginRequest(email="other@example.com", password="wrong-pass1")
        with pytest.raises(HTTPException) as exc:
            auth_login(other, Response(), db)
        assert exc.value.status_code == 401
    finally:
        auth_api._login_failures.clear()


def test_login_success_resets_failure_counter(db):
    import app.api.auth as auth_api
    from app.models.user import User

    auth_api._login_failures.clear()
    user = User(
        role="student", name="限流测试", email="reset@example.com",
        password_hash=hash_password("correct-pass1"), status="active",
    )
    db.add(user)
    db.commit()
    try:
        for _ in range(auth_api.LOGIN_MAX_FAILURES - 1):
            with pytest.raises(HTTPException):
                auth_login(LoginRequest(email=user.email, password="wrong-pass1"), Response(), db)
        auth_login(LoginRequest(email=user.email, password="correct-pass1"), Response(), db)
        assert user.email.lower() not in auth_api._login_failures
    finally:
        auth_api._login_failures.clear()


def test_admin_config_effective_value_reflects_dependency(monkeypatch, db):
    """管理端配置返回实际生效值:开关 on 但服务未配置时标记不可用"""
    from app.api import admin as admin_api
    from app.models.log import SystemConfig

    row = db.query(SystemConfig).filter(SystemConfig.config_key == "feature_asr").one()

    monkeypatch.setitem(
        admin_api._EFFECTIVE_CHECKS, "feature_asr",
        (lambda: False, "语音识别服务未配置"),
    )
    item = admin_api._config_items(db, [row])[0]
    assert item.effective_value == "off"
    assert item.effective_note == "语音识别服务未配置"

    monkeypatch.setitem(admin_api._EFFECTIVE_CHECKS, "feature_asr", (lambda: True, ""))
    item = admin_api._config_items(db, [row])[0]
    assert item.effective_value == "on"
    assert item.effective_note is None

    row.config_value = "off"
    db.commit()
    item = admin_api._config_items(db, [row])[0]
    assert item.effective_value == "off"


def test_register_email_domain_whitelist(monkeypatch, db):
    """配置校园域后,非白名单邮箱不能注册(邮箱验证暂缓,先做域名约束)"""
    from app.api import auth as auth_api
    from app.schemas.auth import RegisterRequest

    monkeypatch.setattr(auth_api.settings, "REGISTER_EMAIL_DOMAINS", "edu.cn")

    with pytest.raises(HTTPException) as exc:
        auth_api.register(RegisterRequest(
            role="student", name="外部用户", email="outside@example.com",
            password="Abcd1234",
        ), Response(), db)
    assert exc.value.status_code == 403

    payload = auth_api.register(RegisterRequest(
        role="student", name="校内用户", email="student@cs.edu.cn",
        password="Abcd1234",
    ), Response(), db)
    assert payload.role == "student"
    assert payload.user.email == "student@cs.edu.cn"
