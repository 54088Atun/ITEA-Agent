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
import json
from datetime import datetime

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.assignments import create_assignment
from app.api.course_share import create_share
from app.api.me import DeactivateRequest, deactivate_account, export_my_data
from app.api.records import student_records, teacher_publish_records
from app.core.security import hash_password, verify_password
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
