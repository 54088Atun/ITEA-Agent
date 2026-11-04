"""作业发布 / 学生可见性 / AI 建议批改与教师确认

覆盖:
- 非本课教师不能发布作业
- 草稿不可见,发布后命中班级/课程的学生可见,非目标不可见
- 截止后禁止提交,参考答案截止前不下发
- AI 批改只写 ai_* 字段,教师确认后才写正式分数
- 确认后学生不可再次提交
"""
import asyncio
from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.api.assignments as assignments_api
from app.api.assignments import (
    ai_grade_submission, batch_publish_assignments, confirm_grade,
    create_assignment, get_my_assignment, give_student_feedback,
    list_assignments, list_my_assignments, publish_assignment,
    publish_course_announcement, remind_assignment, submit_assignment,
)
from app.db.session import Base
from app.models.assignment import Assignment, Submission
from app.models.classroom import (
    ClassAnnouncement, ClassMember, Classroom, CourseEnrollment,
)
from app.models.course import Course
from app.models.notification import Notification, NotificationPreference
from app.models.user import User
from app.schemas.assignment import (
    AssignmentBatchPublishRequest, AssignmentCreate, AssignmentRemindRequest,
    CourseAnnouncementRequest, GradeConfirmRequest, StudentFeedbackRequest,
    SubmissionCreate,
)


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    seed(session)
    yield session
    session.close()
    engine.dispose()


def seed(db):
    teacher = User(id=1, role="teacher", name="张老师", email="t1@example.com",
                   password_hash="x", status="active")
    other = User(id=2, role="teacher", name="李老师", email="t2@example.com",
                 password_hash="x", status="active")
    student = User(id=3, role="student", name="小明", email="s1@example.com",
                   password_hash="x", status="active")
    outsider = User(id=4, role="student", name="小红", email="s2@example.com",
                    password_hash="x", status="active")
    course = Course(id=10, teacher_id=1, name="软件测试", code="ST101",
                    audit_status="approved")
    classroom = Classroom(id=20, teacher_id=1, course_id=10, name="测试 1 班",
                          invite_code="ABCD1234")
    db.add_all([teacher, other, student, outsider, course, classroom])
    db.add(ClassMember(class_id=20, student_id=3, status="active"))
    db.add(CourseEnrollment(course_id=10, student_id=3, source="class", class_id=20))
    db.commit()


def _publish(db, **kwargs):
    data = create_assignment(AssignmentCreate(title=kwargs.pop("title", "第一次作业"),
                                              **kwargs), db.get(User, 1), db)
    return db.get(Assignment, data["id"])


def test_teacher_cannot_publish_to_others_course(db):
    with pytest.raises(HTTPException) as exc:
        create_assignment(
            AssignmentCreate(title="越权作业", course_id=10), db.get(User, 2), db,
        )
    assert exc.value.status_code == 403


def test_assignment_requires_course_binding(db):
    """决策 #8:作业必须绑定课程,不能只挂班级"""
    with pytest.raises(HTTPException) as exc:
        create_assignment(
            AssignmentCreate(title="无课程作业", class_id=20), db.get(User, 1), db,
        )
    assert exc.value.status_code == 400
    assert "课程" in exc.value.detail


def test_assignment_class_must_belong_to_course(db):
    db.add(Course(id=11, teacher_id=1, name="另一门课", code="ST102",
                  audit_status="approved"))
    db.commit()

    with pytest.raises(HTTPException) as exc:
        create_assignment(
            AssignmentCreate(title="错配作业", course_id=11, class_id=20),
            db.get(User, 1), db,
        )
    assert exc.value.status_code == 400
    assert "班级" in exc.value.detail


def test_draft_invisible_until_published(db):
    assignment = _publish(db, course_id=10, publish=False)
    student = db.get(User, 3)
    assert list_my_assignments(student, db) == []

    publish_assignment(assignment.id, db.get(User, 1), db, confirm=True)
    rows = list_my_assignments(student, db)
    assert [r["id"] for r in rows] == [assignment.id]
    assert rows[0]["state"] == "not_submitted"

    # 非目标学生不可见,也不能查看详情
    outsider = db.get(User, 4)
    assert list_my_assignments(outsider, db) == []
    with pytest.raises(HTTPException) as exc:
        get_my_assignment(assignment.id, outsider, db)
    assert exc.value.status_code == 403


def test_reference_answer_hidden_before_due(db):
    assignment = _publish(db, course_id=10, due_days=1,
                          reference_answer="等价类、边界值")
    student = db.get(User, 3)
    detail = get_my_assignment(assignment.id, student, db)
    assert detail["due_passed"] is False
    assert detail["reference_answer"] is None

    assignment.due_at = datetime.utcnow() - timedelta(minutes=1)
    db.commit()
    detail = get_my_assignment(assignment.id, student, db)
    assert detail["due_passed"] is True
    assert detail["reference_answer"] == "等价类、边界值"


def test_submit_blocked_after_due(db):
    assignment = _publish(db, course_id=10, due_days=1)
    student = db.get(User, 3)
    result = submit_assignment(
        assignment.id, SubmissionCreate(content="我的作答"), student, db,
    )
    assert result["state"] == "pending_review"

    assignment.due_at = datetime.utcnow() - timedelta(minutes=1)
    db.commit()
    with pytest.raises(HTTPException) as exc:
        submit_assignment(
            assignment.id, SubmissionCreate(content="补交"), student, db,
        )
    assert exc.value.status_code == 400
    assert "截止" in exc.value.detail


def test_ai_grade_requires_teacher_confirmation(db, monkeypatch):
    async def fake_grade(*args, **kwargs):
        return {"score": 88, "feedback": "AI 建议评语", "source": "rule"}

    monkeypatch.setattr(assignments_api, "grade_submission", fake_grade)

    assignment = _publish(db, course_id=10, due_days=3,
                          reference_answer="等价类划分与边界值分析")
    student = db.get(User, 3)
    teacher = db.get(User, 1)
    submit_assignment(assignment.id, SubmissionCreate(content="等价类划分"), student, db)
    sub = db.query(Submission).filter_by(assignment_id=assignment.id).first()

    result = asyncio.run(ai_grade_submission(sub.id, teacher, db))
    assert result["source"] == "rule"
    assert sub.ai_score == 88
    assert sub.score is None and sub.confirmed_at is None

    # 学生此时只看到"待确认",看不到 AI 建议分
    detail = get_my_assignment(assignment.id, student, db)
    assert detail["state"] == "pending_review"
    assert detail["my_submission"]["score"] is None
    assert detail["my_submission"]["feedback"] is None

    # 非本课教师不能确认
    with pytest.raises(HTTPException) as exc:
        confirm_grade(sub.id, GradeConfirmRequest(score=90), db.get(User, 2), db)
    assert exc.value.status_code == 403

    confirm_grade(sub.id, GradeConfirmRequest(score=90), teacher, db)
    detail = get_my_assignment(assignment.id, student, db)
    assert detail["state"] == "graded"
    assert detail["my_submission"]["score"] == 90
    assert detail["my_submission"]["feedback"] == "AI 建议评语"

    # 已批改后不可再次提交
    with pytest.raises(HTTPException) as exc:
        submit_assignment(assignment.id, SubmissionCreate(content="改一下"), student, db)
    assert exc.value.status_code == 400


def test_teacher_detail_counts_pending(db):
    assignment = _publish(db, course_id=10, due_days=3)
    submit_assignment(
        assignment.id, SubmissionCreate(content="作答"), db.get(User, 3), db,
    )
    rows = list_assignments(db.get(User, 1), db)
    assert rows[0]["submission_count"] == 1
    assert rows[0]["pending_count"] == 1

    detail = assignments_api.get_assignment(assignment.id, db.get(User, 1), db)
    assert detail["submissions"][0]["student_name"] == "小明"
    assert detail["submissions"][0]["confirmed"] is False


def test_submission_draft_is_private_and_not_pending(db, monkeypatch):
    assignment = _publish(db, course_id=10, due_days=3)
    student = db.get(User, 3)
    teacher = db.get(User, 1)

    result = submit_assignment(
        assignment.id, SubmissionCreate(content="私有草稿", draft=True), student, db,
    )
    assert result["state"] == "draft"
    assert result["submitted_at"] is None

    detail = get_my_assignment(assignment.id, student, db)
    assert detail["allow_late"] is False
    assert detail["state"] == "draft"
    assert detail["my_submission"]["status"] == "draft"
    assert detail["my_submission"]["content"] == "私有草稿"
    assert detail["my_submission"]["submitted_at"] is None
    assert list_my_assignments(student, db)[0]["state"] == "draft"

    teacher_row = list_assignments(teacher, db)[0]
    assert teacher_row["submission_count"] == 0
    assert teacher_row["pending_count"] == 0
    assert assignments_api.get_assignment(assignment.id, teacher, db)["submissions"] == []

    async def fake_grade(*args, **kwargs):
        return {"score": 80, "feedback": "不应批改草稿", "source": "rule"}

    monkeypatch.setattr(assignments_api, "grade_submission", fake_grade)
    sub = db.query(Submission).filter_by(assignment_id=assignment.id).one()
    with pytest.raises(HTTPException) as exc:
        asyncio.run(ai_grade_submission(sub.id, teacher, db))
    assert exc.value.status_code == 400


def test_formal_submission_uses_submitted_at_with_legacy_fallback(db):
    assignment = _publish(db, course_id=10, due_days=3)
    student = db.get(User, 3)
    teacher = db.get(User, 1)
    submit_assignment(
        assignment.id, SubmissionCreate(content="先存草稿", draft=True), student, db,
    )
    sub = db.query(Submission).filter_by(assignment_id=assignment.id).one()
    sub.created_at = datetime(2020, 1, 1, 8, 0, 0)
    db.commit()

    before = datetime.utcnow()
    result = submit_assignment(
        assignment.id, SubmissionCreate(content="正式作答"), student, db,
    )
    after = datetime.utcnow()
    assert sub.status == "submitted"
    assert before <= sub.submitted_at <= after
    assert result["submitted_at"] == sub.submitted_at
    assert get_my_assignment(
        assignment.id, student, db,
    )["my_submission"]["submitted_at"] == sub.submitted_at
    teacher_detail = assignments_api.get_assignment(assignment.id, teacher, db)
    assert teacher_detail["submissions"][0]["submitted_at"] == sub.submitted_at

    sub.submitted_at = None
    db.commit()
    assert get_my_assignment(
        assignment.id, student, db,
    )["my_submission"]["submitted_at"] == sub.created_at


@pytest.mark.parametrize("draft", [True, False])
def test_due_rejects_draft_and_formal_submission_by_default(db, draft):
    assignment = _publish(db, course_id=10, due_days=1)
    assignment.due_at = datetime.utcnow() - timedelta(minutes=1)
    db.commit()

    with pytest.raises(HTTPException) as exc:
        submit_assignment(
            assignment.id,
            SubmissionCreate(content="截止后内容", draft=draft),
            db.get(User, 3), db,
        )
    assert exc.value.status_code == 400
    assert "截止" in exc.value.detail


def test_teacher_can_allow_late_formal_submission_but_not_late_draft(db):
    assignment = _publish(db, course_id=10, due_days=1)
    assignment.due_at = datetime.utcnow() - timedelta(minutes=1)
    db.commit()
    teacher = db.get(User, 1)
    student = db.get(User, 3)

    with pytest.raises(HTTPException) as exc:
        assignments_api.set_allow_late(assignment.id, True, db.get(User, 2), db)
    assert exc.value.status_code == 403

    result = assignments_api.set_allow_late(assignment.id, True, teacher, db)
    assert result["allow_late"] is True
    assert get_my_assignment(assignment.id, student, db)["allow_late"] is True

    with pytest.raises(HTTPException) as exc:
        submit_assignment(
            assignment.id, SubmissionCreate(content="迟到草稿", draft=True), student, db,
        )
    assert exc.value.status_code == 400

    submitted = submit_assignment(
        assignment.id, SubmissionCreate(content="允许补交"), student, db,
    )
    assert submitted["state"] == "pending_review"
    assert submitted["submitted_at"] is not None


def test_formal_submission_cannot_revert_to_draft(db):
    assignment = _publish(db, course_id=10, due_days=3)
    student = db.get(User, 3)
    submit_assignment(assignment.id, SubmissionCreate(content="正式作答"), student, db)
    sub = db.query(Submission).filter_by(assignment_id=assignment.id).one()
    submitted_at = sub.submitted_at

    with pytest.raises(HTTPException) as exc:
        submit_assignment(
            assignment.id, SubmissionCreate(content="试图回退", draft=True), student, db,
        )
    assert exc.value.status_code == 400
    assert sub.status == "submitted"
    assert sub.content == "正式作答"
    assert sub.submitted_at == submitted_at


def test_closed_assignment_forbids_draft_and_late_submission(db):
    assignment = _publish(db, course_id=10, due_days=3, allow_late=True)
    assignment.status = "closed"
    db.commit()
    student = db.get(User, 3)

    for draft in (True, False):
        with pytest.raises(HTTPException) as exc:
            submit_assignment(
                assignment.id, SubmissionCreate(content="关闭后内容", draft=draft), student, db,
            )
        assert exc.value.status_code == 400
        assert "关闭" in exc.value.detail


def test_records_exclude_drafts_and_use_formal_submission_time(db):
    from app.api.records import student_records, teacher_publish_records

    assignment = _publish(db, course_id=10, due_days=3)
    student = db.get(User, 3)
    teacher = db.get(User, 1)
    submit_assignment(
        assignment.id, SubmissionCreate(content="私有草稿", draft=True), student, db,
    )

    assert [e for e in student_records(80, student, db) if e["type"] == "assignment"] == []
    teacher_row = teacher_publish_records(None, 50, teacher, db)[0]
    assert teacher_row["submission_count"] == 0
    assert teacher_row["pending_count"] == 0

    submit_assignment(assignment.id, SubmissionCreate(content="正式作答"), student, db)
    sub = db.query(Submission).filter_by(assignment_id=assignment.id).one()
    events = [e for e in student_records(80, student, db) if e["type"] == "assignment"]
    assert len(events) == 1
    assert events[0]["created_at"] == sub.submitted_at.isoformat()
    teacher_row = teacher_publish_records(None, 50, teacher, db)[0]
    assert teacher_row["submission_count"] == 1
    assert teacher_row["pending_count"] == 1


def test_batch_publish_preview_confirm_and_skips(db):
    draft_a = _publish(db, course_id=10, publish=False)
    draft_b = _publish(db, course_id=10, title="第二次作业", publish=False)
    published = _publish(db, course_id=10, title="已发布作业")
    foreign = Assignment(teacher_id=2, course_id=10, title="别人的作业", status="draft")
    db.add(foreign)
    db.commit()
    db.query(Notification).delete()
    db.commit()
    teacher = db.get(User, 1)

    preview = batch_publish_assignments(
        AssignmentBatchPublishRequest(assignment_ids=[draft_a.id, draft_b.id, draft_a.id]),
        teacher, db,
    )
    assert preview.dry_run is True
    assert preview.affected == [draft_a.id, draft_b.id]  # 重复 id 去重
    assert db.get(Assignment, draft_a.id).status == "draft"
    assert db.query(Notification).count() == 0

    with pytest.raises(HTTPException) as exc:
        batch_publish_assignments(
            AssignmentBatchPublishRequest(assignment_ids=[draft_a.id], dry_run=False),
            teacher, db, confirm=False,
        )
    assert exc.value.status_code == 428

    result = batch_publish_assignments(
        AssignmentBatchPublishRequest(assignment_ids=[draft_a.id, draft_b.id], dry_run=False),
        teacher, db, confirm=True,
    )
    assert result.affected == [draft_a.id, draft_b.id]
    assert db.get(Assignment, draft_a.id).status == "published"
    assert db.get(Assignment, draft_b.id).status == "published"
    notes = db.query(Notification).filter_by(user_id=3, source_type="assignment").all()
    assert sorted(n.source_id for n in notes) == sorted([str(draft_a.id), str(draft_b.id)])

    preview2 = batch_publish_assignments(
        AssignmentBatchPublishRequest(assignment_ids=[published.id, 9999, foreign.id]),
        teacher, db,
    )
    assert preview2.affected == []
    assert {e.id: e.reason for e in preview2.skipped} == {
        published.id: "作业已发布",
        foreign.id: "只能操作自己发布的作业",
    }
    assert [(e.id, e.reason) for e in preview2.failed] == [(9999, "作业不存在")]


def test_remind_targets_unsubmitted_students(db):
    assignment = _publish(db, course_id=10, due_days=3)
    db.query(Notification).delete()  # 清掉 _publish 自动写入的通知
    db.commit()
    teacher = db.get(User, 1)

    preview = remind_assignment(assignment.id, AssignmentRemindRequest(), teacher, db)
    assert preview.dry_run is True
    assert preview.affected == [3]
    assert db.query(Notification).count() == 0

    result = remind_assignment(
        assignment.id, AssignmentRemindRequest(dry_run=False, message="请尽快提交"), teacher, db,
    )
    assert result.affected == [3]
    notes = db.query(Notification).filter_by(user_id=3, category="assignment").all()
    assert len(notes) == 1
    assert notes[0].message == "请尽快提交"

    submit_assignment(assignment.id, SubmissionCreate(content="已提交"), db.get(User, 3), db)
    assert remind_assignment(
        assignment.id, AssignmentRemindRequest(), teacher, db,
    ).affected == []


def test_remind_skips_students_with_disabled_category(db):
    assignment = _publish(db, course_id=10, due_days=3)
    db.query(Notification).delete()
    db.add(NotificationPreference(user_id=3, assignment_enabled=False))
    db.commit()

    result = remind_assignment(
        assignment.id, AssignmentRemindRequest(dry_run=False), db.get(User, 1), db,
    )
    assert result.affected == []
    assert [(e.id, e.reason) for e in result.skipped] == [(3, "学生已关闭作业通知")]


def test_teacher_feedback_requires_submission_and_confirmation(db):
    assignment = _publish(db, course_id=10, due_days=3)
    teacher = db.get(User, 1)
    student = db.get(User, 3)

    with pytest.raises(HTTPException) as exc:
        give_student_feedback(
            3, StudentFeedbackRequest(assignment_id=assignment.id, score=90), teacher, db,
        )
    assert exc.value.status_code == 404

    submit_assignment(
        assignment.id, SubmissionCreate(content="草稿", draft=True), student, db,
    )
    with pytest.raises(HTTPException) as exc:
        give_student_feedback(
            3, StudentFeedbackRequest(assignment_id=assignment.id, score=90), teacher, db,
        )
    assert exc.value.status_code == 400

    submit_assignment(assignment.id, SubmissionCreate(content="正式作答"), student, db)
    with pytest.raises(HTTPException) as exc:
        give_student_feedback(
            3,
            StudentFeedbackRequest(assignment_id=assignment.id, score=90, feedback="不错"),
            teacher, db,
        )
    assert exc.value.status_code == 428

    result = give_student_feedback(
        3, StudentFeedbackRequest(assignment_id=assignment.id, score=90, feedback="不错"),
        teacher, db, confirm=True,
    )
    assert result["score"] == 90 and result["feedback"] == "不错"
    sub = db.query(Submission).filter_by(assignment_id=assignment.id).one()
    assert sub.score == 90
    assert sub.feedback == "不错"
    assert sub.confirmed_at is not None
    assert sub.confirmed_by == teacher.id


def test_publish_course_announcement_to_course_classes(db):
    result = publish_course_announcement(
        10, CourseAnnouncementRequest(content="  下周停课一次  "), db.get(User, 1), db,
    )
    assert result["count"] == 1
    assert result["announcements"][0]["class_id"] == 20
    row = db.query(ClassAnnouncement).one()
    assert row.content == "下周停课一次"
    assert row.author_id == 1

    with pytest.raises(HTTPException) as exc:
        publish_course_announcement(
            10, CourseAnnouncementRequest(content="   "), db.get(User, 1), db,
        )
    assert exc.value.status_code == 400

    with pytest.raises(HTTPException) as exc:
        publish_course_announcement(
            10, CourseAnnouncementRequest(content="越权公告"), db.get(User, 2), db,
        )
    assert exc.value.status_code == 403

    with pytest.raises(HTTPException) as exc:
        publish_course_announcement(
            999, CourseAnnouncementRequest(content="不存在"), db.get(User, 1), db,
        )
    assert exc.value.status_code == 404
