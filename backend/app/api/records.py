"""记录与开关路由

- 学生:学习记录时间线(课程/练习/错题/复习/面试/作业)
- 教师:发布记录与完成情况(作业/考试/面试,可按班级筛选)
- 所有登录用户:读取能力开关(供前端灰度隐藏入口)
"""
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, require_student, require_teacher
from app.db.session import get_db
from app.models.assignment import Assignment, Submission
from app.models.classroom import CourseEnrollment
from app.models.course import Course, KnowledgePoint
from app.models.interview import InterviewRecord
from app.models.interview_assignment import InterviewAssignment
from app.models.practice import PracticeRecord
from app.models.profile import ReviewPlan, StudentProfile, WrongQuestion
from app.models.user import User
from app.services.feature_flags import public_features

logger = logging.getLogger(__name__)
router = APIRouter(tags=["记录与开关"])


def _iso(dt) -> Optional[str]:
    return dt.isoformat() if dt else None


def _sort_key(dt) -> datetime:
    return dt or datetime.min


def _course_names(db: Session, ids) -> dict:
    ids = [i for i in {*ids} if i]
    if not ids:
        return {}
    rows = db.query(Course.id, Course.name).filter(Course.id.in_(ids)).all()
    return {cid: name for cid, name in rows}


# ---------- 能力开关 ----------

@router.get("/config/features")
def get_features(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """读取灰度开关与配额(登录用户可见)"""
    return public_features(db)


# ---------- 学生学习记录 ----------

@router.get("/student/records")
def student_records(
    limit: int = Query(80, ge=1, le=200),
    student: User = Depends(require_student),
    db: Session = Depends(get_db),
):
    """学习记录时间线:按时间倒序聚合课程加入/练习/错题/复习/面试/作业提交"""
    events = []
    profiles = db.query(StudentProfile).filter(StudentProfile.user_id == student.id).all()
    profile_ids = [p.id for p in profiles]
    plan_course = {p.id: p.course_id for p in profiles}

    # 加入课程
    enroll_rows = (
        db.query(CourseEnrollment, Course)
        .outerjoin(Course, CourseEnrollment.course_id == Course.id)
        .filter(CourseEnrollment.student_id == student.id)
        .all()
    )
    for enr, course in enroll_rows:
        events.append({
            "type": "enrollment",
            "title": f"加入课程《{course.name}》" if course else "加入课程",
            "detail": f"来源：{enr.source}",
            "course_id": enr.course_id,
            "course_name": course.name if course else None,
            "created_at": _iso(enr.created_at),
            "_ts": _sort_key(enr.created_at),
        })

    if profile_ids:
        # 练习
        practice_rows = (
            db.query(PracticeRecord, KnowledgePoint)
            .outerjoin(KnowledgePoint, PracticeRecord.kp_id == KnowledgePoint.id)
            .filter(PracticeRecord.profile_id.in_(profile_ids))
            .order_by(PracticeRecord.id.desc())
            .limit(limit)
            .all()
        )
        for rec, kp in practice_rows:
            events.append({
                "type": "practice",
                "title": "完成练习" + (f"（{kp.name}）" if kp else ""),
                "detail": (rec.content or "")[:120],
                "course_id": plan_course.get(rec.profile_id),
                "created_at": _iso(rec.created_at),
                "_ts": _sort_key(rec.created_at),
            })

        # 错题
        wrong_rows = (
            db.query(WrongQuestion)
            .filter(WrongQuestion.profile_id.in_(profile_ids))
            .order_by(WrongQuestion.id.desc())
            .limit(limit)
            .all()
        )
        for wq in wrong_rows:
            events.append({
                "type": "wrong",
                "title": f"新增错题（{wq.error_type or '未分类'}）",
                "detail": (wq.question_content or "")[:120],
                "course_id": plan_course.get(wq.profile_id),
                "created_at": _iso(wq.created_at),
                "_ts": _sort_key(wq.created_at),
            })

        # 复习计划
        review_rows = (
            db.query(ReviewPlan, WrongQuestion)
            .join(WrongQuestion, ReviewPlan.wrong_question_id == WrongQuestion.id)
            .filter(WrongQuestion.profile_id.in_(profile_ids))
            .order_by(ReviewPlan.next_review_at.desc())
            .limit(limit)
            .all()
        )
        for plan, wq in review_rows:
            events.append({
                "type": "review",
                "title": f"复习计划（已复习 {plan.review_count} 次）",
                "detail": (wq.question_content or "")[:120],
                "course_id": plan_course.get(wq.profile_id),
                "created_at": _iso(plan.next_review_at),
                "_ts": _sort_key(plan.next_review_at),
            })

        # 模拟面试
        interview_rows = (
            db.query(InterviewRecord)
            .filter(InterviewRecord.profile_id.in_(profile_ids))
            .order_by(InterviewRecord.id.desc())
            .limit(limit)
            .all()
        )
        for rec in interview_rows:
            events.append({
                "type": "interview",
                "title": f"模拟面试 · 第 {rec.round} 轮",
                "detail": f"得分 {rec.score}" if rec.score is not None else "已完成一轮问答",
                "course_id": plan_course.get(rec.profile_id),
                "created_at": _iso(rec.created_at),
                "_ts": _sort_key(rec.created_at),
            })

    # 作业/考试提交
    sub_rows = (
        db.query(Submission, Assignment)
        .join(Assignment, Submission.assignment_id == Assignment.id)
        .filter(Submission.student_id == student.id)
        .order_by(Submission.id.desc())
        .limit(limit)
        .all()
    )
    for sub, asg in sub_rows:
        if sub.confirmed_at:
            detail = f"已批改：{sub.score} 分"
        else:
            detail = "已提交，待教师确认评分"
        events.append({
            "type": "assignment",
            "title": f"提交{'考试' if asg.kind == 'exam' else '作业'}《{asg.title}》",
            "detail": detail,
            "course_id": asg.course_id,
            "created_at": _iso(sub.created_at),
            "_ts": _sort_key(sub.created_at),
        })

    events.sort(key=lambda e: e["_ts"], reverse=True)
    events = events[:limit]

    names = _course_names(db, [e.get("course_id") for e in events])
    for e in events:
        e.pop("_ts", None)
        e["course_name"] = names.get(e.get("course_id"))
    return events


# ---------- 教师发布记录 ----------

@router.get("/teacher/publish-records")
def teacher_publish_records(
    class_id: Optional[int] = Query(None, description="按班级筛选"),
    limit: int = Query(50, ge=1, le=200),
    teacher: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    """发布记录:作业/考试/面试及完成情况"""
    items = []

    aq = db.query(Assignment)
    if teacher.role != "admin":
        aq = aq.filter(Assignment.teacher_id == teacher.id)
    if class_id:
        aq = aq.filter(Assignment.class_id == class_id)
    assignments = aq.order_by(Assignment.id.desc()).limit(limit).all()

    stats = {}
    if assignments:
        rows = (
            db.query(
                Submission.assignment_id,
                func.count(Submission.id),
                func.sum(case((Submission.confirmed_at.isnot(None), 1), else_=0)),
            )
            .filter(Submission.assignment_id.in_([a.id for a in assignments]))
            .group_by(Submission.assignment_id)
            .all()
        )
        stats = {aid: (total, int(graded or 0)) for aid, total, graded in rows}

    for a in assignments:
        total, graded = stats.get(a.id, (0, 0))
        items.append({
            "type": "assignment",
            "kind": a.kind,
            "id": a.id,
            "title": a.title,
            "class_id": a.class_id,
            "course_id": a.course_id,
            "status": a.status,
            "due_at": _iso(a.due_at),
            "created_at": _iso(a.created_at),
            "submission_count": total,
            "graded_count": graded,
            "pending_count": total - graded,
            "_ts": _sort_key(a.created_at),
        })

    iq = db.query(InterviewAssignment)
    if teacher.role != "admin":
        iq = iq.filter(InterviewAssignment.teacher_id == teacher.id)
    if class_id:
        iq = iq.filter(InterviewAssignment.class_id == class_id)
    for r in iq.order_by(InterviewAssignment.id.desc()).limit(limit).all():
        items.append({
            "type": "interview",
            "kind": "interview",
            "id": r.id,
            "title": r.title,
            "class_id": r.class_id,
            "course_id": r.course_id,
            "status": r.status,
            "due_at": _iso(r.due_at),
            "created_at": _iso(r.created_at),
            "submission_count": None,
            "graded_count": None,
            "pending_count": None,
            "_ts": _sort_key(r.created_at),
        })

    items.sort(key=lambda i: i["_ts"], reverse=True)
    items = items[:limit]
    for i in items:
        i.pop("_ts", None)

    names = _course_names(db, [i.get("course_id") for i in items])
    for i in items:
        i["course_name"] = names.get(i.get("course_id"))
    return items
