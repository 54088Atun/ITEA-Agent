"""题库、AI 出题草稿与在线考试

覆盖:
- 题目校验与归属校验
- AI 出题草稿采纳入库,重复采纳被拒
- 组卷仅支持客观题、分值合计、重复题目拒绝
- 学生可见性、答案截止前不下发、客观题自动判分、禁止重复提交
- 教师结果统计、关闭后答案与解析展示
"""
import asyncio
from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.api.exams as exams_api
from app.api.exams import (
    adopt_question_draft, ai_grade_exam_record, close_exam, confirm_short_scores,
    create_exam, create_question, create_question_drafts, exam_heartbeat,
    exam_results, get_exam, get_exam_record, get_my_exam, list_my_exams,
    list_questions, start_exam, submit_exam,
)
from app.db.session import Base
from app.models.classroom import ClassMember, Classroom, CourseEnrollment
from app.models.course import Course, KnowledgePoint
from app.models.exam import Exam, ExamSession
from app.models.log import SystemConfig
from app.models.question import Question
from app.models.profile import MasteryRecord, ReviewPlan, StudentProfile, WrongQuestion
from app.models.user import User
from app.schemas.exam import (
    DraftAdoptRequest, DraftGenerateRequest, ExamCreate, ExamHeartbeat,
    ExamQuestionItem, ExamSubmit, QuestionCreate, ShortGradeConfirm,
)
from app.services.feature_flags import seed_defaults


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
    other_course = Course(id=11, teacher_id=2, name="Web 开发", code="WEB101",
                          audit_status="approved")
    kp = KnowledgePoint(id=30, course_id=10, name="等价类划分")
    classroom = Classroom(id=20, teacher_id=1, course_id=10, name="测试 1 班",
                          invite_code="ABCD1234")
    db.add_all([teacher, other, student, outsider, course, other_course, kp, classroom])
    db.add(ClassMember(class_id=20, student_id=3, status="active"))
    db.add(CourseEnrollment(course_id=10, student_id=3, source="class", class_id=20))
    db.commit()


def _make_question(db, **kwargs):
    payload = {
        "course_id": 10,
        "type": "single",
        "stem": "等价类划分的核心是？",
        "options": [
            {"key": "A", "text": "划分有效与无效等价类"},
            {"key": "B", "text": "穷举所有输入"},
        ],
        "answer": "A",
        "analysis": "关注等价类代表值",
        "difficulty": 2,
    }
    payload.update(kwargs)
    return create_question(QuestionCreate(**payload), db.get(User, 1), db)


def _make_exam(db, publish=True, due_days=3, **kwargs):
    single = _make_question(db)
    multi = _make_question(
        db, type="multiple",
        stem="以下属于黑盒测试方法的有？",
        options=[
            {"key": "A", "text": "等价类划分"},
            {"key": "B", "text": "边界值分析"},
            {"key": "C", "text": "语句覆盖"},
        ],
        answer="A,B",
    )
    items = [ExamQuestionItem(question_id=single["id"], score=5),
             ExamQuestionItem(question_id=multi["id"], score=10)]
    data = ExamCreate(title="第一次测验", course_id=10, class_id=20,
                      duration_minutes=45, due_days=due_days, questions=items,
                      publish=publish)
    for k, v in kwargs.items():
        setattr(data, k, v)
    return create_exam(data, db.get(User, 1), db), single, multi


def test_question_validation_and_ownership(db):
    with pytest.raises(HTTPException) as exc:
        _make_question(db, options=[{"key": "A", "text": "唯一"}])
    assert exc.value.status_code == 400

    q = _make_question(db)
    assert q["type"] == "single"
    multi = _make_question(db, type="multiple", answer="b,a",
                           options=[{"key": "A", "text": "x"}, {"key": "B", "text": "y"}])
    assert multi["answer"] == "A,B"

    with pytest.raises(HTTPException) as exc:
        create_question(QuestionCreate(**{
            "course_id": 10, "type": "single", "stem": "越权", "answer": "A",
            "options": [{"key": "A", "text": "x"}, {"key": "B", "text": "y"}],
        }), db.get(User, 2), db)
    assert exc.value.status_code == 403

    assert len(list_questions(10, None, None, 100, db.get(User, 1), db)) == 2


def test_ai_draft_adopt(db, monkeypatch):
    async def fake_generate(*args, **kwargs):
        return [
            {"type": "single", "stem": "AI 题 1", "options": [
                {"key": "A", "text": "正确"}, {"key": "B", "text": "错误"}],
             "answer": "A", "analysis": "解析", "difficulty": 2},
            {"type": "single", "stem": "", "options": [], "answer": "A"},  # 非法,应被丢弃
        ]

    monkeypatch.setattr(exams_api, "generate_questions", fake_generate)
    draft = asyncio.run(create_question_drafts(
        10, DraftGenerateRequest(count=2), db.get(User, 1), db,
    ))
    assert len(draft["items"]) == 1

    result = adopt_question_draft(
        draft["id"], DraftAdoptRequest(adopt_all=True), db.get(User, 1), db,
    )
    assert result["created"] == 1
    q = db.query(Question).filter(Question.source == "agent").first()
    assert q is not None and q.stem == "AI 题 1"

    with pytest.raises(HTTPException) as exc:
        adopt_question_draft(draft["id"], DraftAdoptRequest(adopt_all=True),
                             db.get(User, 1), db)
    assert exc.value.status_code == 400

    with pytest.raises(HTTPException) as exc:
        adopt_question_draft(draft["id"], DraftAdoptRequest(adopt_all=True),
                             db.get(User, 2), db)
    assert exc.value.status_code == 403


def test_exam_assembly_rules(db):
    short = _make_question(db, type="short", stem="简述等价类", options=[], answer="文本答案")
    single = _make_question(db)
    mixed = create_exam(ExamCreate(title="含简答", course_id=10, questions=[
        ExamQuestionItem(question_id=single["id"], score=5),
        ExamQuestionItem(question_id=short["id"], score=10),
    ]), db.get(User, 1), db)
    assert mixed["total_score"] == 15
    assert mixed["question_count"] == 2

    with pytest.raises(HTTPException) as exc:
        create_exam(ExamCreate(title="重复题", course_id=10, questions=[
            ExamQuestionItem(question_id=single["id"], score=5),
            ExamQuestionItem(question_id=single["id"], score=5)]), db.get(User, 1), db)
    assert exc.value.status_code == 400

    exam, _, _ = _make_exam(db)
    assert exam["total_score"] == 15
    assert exam["question_count"] == 2
    assert exam["status"] == "published"

    with pytest.raises(HTTPException) as exc:
        get_exam(exam["id"], db.get(User, 2), db)
    assert exc.value.status_code == 403


def test_student_visibility_and_autograding(db):
    draft_exam, _, _ = _make_exam(db, publish=False)
    student = db.get(User, 3)
    assert list_my_exams(student, db) == []
    with pytest.raises(HTTPException) as exc:
        get_my_exam(draft_exam["id"], student, db)
    assert exc.value.status_code == 403

    exam, single, multi = _make_exam(db)
    assert [e["id"] for e in list_my_exams(student, db)] == [exam["id"]]
    assert list_my_exams(db.get(User, 4), db) == []
    with pytest.raises(HTTPException) as exc:
        get_my_exam(exam["id"], db.get(User, 4), db)
    assert exc.value.status_code == 403

    detail = get_my_exam(exam["id"], student, db)
    assert detail["reveal_answers"] is False
    assert all("answer" not in q for q in detail["questions"])

    start_exam(exam["id"], student, db)
    result = submit_exam(
        exam["id"],
        ExamSubmit(answers={str(single["id"]): "A", str(multi["id"]): "A"}),
        student, db,
    )
    assert result["score"] == 10
    assert result["correct_count"] == 1
    assert result["question_count"] == 2

    with pytest.raises(HTTPException) as exc:
        submit_exam(exam["id"], ExamSubmit(answers={}), student, db)
    assert exc.value.status_code == 400

    after = get_my_exam(exam["id"], student, db)
    assert after["my_record"]["score"] == 10
    assert after["reveal_answers"] is False
    assert len(after["results"]) == 2
    assert after["results"][0]["correct"] is True
    assert after["results"][1]["awarded"] == 5
    assert after["results"][1]["correct"] is False

    results = exam_results(exam["id"], db.get(User, 1), db)
    assert results["submission_count"] == 1
    assert results["items"][0]["score"] == 10
    assert results["items"][0]["student_name"] == "小明"


def test_multiple_partial_credit_rules(db):
    """多选无错选按比例给分,有错选则零分,全对才计入正确题数"""
    partial = _make_question(db, type="multiple", stem="部分正确", options=[
        {"key": "A", "text": "正确 1"}, {"key": "B", "text": "正确 2"},
        {"key": "C", "text": "干扰项"},
    ], answer="A,B")
    wrong = _make_question(db, type="multiple", stem="存在错选", options=[
        {"key": "A", "text": "正确 1"}, {"key": "B", "text": "正确 2"},
        {"key": "C", "text": "干扰项"},
    ], answer="A,B")
    exact = _make_question(db, type="multiple", stem="完全正确", options=[
        {"key": "A", "text": "正确 1"}, {"key": "B", "text": "正确 2"},
        {"key": "C", "text": "干扰项"},
    ], answer="A,B")
    exam = create_exam(ExamCreate(
        title="多选给分", course_id=10, class_id=20, duration_minutes=30,
        questions=[ExamQuestionItem(question_id=q["id"], score=10)
                   for q in (partial, wrong, exact)],
    ), db.get(User, 1), db)
    student = db.get(User, 3)
    start_exam(exam["id"], student, db)
    result = submit_exam(exam["id"], ExamSubmit(answers={
        str(partial["id"]): "A",
        str(wrong["id"]): "A,C",
        str(exact["id"]): "B,A",
    }), student, db)

    assert result["score"] == 15
    assert result["correct_count"] == 1
    detail = get_my_exam(exam["id"], student, db)
    assert [r["awarded"] for r in detail["results"]] == [5, 0, 10]
    assert [r["correct"] for r in detail["results"]] == [False, False, True]


def test_answers_revealed_after_close(db):
    exam, _, _ = _make_exam(db)
    student = db.get(User, 3)
    start_exam(exam["id"], student, db)
    submit_exam(exam["id"], ExamSubmit(answers={}), student, db)
    close_exam(exam["id"], db.get(User, 1), db, confirm=True)

    detail = get_my_exam(exam["id"], student, db)
    assert detail["reveal_answers"] is True
    assert all("answer" in q for q in detail["questions"])
    assert detail["questions"][0]["analysis"]


def test_exam_deadline_and_feature_switch(db):
    exam, single, _ = _make_exam(db)
    student = db.get(User, 3)
    start_exam(exam["id"], student, db)

    session = db.query(ExamSession).filter_by(exam_id=exam["id"], student_id=student.id).first()
    session.deadline_at = datetime.utcnow() - timedelta(minutes=2)
    db.commit()
    with pytest.raises(HTTPException) as exc:
        submit_exam(exam["id"], ExamSubmit(answers={str(single["id"]): "A"}), student, db)
    assert exc.value.status_code == 400
    assert "超时" in exc.value.detail

    cfg = db.query(SystemConfig).filter_by(config_key="feature_exams").first()
    cfg.config_value = "off"
    db.commit()
    with pytest.raises(HTTPException) as exc:
        create_exam(ExamCreate(title="关闭期", course_id=10, questions=[
            ExamQuestionItem(question_id=single["id"], score=5)]), db.get(User, 1), db)
    assert exc.value.status_code == 403
    with pytest.raises(HTTPException) as exc:
        submit_exam(exam["id"], ExamSubmit(answers={}), student, db)
    assert exc.value.status_code == 403


def test_short_answer_grading_and_violations(db, monkeypatch):
    """简答题人工确认评分 + 服务端计时/切屏计数"""
    single = _make_question(db)
    short = _make_question(
        db, type="short", stem="简述边界值分析", options=[], answer="边界及两侧取值",
    )
    exam = create_exam(ExamCreate(
        title="简答测验", course_id=10, class_id=20, duration_minutes=30, due_days=3,
        questions=[
            ExamQuestionItem(question_id=single["id"], score=10),
            ExamQuestionItem(question_id=short["id"], score=20),
        ],
        publish=True,
    ), db.get(User, 1), db)
    student = db.get(User, 3)

    with pytest.raises(HTTPException) as exc:
        submit_exam(exam["id"], ExamSubmit(answers={}), student, db)
    assert "开始考试" in exc.value.detail

    started = start_exam(exam["id"], student, db)
    assert started["remaining_seconds"] > 0
    again = start_exam(exam["id"], student, db)
    assert again["started_at"] == started["started_at"]

    heartbeat = exam_heartbeat(exam["id"], ExamHeartbeat(violations=2), student, db)
    assert heartbeat["violations"] == 2

    result = submit_exam(
        exam["id"],
        ExamSubmit(answers={
            str(single["id"]): "A",
            str(short["id"]): "边界值分析关注边界及两侧取值",
        }, violations=3),
        student, db,
    )
    assert result["score"] == 10
    assert result["pending_manual"] == 1
    assert result["violations"] == 3

    detail = get_my_exam(exam["id"], student, db)
    assert detail["my_record"]["score"] == 10
    assert detail["my_record"]["pending_manual"] == 1
    short_res = next(r for r in detail["results"] if r["question_id"] == short["id"])
    assert short_res["awarded"] is None

    results = exam_results(exam["id"], db.get(User, 1), db)
    item = results["items"][0]
    assert item["pending_manual"] == 1
    assert item["violations"] == 3
    record_id = item["record_id"]

    teacher_view = get_exam_record(record_id, db.get(User, 1), db)
    assert teacher_view["pending_manual"] == 1
    assert teacher_view["questions"][1]["my_answer"] == "边界值分析关注边界及两侧取值"

    async def fake_grade(*args, **kwargs):
        return {"score": 75, "feedback": "AI 建议", "source": "rule"}

    monkeypatch.setattr(exams_api, "grade_submission", fake_grade)
    graded = asyncio.run(ai_grade_exam_record(record_id, db.get(User, 1), db))
    assert graded["suggestions"][str(short["id"])]["score"] == 15

    # AI 建议不生效
    assert get_my_exam(exam["id"], student, db)["my_record"]["score"] == 10

    with pytest.raises(HTTPException) as exc:
        confirm_short_scores(
            record_id, ShortGradeConfirm(scores={str(short["id"]): 18}),
            db.get(User, 2), db,
        )
    assert exc.value.status_code == 403

    confirmed = confirm_short_scores(
        record_id, ShortGradeConfirm(scores={str(short["id"]): 18}),
        db.get(User, 1), db,
    )
    assert confirmed["score"] == 28
    assert confirmed["pending_manual"] == 0

    detail = get_my_exam(exam["id"], student, db)
    assert detail["my_record"]["score"] == 28
    short_res = next(r for r in detail["results"] if r["question_id"] == short["id"])
    assert short_res["awarded"] == 18


def test_client_exclusivity_and_clipboard_monitoring(db):
    """同一考试仅允许绑定客户端作答,复制粘贴次数取历次上报峰值"""
    exam, single, _ = _make_exam(db)
    student = db.get(User, 3)

    started = start_exam(exam["id"], student, db, client_id="browser-a")
    assert started["client_id"] == "browser-a"
    assert started["copy_count"] == 0
    assert started["paste_count"] == 0

    with pytest.raises(HTTPException) as exc:
        start_exam(exam["id"], student, db, client_id="browser-b")
    assert exc.value.status_code == 409

    with pytest.raises(HTTPException) as exc:
        exam_heartbeat(exam["id"], ExamHeartbeat(client_id="browser-b"), student, db)
    assert exc.value.status_code == 409

    heartbeat = exam_heartbeat(exam["id"], ExamHeartbeat(
        client_id="browser-a", violations=1, copy_count=2, paste_count=1,
    ), student, db)
    assert heartbeat["copy_count"] == 2
    assert heartbeat["paste_count"] == 1

    with pytest.raises(HTTPException) as exc:
        submit_exam(exam["id"], ExamSubmit(
            answers={str(single["id"]): "A"}, client_id="browser-b",
        ), student, db)
    assert exc.value.status_code == 409

    result = submit_exam(exam["id"], ExamSubmit(
        answers={str(single["id"]): "A"}, client_id="browser-a",
        violations=2, copy_count=4, paste_count=3,
    ), student, db)
    assert result["copy_count"] == 4
    assert result["paste_count"] == 3

    detail = get_my_exam(exam["id"], student, db)
    assert detail["my_record"]["copy_count"] == 4
    assert detail["my_record"]["paste_count"] == 3
    teacher_item = exam_results(exam["id"], db.get(User, 1), db)["items"][0]
    assert teacher_item["copy_count"] == 4
    assert teacher_item["paste_count"] == 3


def test_exam_wrong_questions_reflow_idempotently(db):
    """客观题提交、简答题确认后回流失分题,重复确认不重复写入"""
    single = _make_question(db, kp_id=30)
    short = _make_question(
        db, kp_id=30, type="short", stem="简述测试原则", options=[], answer="参考原则",
    )
    exam = create_exam(ExamCreate(
        title="错题回流", course_id=10, class_id=20, duration_minutes=30,
        questions=[
            ExamQuestionItem(question_id=single["id"], score=10),
            ExamQuestionItem(question_id=short["id"], score=20),
        ],
    ), db.get(User, 1), db)
    student = db.get(User, 3)
    start_exam(exam["id"], student, db)
    submit_exam(exam["id"], ExamSubmit(answers={
        str(single["id"]): "B", str(short["id"]): "我的回答",
    }), student, db)

    profile = db.query(StudentProfile).filter_by(user_id=student.id, course_id=10).one()
    wrongs = db.query(WrongQuestion).filter_by(profile_id=profile.id).all()
    assert len(wrongs) == 1
    assert wrongs[0].source_type == "exam_record"
    assert wrongs[0].source_id.endswith(f":{single['id']}")
    assert "参考原则" not in wrongs[0].question_content
    assert db.query(ReviewPlan).filter_by(wrong_question_id=wrongs[0].id).count() == 1
    mastery = db.query(MasteryRecord).filter_by(profile_id=profile.id, kp_id=30).one()
    assert mastery.mastery_level == 90

    record_id = exam_results(exam["id"], db.get(User, 1), db)["items"][0]["record_id"]
    confirm_short_scores(
        record_id, ShortGradeConfirm(scores={str(short["id"]): 10}), db.get(User, 1), db,
    )
    assert db.query(WrongQuestion).filter_by(profile_id=profile.id).count() == 2
    assert db.query(ReviewPlan).join(WrongQuestion).filter(
        WrongQuestion.profile_id == profile.id
    ).count() == 2
    db.refresh(mastery)
    assert mastery.mastery_level == 80

    confirm_short_scores(
        record_id, ShortGradeConfirm(scores={str(short["id"]): 10}), db.get(User, 1), db,
    )
    assert db.query(WrongQuestion).filter_by(profile_id=profile.id).count() == 2
    assert db.query(ReviewPlan).join(WrongQuestion).filter(
        WrongQuestion.profile_id == profile.id
    ).count() == 2
    db.refresh(mastery)
    assert mastery.mastery_level == 80
