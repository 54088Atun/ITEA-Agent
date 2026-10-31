"""题库、AI 出题草稿与在线考试

口径:
- 题目与试卷均归属教师,只能操作自己的课程
- AI 出题只写草稿,教师勾选采纳后才入库
- 组卷仅支持客观题(单选/多选/判断),提交后自动判分
- 学生仅能看到已发布且命中班级/课程的试卷;答案与解析在截止或关闭后才展示
"""
import json
import logging
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from app.core.deps import require_student, require_teacher
from app.db.session import get_db
from app.models.classroom import ClassMember, Classroom, CourseEnrollment
from app.models.course import Course, KnowledgePoint
from app.models.exam import Exam, ExamQuestion, ExamRecord, ExamSession
from app.models.profile import MasteryRecord, ReviewPlan, StudentProfile, WrongQuestion
from app.models.question import Question, QuestionDraft
from app.models.user import User
from app.schemas.exam import (
    DraftAdoptRequest, DraftGenerateRequest, ExamCreate, ExamHeartbeat, ExamSubmit,
    QuestionCreate, ShortGradeConfirm,
)
from app.services.feature_flags import is_enabled
from app.services.grader import grade_submission
from app.services.notifications import notify_task_students
from app.services.question_generator import generate_questions

logger = logging.getLogger(__name__)
router = APIRouter(tags=["题库与考试"])

OBJECTIVE_TYPES = {"single", "multiple", "judge"}
ALL_TYPES = OBJECTIVE_TYPES | {"short"}
TRUE_SET = {"TRUE", "T", "1", "对", "正确", "是"}
FALSE_SET = {"FALSE", "F", "0", "错", "错误", "否"}


# ---------- 标准化与序列化 ----------

def _clean_options(raw) -> list[dict]:
    options = []
    for item in raw or []:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "").strip()
        text = str(item.get("text") or "").strip()
        if key and text:
            options.append({"key": key[:10].upper(), "text": text[:500]})
    return options


def _normalize_question(raw) -> dict:
    """校验并标准化题目;非法抛 ValueError"""
    qtype = str(raw.get("type") or "single").strip().lower()
    if qtype not in ALL_TYPES:
        raise ValueError("题型不合法")
    stem = str(raw.get("stem") or "").strip()[:5000]
    if not stem:
        raise ValueError("题干不能为空")

    try:
        difficulty = int(raw.get("difficulty") or 3)
    except (TypeError, ValueError):
        difficulty = 3
    difficulty = max(1, min(5, difficulty))

    options = _clean_options(raw.get("options"))
    answer = str(raw.get("answer") or "").strip()

    if qtype == "judge":
        if not options:
            options = [{"key": "TRUE", "text": "正确"}, {"key": "FALSE", "text": "错误"}]
        if answer.upper() in TRUE_SET:
            answer = "true"
        elif answer.upper() in FALSE_SET:
            answer = "false"
        else:
            raise ValueError("判断题答案应为 true/false")
    elif qtype == "single":
        if len(options) < 2:
            raise ValueError("单选题至少需要 2 个选项")
        keys = {o["key"] for o in options}
        answer = answer.upper()
        if answer not in keys:
            raise ValueError("单选答案不在选项内")
    elif qtype == "multiple":
        if len(options) < 2:
            raise ValueError("多选题至少需要 2 个选项")
        keys = {o["key"] for o in options}
        parts = [p.strip().upper() for p in answer.replace("，", ",").split(",") if p.strip()]
        if not parts or any(p not in keys for p in parts):
            raise ValueError("多选答案不在选项内")
        answer = ",".join(sorted(set(parts)))
    else:
        options = []
        if not answer:
            raise ValueError("简答题答案不能为空")

    return {
        "type": qtype,
        "stem": stem,
        "options": options,
        "answer": answer[:2000],
        "analysis": str(raw.get("analysis") or "").strip()[:2000],
        "difficulty": difficulty,
    }


def _q_out(q: Question, with_answer: bool) -> dict:
    data = {
        "id": q.id,
        "course_id": q.course_id,
        "kp_id": q.kp_id,
        "type": q.type,
        "stem": q.stem,
        "options": json.loads(q.options) if q.options else [],
        "difficulty": q.difficulty,
        "source": q.source,
        "status": q.status,
        "created_at": q.created_at,
    }
    if with_answer:
        data["answer"] = q.answer
        data["analysis"] = q.analysis
    return data


def _norm_given(q: Question, given: str) -> str:
    value = (given or "").strip()
    if q.type == "judge":
        upper = value.upper()
        if upper in TRUE_SET or value in TRUE_SET:
            return "true"
        if upper in FALSE_SET or value in FALSE_SET:
            return "false"
        return upper.lower()
    if q.type == "multiple":
        parts = [p.strip().upper() for p in value.replace("，", ",").split(",") if p.strip()]
        return ",".join(sorted(set(parts)))
    return value.upper()


def _grade_objective(q: Question, given: str, full_score: int) -> tuple[int, bool]:
    """客观题计分:多选无错选按比例给分,全对才计为正确"""
    normalized = _norm_given(q, given)
    expected = _norm_given(q, q.answer)
    if q.type != "multiple":
        ok = normalized == expected
        return (full_score if ok else 0), ok

    selected = set(normalized.split(",")) if normalized else set()
    answers = set(expected.split(",")) if expected else set()
    ok = selected == answers
    if not selected or not selected.issubset(answers):
        return 0, False
    if ok:
        return full_score, True
    return round(full_score * len(selected) / len(answers)), False


# ---------- 权限 ----------

def _owned_course(db: Session, course_id: int, teacher: User) -> Course:
    course = db.query(Course).filter(Course.id == course_id).first()
    if not course:
        raise HTTPException(status_code=404, detail="课程不存在")
    if teacher.role != "admin" and course.teacher_id != teacher.id:
        raise HTTPException(status_code=403, detail="只能操作自己的课程")
    return course


def _owned_question(db: Session, question_id: int, teacher: User) -> Question:
    q = db.query(Question).filter(Question.id == question_id).first()
    if not q:
        raise HTTPException(status_code=404, detail="题目不存在")
    if teacher.role != "admin" and q.teacher_id != teacher.id:
        raise HTTPException(status_code=403, detail="只能操作自己的题目")
    return q


def _owned_draft(db: Session, draft_id: int, teacher: User) -> QuestionDraft:
    draft = db.query(QuestionDraft).filter(QuestionDraft.id == draft_id).first()
    if not draft:
        raise HTTPException(status_code=404, detail="草稿不存在")
    if teacher.role != "admin" and draft.teacher_id != teacher.id:
        raise HTTPException(status_code=403, detail="只能操作自己的草稿")
    return draft


def _owned_exam(db: Session, exam_id: int, teacher: User) -> Exam:
    exam = db.query(Exam).filter(Exam.id == exam_id).first()
    if not exam:
        raise HTTPException(status_code=404, detail="试卷不存在")
    if teacher.role != "admin" and exam.teacher_id != teacher.id:
        raise HTTPException(status_code=403, detail="只能操作自己的试卷")
    return exam


def _student_conditions(db: Session, student: User):
    class_ids = [
        cid for (cid,) in db.query(ClassMember.class_id).filter(
            ClassMember.student_id == student.id,
            ClassMember.status == "active",
        ).all()
    ]
    course_ids = [
        cid for (cid,) in db.query(CourseEnrollment.course_id).filter(
            CourseEnrollment.student_id == student.id,
        ).all()
    ]
    conditions = []
    if class_ids:
        conditions.append(Exam.class_id.in_(class_ids))
    if course_ids:
        conditions.append(and_(
            Exam.class_id.is_(None),
            Exam.course_id.in_(course_ids),
        ))
    return conditions


def _visible_exam(
    db: Session, exam_id: int, student: User, allow_closed: bool = False,
) -> Exam:
    exam = db.query(Exam).filter(Exam.id == exam_id).first()
    if not exam:
        raise HTTPException(status_code=404, detail="试卷不存在")
    allowed_status = ("published", "closed") if allow_closed else ("published",)
    if exam.status not in allowed_status:
        raise HTTPException(status_code=403, detail="试卷未发布或已关闭")
    conditions = _student_conditions(db, student)
    if not conditions or not db.query(Exam).filter(
        Exam.id == exam_id, or_(*conditions)
    ).first():
        raise HTTPException(status_code=403, detail="无权查看该试卷")
    return exam


def _due_passed(exam: Exam) -> bool:
    return bool(exam.due_at and exam.due_at < datetime.utcnow())


# ---------- 题库 ----------

@router.post("/teacher/questions")
def create_question(
    req: QuestionCreate,
    teacher: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    """手动新增题目"""
    _owned_course(db, req.course_id, teacher)
    if req.kp_id is not None:
        kp = db.query(KnowledgePoint).filter(
            KnowledgePoint.id == req.kp_id,
            KnowledgePoint.course_id == req.course_id,
        ).first()
        if not kp:
            raise HTTPException(status_code=400, detail="知识点不属于该课程")
    try:
        norm = _normalize_question(req.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    q = Question(
        teacher_id=teacher.id,
        course_id=req.course_id,
        kp_id=req.kp_id,
        type=norm["type"],
        stem=norm["stem"],
        options=json.dumps(norm["options"], ensure_ascii=False),
        answer=norm["answer"],
        analysis=norm["analysis"] or None,
        difficulty=norm["difficulty"],
        source="manual",
        status="active",
    )
    db.add(q)
    db.commit()
    db.refresh(q)
    return _q_out(q, with_answer=True)


@router.get("/teacher/questions")
def list_questions(
    course_id: Optional[int] = Query(None),
    kp_id: Optional[int] = Query(None),
    type: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=300),
    teacher: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    query = db.query(Question).filter(Question.status == "active")
    if teacher.role != "admin":
        query = query.filter(Question.teacher_id == teacher.id)
    if course_id:
        _owned_course(db, course_id, teacher)
        query = query.filter(Question.course_id == course_id)
    if kp_id:
        query = query.filter(Question.kp_id == kp_id)
    if type:
        query = query.filter(Question.type == type)
    rows = query.order_by(Question.id.desc()).limit(limit).all()
    return [_q_out(q, with_answer=True) for q in rows]


@router.put("/teacher/questions/{question_id}")
def update_question(
    question_id: int,
    req: QuestionCreate,
    teacher: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    q = _owned_question(db, question_id, teacher)
    _owned_course(db, req.course_id, teacher)
    try:
        norm = _normalize_question(req.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    q.course_id = req.course_id
    q.kp_id = req.kp_id
    q.type = norm["type"]
    q.stem = norm["stem"]
    q.options = json.dumps(norm["options"], ensure_ascii=False)
    q.answer = norm["answer"]
    q.analysis = norm["analysis"] or None
    q.difficulty = norm["difficulty"]
    db.commit()
    db.refresh(q)
    return _q_out(q, with_answer=True)


@router.delete("/teacher/questions/{question_id}")
def archive_question(
    question_id: int,
    teacher: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    """归档题目:不物理删除,避免破坏已组好的试卷"""
    q = _owned_question(db, question_id, teacher)
    q.status = "archived"
    db.commit()
    return {"id": q.id, "status": q.status}


# ---------- AI 出题草稿 ----------

@router.post("/teacher/courses/{course_id}/question-drafts")
async def create_question_drafts(
    course_id: int,
    req: DraftGenerateRequest,
    teacher: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    """按课程/知识点生成题目草稿(不直接入库)"""
    course = _owned_course(db, course_id, teacher)
    if not is_enabled(db, "feature_exams"):
        raise HTTPException(status_code=403, detail="题库功能已关闭")

    kp_query = db.query(KnowledgePoint.name).filter(
        KnowledgePoint.course_id == course_id
    )
    if req.kp_ids:
        kp_query = kp_query.filter(KnowledgePoint.id.in_(req.kp_ids))
    points = [name for (name,) in kp_query.limit(20).all()]

    raw_items = await generate_questions(course.name, points, req.count, req.types)
    items = []
    for raw in raw_items:
        try:
            items.append(_normalize_question(raw))
        except ValueError:
            continue
    if not items:
        raise HTTPException(status_code=502, detail="AI 出题失败，请重试")

    draft = QuestionDraft(
        teacher_id=teacher.id,
        course_id=course_id,
        kp_ids=",".join(str(i) for i in req.kp_ids) if req.kp_ids else None,
        payload=json.dumps(items, ensure_ascii=False),
        status="draft",
    )
    db.add(draft)
    db.commit()
    db.refresh(draft)
    return {"id": draft.id, "course_id": course_id, "status": draft.status, "items": items}


@router.get("/teacher/courses/{course_id}/question-drafts")
def list_question_drafts(
    course_id: int,
    teacher: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    _owned_course(db, course_id, teacher)
    rows = (
        db.query(QuestionDraft)
        .filter(QuestionDraft.course_id == course_id)
        .order_by(QuestionDraft.id.desc())
        .limit(20)
        .all()
    )
    return [
        {
            "id": r.id,
            "status": r.status,
            "created_at": r.created_at,
            "items": json.loads(r.payload),
        }
        for r in rows
    ]


@router.post("/teacher/question-drafts/{draft_id}/adopt")
def adopt_question_draft(
    draft_id: int,
    req: DraftAdoptRequest,
    teacher: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    """采纳草稿中的题目到题库"""
    draft = _owned_draft(db, draft_id, teacher)
    if draft.status == "adopted":
        raise HTTPException(status_code=400, detail="该草稿已采纳")
    items = json.loads(draft.payload)
    if req.adopt_all:
        selected = list(range(len(items)))
    else:
        selected = [i for i in req.indices if 0 <= i < len(items)]
    if not selected:
        raise HTTPException(status_code=400, detail="请选择要采纳的题目")

    created = 0
    for idx in selected:
        raw = items[idx]
        try:
            norm = _normalize_question(raw)
        except ValueError:
            continue
        db.add(Question(
            teacher_id=teacher.id,
            course_id=draft.course_id,
            kp_id=None,
            type=norm["type"],
            stem=norm["stem"],
            options=json.dumps(norm["options"], ensure_ascii=False),
            answer=norm["answer"],
            analysis=norm["analysis"] or None,
            difficulty=norm["difficulty"],
            source="agent",
            status="active",
        ))
        created += 1

    draft.status = "adopted"
    db.commit()
    return {"draft_id": draft.id, "created": created, "status": draft.status}


@router.delete("/teacher/question-drafts/{draft_id}")
def discard_question_draft(
    draft_id: int,
    teacher: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    draft = _owned_draft(db, draft_id, teacher)
    draft.status = "discarded"
    db.commit()
    return {"draft_id": draft.id, "status": draft.status}


# ---------- 试卷 ----------

def _exam_summary(exam: Exam, question_count: int, submission_count: int = 0) -> dict:
    return {
        "id": exam.id,
        "title": exam.title,
        "course_id": exam.course_id,
        "class_id": exam.class_id,
        "description": exam.description,
        "duration_minutes": exam.duration_minutes,
        "start_at": exam.start_at,
        "due_at": exam.due_at,
        "status": exam.status,
        "total_score": exam.total_score,
        "question_count": question_count,
        "submission_count": submission_count,
        "created_at": exam.created_at,
    }


@router.post("/teacher/exams")
def create_exam(
    req: ExamCreate,
    teacher: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    """组卷:选择题目并设置分值,可直接发布或存草稿"""
    if not is_enabled(db, "feature_exams"):
        raise HTTPException(status_code=403, detail="考试功能已关闭")
    _owned_course(db, req.course_id, teacher)
    if req.class_id:
        classroom = db.query(Classroom).filter(Classroom.id == req.class_id).first()
        if not classroom:
            raise HTTPException(status_code=404, detail="班级不存在")
        if teacher.role != "admin" and classroom.teacher_id != teacher.id:
            raise HTTPException(status_code=403, detail="只能向自己的班级发布")
    if not req.questions:
        raise HTTPException(status_code=400, detail="请至少选择一道题目")

    qids = [item.question_id for item in req.questions]
    if len(qids) != len(set(qids)):
        raise HTTPException(status_code=400, detail="同一题目不能重复加入试卷")

    questions = db.query(Question).filter(Question.id.in_(qids)).all()
    qmap = {q.id: q for q in questions}
    if len(qmap) != len(qids):
        raise HTTPException(status_code=404, detail="部分题目不存在")
    for q in questions:
        if teacher.role != "admin" and q.teacher_id != teacher.id:
            raise HTTPException(status_code=403, detail="只能使用自己的题目")
        if q.course_id != req.course_id:
            raise HTTPException(status_code=400, detail="题目不属于该课程")
        if q.status != "active":
            raise HTTPException(status_code=400, detail="已归档题目不能组卷")

    due_at = None
    if req.due_days:
        due_at = datetime.utcnow() + timedelta(days=req.due_days)

    exam = Exam(
        teacher_id=teacher.id,
        course_id=req.course_id,
        class_id=req.class_id,
        title=req.title.strip()[:120],
        description=req.description,
        duration_minutes=req.duration_minutes,
        start_at=req.start_at,
        due_at=due_at,
        total_score=sum(item.score for item in req.questions),
        status="published" if req.publish else "draft",
    )
    db.add(exam)
    db.flush()
    for index, item in enumerate(req.questions):
        db.add(ExamQuestion(
            exam_id=exam.id,
            question_id=item.question_id,
            score=item.score,
            sort=index,
        ))
    if exam.status == "published":
        notify_task_students(
            db, "exam", exam.id, exam.title, exam.course_id, exam.class_id,
            f"/student/exams?exam_id={exam.id}",
        )
    db.commit()
    db.refresh(exam)
    logger.info("试卷创建: %s (teacher=%s)", exam.title, teacher.id)
    return _exam_summary(exam, len(req.questions))


@router.get("/teacher/exams")
def list_exams(
    teacher: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    query = db.query(Exam)
    if teacher.role != "admin":
        query = query.filter(Exam.teacher_id == teacher.id)
    rows = query.order_by(Exam.id.desc()).limit(50).all()
    if not rows:
        return []

    ids = [e.id for e in rows]
    q_counts = dict(
        db.query(ExamQuestion.exam_id, func.count(ExamQuestion.id))
        .filter(ExamQuestion.exam_id.in_(ids))
        .group_by(ExamQuestion.exam_id)
        .all()
    )
    r_counts = dict(
        db.query(ExamRecord.exam_id, func.count(ExamRecord.id))
        .filter(ExamRecord.exam_id.in_(ids))
        .group_by(ExamRecord.exam_id)
        .all()
    )
    return [
        _exam_summary(e, q_counts.get(e.id, 0), r_counts.get(e.id, 0))
        for e in rows
    ]


def _exam_question_rows(db: Session, exam_id: int):
    return (
        db.query(ExamQuestion, Question)
        .join(Question, ExamQuestion.question_id == Question.id)
        .filter(ExamQuestion.exam_id == exam_id)
        .order_by(ExamQuestion.sort.asc())
        .all()
    )


@router.get("/teacher/exams/{exam_id}")
def get_exam(
    exam_id: int,
    teacher: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    exam = _owned_exam(db, exam_id, teacher)
    rows = _exam_question_rows(db, exam_id)
    data = _exam_summary(
        exam, len(rows),
        db.query(ExamRecord).filter(ExamRecord.exam_id == exam.id).count(),
    )
    data["questions"] = [
        {**_q_out(q, with_answer=True), "score": eq.score, "sort": eq.sort}
        for eq, q in rows
    ]
    return data


@router.post("/teacher/exams/{exam_id}/publish")
def publish_exam(
    exam_id: int,
    teacher: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    if not is_enabled(db, "feature_exams"):
        raise HTTPException(status_code=403, detail="考试功能已关闭")
    exam = _owned_exam(db, exam_id, teacher)
    if not db.query(ExamQuestion).filter(ExamQuestion.exam_id == exam.id).first():
        raise HTTPException(status_code=400, detail="试卷没有题目，无法发布")
    exam.status = "published"
    notify_task_students(
        db, "exam", exam.id, exam.title, exam.course_id, exam.class_id,
        f"/student/exams?exam_id={exam.id}",
    )
    db.commit()
    return {"id": exam.id, "status": exam.status}


@router.post("/teacher/exams/{exam_id}/close")
def close_exam(
    exam_id: int,
    teacher: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    exam = _owned_exam(db, exam_id, teacher)
    exam.status = "closed"
    db.commit()
    return {"id": exam.id, "status": exam.status}


@router.get("/teacher/exams/{exam_id}/results")
def exam_results(
    exam_id: int,
    teacher: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    exam = _owned_exam(db, exam_id, teacher)
    rows = (
        db.query(ExamRecord, User)
        .join(User, ExamRecord.student_id == User.id)
        .filter(ExamRecord.exam_id == exam.id)
        .order_by(ExamRecord.total_score.desc())
        .all()
    )
    return {
        "exam_id": exam.id,
        "title": exam.title,
        "total_score": exam.total_score,
        "submission_count": len(rows),
        "items": [
            {
                "record_id": rec.id,
                "student_id": rec.student_id,
                "student_name": user.name,
                "score": rec.total_score,
                "correct_count": rec.correct_count,
                "question_count": rec.question_count,
                "pending_manual": 0 if rec.graded_at else _pending_manual_count(db, rec),
                "violations": rec.violations or 0,
                "copy_count": rec.copy_count or 0,
                "paste_count": rec.paste_count or 0,
                "timed_out": bool(rec.timed_out),
                "graded": rec.graded_at is not None,
                "submitted_at": rec.submitted_at,
            }
            for rec, user in rows
        ],
    }


def _pending_manual_count(db: Session, record: ExamRecord) -> int:
    """未批改的简答题数量"""
    short_ids = [
        qid for (qid,) in db.query(Question.id).join(
            ExamQuestion, ExamQuestion.question_id == Question.id
        ).filter(
            ExamQuestion.exam_id == record.exam_id,
            Question.type == "short",
        ).all()
    ]
    if not short_ids:
        return 0
    scored = _json_obj(record.short_scores)
    return sum(1 for qid in short_ids if str(qid) not in scored)


# ---------- 答卷详情与简答批改 ----------

def _json_obj(text) -> dict:
    try:
        data = json.loads(text or "{}")
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _owned_record(db: Session, record_id: int, teacher: User):
    record = db.query(ExamRecord).filter(ExamRecord.id == record_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="答卷不存在")
    exam = _owned_exam(db, record.exam_id, teacher)
    return record, exam


def _build_record_view(record: ExamRecord, rows, with_answer: bool) -> dict:
    """按题目组装作答详情:客观题自动判分,简答题取已确认得分"""
    answers = _json_obj(record.answers)
    short_scores = _json_obj(record.short_scores)
    ai = _json_obj(record.ai_suggestions)
    objective = short_total = correct = pending = 0
    items = []
    for eq, q in rows:
        given = answers.get(str(q.id), "")
        if q.type == "short":
            sc = short_scores.get(str(q.id))
            awarded = int(sc) if sc is not None else None
            ok = None
            if awarded is None:
                pending += 1
            else:
                short_total += awarded
        else:
            awarded, ok = _grade_objective(q, given, eq.score)
            objective += awarded
            correct += 1 if ok else 0
        items.append({
            **_q_out(q, with_answer=with_answer),
            "score": eq.score,
            "sort": eq.sort,
            "my_answer": given,
            "correct": ok,
            "awarded": awarded,
            "ai_suggestion": ai.get(str(q.id)),
        })
    return {
        "objective_score": objective,
        "short_score": short_total,
        "total": objective + short_total,
        "correct_count": correct,
        "pending_manual": pending,
        "questions": items,
    }


def _reflow_wrong_questions(db: Session, record: ExamRecord, rows) -> None:
    """把已确定的失分题幂等写入错题、复习计划和知识点掌握度"""
    view = _build_record_view(record, rows, False)
    lost_items = [item for item in view["questions"]
                  if item["awarded"] is not None and item["awarded"] < item["score"]]
    if not lost_items:
        return

    exam = db.query(Exam).filter(Exam.id == record.exam_id).first()
    profile = db.query(StudentProfile).filter(
        StudentProfile.user_id == record.student_id,
        StudentProfile.course_id == exam.course_id,
    ).first()
    if not profile:
        profile = StudentProfile(
            user_id=record.student_id, course_id=exam.course_id, overall_progress=0,
        )
        db.add(profile)
        db.flush()

    for item in lost_items:
        source_id = f"{record.id}:{item['id']}"
        wrong = db.query(WrongQuestion).filter(
            WrongQuestion.profile_id == profile.id,
            WrongQuestion.source_type == "exam_record",
            WrongQuestion.source_id == source_id,
        ).first()
        created = wrong is None
        if created:
            content = f"【考试失分】{item['stem']}\n我的作答：{item['my_answer'] or '（未作答）'}"
            wrong = WrongQuestion(
                profile_id=profile.id,
                kp_id=item["kp_id"],
                question_content=content[:4000],
                error_type="考试失分",
                source_type="exam_record",
                source_id=source_id,
            )
            db.add(wrong)
            db.flush()

        if not db.query(ReviewPlan).filter(ReviewPlan.wrong_question_id == wrong.id).first():
            db.add(ReviewPlan(
                wrong_question_id=wrong.id,
                next_review_at=datetime.utcnow() + timedelta(days=1),
                review_count=0,
                interval_days=1,
                status="pending",
            ))

        if created and item["kp_id"]:
            mastery = db.query(MasteryRecord).filter(
                MasteryRecord.profile_id == profile.id,
                MasteryRecord.kp_id == item["kp_id"],
            ).first()
            if not mastery:
                mastery = MasteryRecord(
                    profile_id=profile.id, kp_id=item["kp_id"], mastery_level=100,
                )
                db.add(mastery)
                db.flush()
            mastery.mastery_level = max(0, (mastery.mastery_level or 0) - 10)
            mastery.last_assessed_at = datetime.utcnow()


@router.get("/teacher/exam-records/{record_id}")
def get_exam_record(
    record_id: int,
    teacher: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    """教师查看单个答卷与简答批改状态"""
    record, exam = _owned_record(db, record_id, teacher)
    student = db.query(User).filter(User.id == record.student_id).first()
    view = _build_record_view(record, _exam_question_rows(db, exam.id), True)
    return {
        "record_id": record.id,
        "exam_id": exam.id,
        "exam_title": exam.title,
        "student_id": record.student_id,
        "student_name": student.name if student else "",
        "total_score": exam.total_score,
        "score": view["total"],
        "objective_score": view["objective_score"],
        "short_score": view["short_score"],
        "correct_count": view["correct_count"],
        "pending_manual": view["pending_manual"],
        "violations": record.violations or 0,
        "copy_count": record.copy_count or 0,
        "paste_count": record.paste_count or 0,
        "timed_out": bool(record.timed_out),
        "graded_at": record.graded_at,
        "submitted_at": record.submitted_at,
        "questions": view["questions"],
    }


@router.post("/teacher/exam-records/{record_id}/ai-grade")
async def ai_grade_exam_record(
    record_id: int,
    teacher: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    """AI 简答评分建议:只写 ai_suggestions,不改变正式得分"""
    record, exam = _owned_record(db, record_id, teacher)
    rows = _exam_question_rows(db, exam.id)
    short_rows = [(eq, q) for eq, q in rows if q.type == "short"]
    if not short_rows:
        raise HTTPException(status_code=400, detail="该答卷没有简答题")

    answers = _json_obj(record.answers)
    suggestions = {}
    for eq, q in short_rows:
        given = answers.get(str(q.id), "")
        result = await grade_submission(
            q.stem, f"本题满分 {eq.score} 分", given, q.answer or None,
        )
        scaled = round(result["score"] / 100 * eq.score)
        suggestions[str(q.id)] = {
            "score": max(0, min(eq.score, scaled)),
            "feedback": result["feedback"],
            "source": result["source"],
        }
    record.ai_suggestions = json.dumps(suggestions, ensure_ascii=False)
    db.commit()
    return {"record_id": record.id, "suggestions": suggestions}


@router.post("/teacher/exam-records/{record_id}/confirm")
def confirm_short_scores(
    record_id: int,
    req: ShortGradeConfirm,
    teacher: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    """教师确认简答得分:写入 short_scores 并重算总分"""
    record, exam = _owned_record(db, record_id, teacher)
    rows = _exam_question_rows(db, exam.id)
    short_map = {str(q.id): eq for eq, q in rows if q.type == "short"}
    if not short_map:
        raise HTTPException(status_code=400, detail="该答卷没有简答题")

    merged = _json_obj(record.short_scores)
    changed = 0
    for key, value in req.scores.items():
        eq = short_map.get(str(key))
        if not eq:
            continue
        merged[str(key)] = max(0, min(eq.score, int(value)))
        changed += 1
    if not changed:
        raise HTTPException(status_code=400, detail="没有可确认的简答得分")

    record.short_scores = json.dumps(merged, ensure_ascii=False)
    record.graded_at = datetime.utcnow()
    record.graded_by = teacher.id
    view = _build_record_view(record, rows, True)
    record.total_score = view["total"]
    _reflow_wrong_questions(db, record, rows)
    db.commit()
    return {
        "record_id": record.id,
        "score": record.total_score,
        "short_score": view["short_score"],
        "pending_manual": view["pending_manual"],
    }


# ---------- 学生考试 ----------

def _clean_client_id(value: Optional[str]) -> Optional[str]:
    return (value or "").strip()[:128] or None


def _bind_session_client(session: ExamSession, client_id: Optional[str]) -> None:
    """绑定考试客户端;已绑定后拒绝其他浏览器/设备继续作答"""
    client_id = _clean_client_id(client_id)
    if session.client_id and session.client_id != client_id:
        raise HTTPException(status_code=409, detail="该考试已在其他浏览器或设备中开始")
    if client_id and not session.client_id:
        session.client_id = client_id


@router.get("/student/exams")
def list_my_exams(
    student: User = Depends(require_student),
    db: Session = Depends(get_db),
):
    if not is_enabled(db, "feature_exams"):
        return []
    conditions = _student_conditions(db, student)
    if not conditions:
        return []
    rows = (
        db.query(Exam)
        .filter(Exam.status.in_(("published", "closed")), or_(*conditions))
        .order_by(Exam.id.desc())
        .limit(50)
        .all()
    )
    if not rows:
        return []
    ids = [e.id for e in rows]
    records = {
        r.exam_id: r for r in db.query(ExamRecord).filter(
            ExamRecord.student_id == student.id,
            ExamRecord.exam_id.in_(ids),
        ).all()
    }
    courses = {
        c.id: c.name for c in db.query(Course).filter(
            Course.id.in_([e.course_id for e in rows] or [0])
        ).all()
    }
    q_counts = dict(
        db.query(ExamQuestion.exam_id, func.count(ExamQuestion.id))
        .filter(ExamQuestion.exam_id.in_(ids))
        .group_by(ExamQuestion.exam_id)
        .all()
    )
    result = []
    for exam in rows:
        rec = records.get(exam.id)
        if rec:
            state = "submitted"
        elif exam.status == "closed":
            state = "closed"
        elif _due_passed(exam):
            state = "overdue"
        else:
            state = "not_started"
        result.append({
            "id": exam.id,
            "title": exam.title,
            "course_id": exam.course_id,
            "course_name": courses.get(exam.course_id),
            "duration_minutes": exam.duration_minutes,
            "due_at": exam.due_at,
            "total_score": exam.total_score,
            "question_count": q_counts.get(exam.id, 0),
            "state": state,
            "score": rec.total_score if rec else None,
        })
    return result


@router.post("/student/exams/{exam_id}/start")
def start_exam(
    exam_id: int,
    student: User = Depends(require_student),
    db: Session = Depends(get_db),
    client_id: Optional[str] = None,
):
    """开始考试:服务端记录开始时间与截止时间(时长与试卷截止取较早)"""
    if not is_enabled(db, "feature_exams"):
        raise HTTPException(status_code=403, detail="考试功能已关闭")
    exam = _visible_exam(db, exam_id, student)
    if _due_passed(exam):
        raise HTTPException(status_code=400, detail="已过截止时间，无法开始考试")
    record = db.query(ExamRecord).filter(
        ExamRecord.exam_id == exam.id,
        ExamRecord.student_id == student.id,
    ).first()
    if record:
        raise HTTPException(status_code=400, detail="你已提交过该试卷")

    session = db.query(ExamSession).filter(
        ExamSession.exam_id == exam.id,
        ExamSession.student_id == student.id,
    ).first()
    client_id = _clean_client_id(client_id)
    if not session:
        now = datetime.utcnow()
        deadline = now + timedelta(minutes=exam.duration_minutes)
        if exam.due_at and exam.due_at < deadline:
            deadline = exam.due_at
        session = ExamSession(
            exam_id=exam.id, student_id=student.id,
            started_at=now, deadline_at=deadline, last_seen_at=now,
            client_id=client_id,
        )
        db.add(session)
    else:
        _bind_session_client(session, client_id)
    db.commit()
    db.refresh(session)

    remaining = 0
    if session.deadline_at:
        remaining = max(0, int((session.deadline_at - datetime.utcnow()).total_seconds()))
    return {
        "exam_id": exam.id,
        "started_at": session.started_at,
        "deadline_at": session.deadline_at,
        "remaining_seconds": remaining,
        "duration_minutes": exam.duration_minutes,
        "violations": session.violations or 0,
        "client_id": session.client_id,
        "copy_count": session.copy_count or 0,
        "paste_count": session.paste_count or 0,
    }


@router.post("/student/exams/{exam_id}/heartbeat")
def exam_heartbeat(
    exam_id: int,
    req: ExamHeartbeat,
    student: User = Depends(require_student),
    db: Session = Depends(get_db),
):
    """答题心跳:上报切屏次数并返回剩余时间"""
    exam = _visible_exam(db, exam_id, student)
    session = db.query(ExamSession).filter(
        ExamSession.exam_id == exam.id,
        ExamSession.student_id == student.id,
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="请先开始考试")
    if session.submitted_at:
        raise HTTPException(status_code=400, detail="答卷已提交")

    _bind_session_client(session, req.client_id)
    now = datetime.utcnow()
    session.last_seen_at = now
    session.violations = max(session.violations or 0, req.violations)
    session.copy_count = max(session.copy_count or 0, req.copy_count)
    session.paste_count = max(session.paste_count or 0, req.paste_count)
    db.commit()

    remaining = 0
    if session.deadline_at:
        remaining = max(0, int((session.deadline_at - now).total_seconds()))
    return {
        "deadline_at": session.deadline_at,
        "remaining_seconds": remaining,
        "violations": session.violations,
        "copy_count": session.copy_count or 0,
        "paste_count": session.paste_count or 0,
    }


@router.get("/student/exams/{exam_id}")
def get_my_exam(
    exam_id: int,
    student: User = Depends(require_student),
    db: Session = Depends(get_db),
):
    exam = _visible_exam(db, exam_id, student, allow_closed=True)
    rows = _exam_question_rows(db, exam_id)
    record = db.query(ExamRecord).filter(
        ExamRecord.exam_id == exam.id,
        ExamRecord.student_id == student.id,
    ).first()

    due_passed = _due_passed(exam)
    reveal = exam.status == "closed" or due_passed
    questions = []
    for eq, q in rows:
        item = _q_out(q, with_answer=reveal)
        item["score"] = eq.score
        item["sort"] = eq.sort
        questions.append(item)

    my_record = None
    results = []
    if record:
        view = _build_record_view(record, rows, reveal)
        results = [
            {
                "question_id": item["id"],
                "my_answer": item["my_answer"],
                "correct": item["correct"],
                "awarded": item["awarded"],
            }
            for item in view["questions"]
        ]
        my_record = {
            "score": view["total"],
            "objective_score": view["objective_score"],
            "short_score": view["short_score"],
            "correct_count": view["correct_count"],
            "question_count": record.question_count,
            "pending_manual": view["pending_manual"],
            "violations": record.violations or 0,
            "copy_count": record.copy_count or 0,
            "paste_count": record.paste_count or 0,
            "timed_out": bool(record.timed_out),
            "submitted_at": record.submitted_at,
        }

    return {
        "id": exam.id,
        "title": exam.title,
        "description": exam.description,
        "course_id": exam.course_id,
        "duration_minutes": exam.duration_minutes,
        "due_at": exam.due_at,
        "status": exam.status,
        "total_score": exam.total_score,
        "due_passed": due_passed,
        "reveal_answers": reveal,
        "questions": questions,
        "my_record": my_record,
        "results": results,
    }


@router.post("/student/exams/{exam_id}/submit")
def submit_exam(
    exam_id: int,
    req: ExamSubmit,
    student: User = Depends(require_student),
    db: Session = Depends(get_db),
):
    """提交答卷:必须先开始计时;客观题自动判分,简答题待教师批改"""
    if not is_enabled(db, "feature_exams"):
        raise HTTPException(status_code=403, detail="考试功能已关闭")
    exam = _visible_exam(db, exam_id, student)
    existing = db.query(ExamRecord).filter(
        ExamRecord.exam_id == exam.id,
        ExamRecord.student_id == student.id,
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="你已提交过该试卷，不能重复提交")

    session = db.query(ExamSession).filter(
        ExamSession.exam_id == exam.id,
        ExamSession.student_id == student.id,
    ).first()
    if not session:
        raise HTTPException(status_code=400, detail="请先开始考试再提交")
    if session.submitted_at:
        raise HTTPException(status_code=400, detail="答卷已提交")

    _bind_session_client(session, req.client_id)
    now = datetime.utcnow()
    timed_out = 0
    if session.deadline_at:
        if now > session.deadline_at + timedelta(seconds=60):
            raise HTTPException(status_code=400, detail="考试已超时，无法提交")
        if now > session.deadline_at:
            timed_out = 1

    rows = _exam_question_rows(db, exam.id)
    if not rows:
        raise HTTPException(status_code=400, detail="试卷没有题目")

    answers = {str(k): str(v) for k, v in req.answers.items()}
    objective = 0
    correct = 0
    pending = 0
    for eq, q in rows:
        if q.type == "short":
            pending += 1
            continue
        given = answers.get(str(q.id), "")
        awarded, ok = _grade_objective(q, given, eq.score)
        objective += awarded
        correct += 1 if ok else 0

    violations = max(session.violations or 0, req.violations)
    copy_count = max(session.copy_count or 0, req.copy_count)
    paste_count = max(session.paste_count or 0, req.paste_count)
    record = ExamRecord(
        exam_id=exam.id,
        student_id=student.id,
        answers=json.dumps(answers, ensure_ascii=False),
        total_score=objective,
        correct_count=correct,
        question_count=len(rows),
        violations=violations,
        client_id=session.client_id,
        copy_count=copy_count,
        paste_count=paste_count,
        timed_out=timed_out,
    )
    db.add(record)
    db.flush()
    _reflow_wrong_questions(db, record, rows)
    session.submitted_at = now
    session.violations = violations
    session.copy_count = copy_count
    session.paste_count = paste_count
    db.commit()
    db.refresh(record)
    logger.info(
        "试卷提交: exam=%s student=%s objective=%s pending_manual=%s violations=%s",
        exam.id, student.id, objective, pending, violations,
    )

    return {
        "exam_id": exam.id,
        "score": objective,
        "total_score": exam.total_score,
        "correct_count": correct,
        "question_count": len(rows),
        "pending_manual": pending,
        "violations": violations,
        "copy_count": copy_count,
        "paste_count": paste_count,
        "timed_out": bool(timed_out),
        "submitted_at": record.submitted_at,
    }
