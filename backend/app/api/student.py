"""学生端路由:我的课程 / 学情档案 / 错题 / 复习计划 / 练习 / 面试 / 通知"""
import logging
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.core.time import utcnow
from app.core.deps import require_student
from app.models.user import User
from app.models.course import Course, KnowledgePoint
from app.models.classroom import CourseEnrollment, ClassMember
from app.models.assignment import Assignment, Submission
from app.models.exam import Exam, ExamRecord
from app.models.interview_assignment import InterviewAssignment
from app.models.profile import StudentProfile, MasteryRecord, WrongQuestion, ReviewPlan
from app.models.practice import PracticeRecord
from app.models.interview import InterviewRecord
from app.api.assignments import _student_conditions as _assignment_conditions
from app.api.exams import _student_conditions as _exam_conditions
from app.schemas.agent import ChatRequest
from app.schemas.student import (
    WrongQuestionOut, ReviewPlanOut, ProgressOut, MasteryItem, InterviewRecordOut,
    InterviewStartRequest, EnrollOut, PracticeSubmitRequest,
    PracticeGenerateRequest, WrongQuestionCreate, NotificationPreferenceUpdate,
    InterviewVisibilityUpdate,
)
from app.api.chat import stream_agent_response, SSE_HEADERS
from app.services.course_access import is_open_to_students, visible_course_ids
from app.services.practice_generator import generate_practice
from app.services.notifications import (
    get_preferences, list_notifications,
    mark_all_notifications_read as mark_all_notifications_read_service,
    mark_notification_read as mark_notification_read_service,
    preference_out, update_preferences,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/student", tags=["学生端"])


def _ensure_profile(
    db: Session, user_id: int, course_id: int, require_enrolled: bool = True,
) -> StudentProfile:
    """获取或自动创建学情档案(学生首次进入不再 404)

    课程已私有化:学生必须先有选课关系,否则拒绝建档案,避免直连越权。
    管理员代查场景传 require_enrolled=False。
    """
    course = db.query(Course).filter(Course.id == course_id).first()
    if not course:
        raise HTTPException(status_code=404, detail="课程不存在")

    user = db.query(User).filter(User.id == user_id).first()
    if require_enrolled and user and user.role == "student":
        if not is_open_to_students(course):
            raise HTTPException(status_code=403, detail="课程未通过平台审核，暂不可访问")
        enrolled = db.query(CourseEnrollment).filter(
            CourseEnrollment.course_id == course_id,
            CourseEnrollment.student_id == user_id,
        ).first()
        if not enrolled:
            raise HTTPException(status_code=403, detail="请先通过班级邀请码加入该课程")

    profile = (
        db.query(StudentProfile)
        .filter(StudentProfile.user_id == user_id, StudentProfile.course_id == course_id)
        .first()
    )
    if not profile:
        profile = StudentProfile(user_id=user_id, course_id=course_id)
        db.add(profile)
        db.commit()
        db.refresh(profile)
        logger.info("学情档案自动创建(user=%s, course=%s)", user_id, course_id)
    return profile


def _build_progress(db: Session, profile: StudentProfile, course_id: int) -> ProgressOut:
    """组装进度与掌握度响应"""
    records = (
        db.query(MasteryRecord, KnowledgePoint)
        .join(KnowledgePoint, MasteryRecord.kp_id == KnowledgePoint.id)
        .filter(MasteryRecord.profile_id == profile.id)
        .all()
    )
    mastery = [
        MasteryItem(kp_id=kp.id, kp_name=kp.name, mastery_level=rec.mastery_level)
        for rec, kp in records
    ]
    return ProgressOut(
        course_id=course_id,
        overall_progress=float(profile.overall_progress or 0),
        mastery=mastery,
    )


# ---------- 学习聚合与下一步建议 ----------

def _pending_assignments(db: Session, student: User, course_id: int) -> list[Assignment]:
    """该课程下学生可见且尚未正式提交的已发布作业"""
    conditions = _assignment_conditions(db, student)
    if not conditions:
        return []
    rows = (
        db.query(Assignment)
        .filter(
            Assignment.course_id == course_id,
            Assignment.status == "published",
            or_(*conditions),
        )
        .order_by(Assignment.due_at.asc(), Assignment.id.desc())
        .all()
    )
    if not rows:
        return []
    submitted_ids = {
        sid for (sid,) in db.query(Submission.assignment_id).filter(
            Submission.student_id == student.id,
            Submission.status == "submitted",
            Submission.assignment_id.in_([row.id for row in rows]),
        ).all()
    }
    return [row for row in rows if row.id not in submitted_ids]


def _pending_exams(db: Session, student: User, course_id: int) -> list[Exam]:
    """该课程下学生可见、尚未作答的已发布考试"""
    conditions = _exam_conditions(db, student)
    if not conditions:
        return []
    rows = (
        db.query(Exam)
        .filter(
            Exam.course_id == course_id,
            Exam.status == "published",
            or_(*conditions),
        )
        .order_by(Exam.due_at.asc(), Exam.id.desc())
        .all()
    )
    if not rows:
        return []
    done_ids = {
        eid for (eid,) in db.query(ExamRecord.exam_id).filter(
            ExamRecord.student_id == student.id,
            ExamRecord.exam_id.in_([row.id for row in rows]),
        ).all()
    }
    return [row for row in rows if row.id not in done_ids]


def _course_snapshot(db: Session, student: User, profile: StudentProfile) -> dict:
    """单个课程的学习快照:薄弱点、到期复习、待交作业、待考考试"""
    now = utcnow()
    course = db.query(Course).filter(Course.id == profile.course_id).first()

    weak_rows = (
        db.query(KnowledgePoint, MasteryRecord)
        .join(MasteryRecord, MasteryRecord.kp_id == KnowledgePoint.id)
        .filter(
            MasteryRecord.profile_id == profile.id,
            MasteryRecord.mastery_level < 60,
        )
        .order_by(MasteryRecord.mastery_level.asc())
        .limit(5)
        .all()
    )
    weak_points = [
        {
            "kp_id": kp.id,
            "kp_name": kp.name,
            "mastery_level": int(record.mastery_level or 0),
        }
        for kp, record in weak_rows
    ]

    due_rows = (
        db.query(ReviewPlan)
        .join(WrongQuestion, ReviewPlan.wrong_question_id == WrongQuestion.id)
        .filter(
            WrongQuestion.profile_id == profile.id,
            ReviewPlan.status == "pending",
            ReviewPlan.next_review_at <= now,
        )
        .order_by(ReviewPlan.next_review_at.asc())
        .all()
    )

    assignments = _pending_assignments(db, student, profile.course_id)
    exams = _pending_exams(db, student, profile.course_id)

    last_interview = (
        db.query(InterviewRecord)
        .filter(InterviewRecord.profile_id == profile.id)
        .order_by(InterviewRecord.round.desc())
        .first()
    )

    return {
        "course": {
            "id": course.id,
            "name": course.name,
            "code": course.code,
            "overall_progress": float(profile.overall_progress or 0),
        },
        "weak_knowledge_points": weak_points,
        "due_reviews": {
            "count": len(due_rows),
            "next_at": due_rows[0].next_review_at if due_rows else None,
        },
        "pending_assignments": {
            "count": len(assignments),
            "items": [
                {
                    "id": row.id,
                    "title": row.title,
                    "due_at": row.due_at,
                    "overdue": bool(row.due_at and row.due_at < now),
                }
                for row in assignments[:5]
            ],
        },
        "pending_exams": {
            "count": len(exams),
            "items": [
                {
                    "id": row.id,
                    "title": row.title,
                    "due_at": row.due_at,
                    "overdue": bool(row.due_at and row.due_at < now),
                }
                for row in exams[:5]
            ],
        },
        "last_interview": (
            {
                "record_id": last_interview.id,
                "round": last_interview.round,
                "score": last_interview.score,
            }
            if last_interview else None
        ),
    }


def _learning_snapshots(
    db: Session, student: User, course_id: Optional[int] = None,
) -> list[dict]:
    """按课程返回学习快照;只包含学生可见课程"""
    visible = set(visible_course_ids(student, db))
    query = db.query(StudentProfile).filter(StudentProfile.user_id == student.id)
    if course_id is not None:
        query = query.filter(StudentProfile.course_id == course_id)
    profiles = query.all()
    return [
        _course_snapshot(db, student, profile)
        for profile in profiles
        if profile.course_id in visible
    ]


@router.get("/learning-overview")
def learning_overview(
    course_id: Optional[int] = Query(None, description="不传则汇总全部可见课程"),
    student: User = Depends(require_student),
    db: Session = Depends(get_db),
):
    """学习总览:进度、薄弱点、到期复习、待交作业、待考考试一次返回"""
    if course_id is not None:
        _ensure_profile(db, student.id, course_id)
    courses = _learning_snapshots(db, student, course_id)
    return {
        "courses": courses,
        "summary": {
            "course_count": len(courses),
            "weak_points": sum(len(item["weak_knowledge_points"]) for item in courses),
            "due_reviews": sum(item["due_reviews"]["count"] for item in courses),
            "pending_assignments": sum(item["pending_assignments"]["count"] for item in courses),
            "pending_exams": sum(item["pending_exams"]["count"] for item in courses),
        },
    }


@router.get("/recommendations")
def learning_recommendations(
    course_id: Optional[int] = Query(None, description="不传则汇总全部可见课程"),
    limit: int = Query(10, ge=1, le=30),
    student: User = Depends(require_student),
    db: Session = Depends(get_db),
):
    """下一步建议:按截止时间与薄弱程度给出可执行动作,不调用模型"""
    if course_id is not None:
        _ensure_profile(db, student.id, course_id)
    now = utcnow()
    items: list[dict] = []

    for snapshot in _learning_snapshots(db, student, course_id):
        course = snapshot["course"]
        for exam in snapshot["pending_exams"]["items"]:
            hours_left = None
            if exam["due_at"]:
                hours_left = (exam["due_at"] - now).total_seconds() / 3600
            items.append({
                "type": "exam",
                "priority": "high" if (exam["overdue"] or (hours_left is not None and hours_left <= 48)) else "medium",
                "title": f"完成考试:{exam['title']}",
                "reason": "考试已过截止时间" if exam["overdue"] else "考试尚未作答",
                "course_id": course["id"],
                "course_name": course["name"],
                "target_id": exam["id"],
                "due_at": exam["due_at"],
            })
        for assignment in snapshot["pending_assignments"]["items"]:
            items.append({
                "type": "assignment",
                "priority": "high" if assignment["overdue"] else "medium",
                "title": f"提交作业:{assignment['title']}",
                "reason": "作业已过截止时间" if assignment["overdue"] else "作业尚未提交",
                "course_id": course["id"],
                "course_name": course["name"],
                "target_id": assignment["id"],
                "due_at": assignment["due_at"],
            })
        if snapshot["due_reviews"]["count"]:
            items.append({
                "type": "review",
                "priority": "medium",
                "title": f"完成到期错题复习({snapshot['due_reviews']['count']} 项)",
                "reason": "遗忘曲线已到复习时间",
                "course_id": course["id"],
                "course_name": course["name"],
                "target_id": None,
                "due_at": snapshot["due_reviews"]["next_at"],
            })
        for point in snapshot["weak_knowledge_points"][:2]:
            items.append({
                "type": "practice",
                "priority": "medium" if point["mastery_level"] < 40 else "low",
                "title": f"巩固知识点:{point['kp_name']}",
                "reason": f"当前掌握度 {point['mastery_level']}%",
                "course_id": course["id"],
                "course_name": course["name"],
                "target_id": point["kp_id"],
                "due_at": None,
            })

    priority_rank = {"high": 0, "medium": 1, "low": 2}
    items.sort(key=lambda item: (
        priority_rank.get(item["priority"], 3),
        item["due_at"] or datetime.max,
    ))
    selected = items[:limit]
    return {
        "generated_at": now,
        "total": len(items),
        "items": selected,
        "summary": (
            f"共 {len(items)} 条待办建议,其中高优先级 "
            f"{sum(1 for item in items if item['priority'] == 'high')} 条"
        ),
    }


# ---------- 我的课程 ----------

@router.get("/courses")
def my_courses(
    student: User = Depends(require_student),
    db: Session = Depends(get_db),
    keyword: Optional[str] = None,
    semester: Optional[str] = None,
):
    """我的课程列表(已加入且已通过平台审核的课程);支持名称/代码搜索与学期筛选"""
    query = (
        db.query(Course, StudentProfile)
        .join(StudentProfile, StudentProfile.course_id == Course.id)
        .filter(
            StudentProfile.user_id == student.id,
            Course.audit_status == "approved",
            Course.deleted_at.is_(None),
        )
    )
    text = (keyword or "").strip()
    if text:
        like = f"%{text}%"
        query = query.filter(or_(Course.name.like(like), Course.code.like(like)))
    if semester:
        query = query.filter(Course.semester == semester)

    rows = query.order_by(Course.id.desc()).all()
    return [
        {
            "id": course.id,
            "teacher_id": course.teacher_id,
            "name": course.name,
            "code": course.code,
            "syllabus": course.syllabus,
            "semester": course.semester,
            "audit_status": course.audit_status,
            "overall_progress": float(profile.overall_progress or 0),
        }
        for course, profile in rows
    ]


@router.post("/courses/{course_id}/enroll", response_model=EnrollOut)
def enroll_course(
    course_id: int,
    student: User = Depends(require_student),
    db: Session = Depends(get_db),
):
    """加入课程(幂等)。课程已私有化:仅已通过班级/邀请获得可见性的学生可加入"""
    course = db.query(Course).filter(Course.id == course_id).first()
    if not course:
        raise HTTPException(status_code=404, detail="课程不存在")
    if student.role == "student":
        if not is_open_to_students(course):
            raise HTTPException(status_code=403, detail="课程未通过平台审核，暂不可加入")
        enrolled = db.query(CourseEnrollment).filter(
            CourseEnrollment.course_id == course_id,
            CourseEnrollment.student_id == student.id,
        ).first()
        if not enrolled:
            raise HTTPException(
                status_code=403,
                detail="请先通过班级邀请码加入该课程",
            )
    profile = _ensure_profile(db, student.id, course_id)
    return EnrollOut(course_id=course_id, profile_id=profile.id, joined=True)


# ---------- 学情进度 ----------

@router.get("/progress", response_model=ProgressOut)
def get_progress(
    course_id: int = Query(...),
    student: User = Depends(require_student),
    db: Session = Depends(get_db),
):
    """查看我的学习进度与知识点掌握度(旧路径)"""
    profile = _ensure_profile(db, student.id, course_id)
    return _build_progress(db, profile, course_id)


@router.get("/progress/{course_id}", response_model=ProgressOut)
def get_progress_by_path(
    course_id: int,
    student: User = Depends(require_student),
    db: Session = Depends(get_db),
):
    """查看我的学习进度与知识点掌握度(方案路径)"""
    profile = _ensure_profile(db, student.id, course_id)
    return _build_progress(db, profile, course_id)


# ---------- 练习 ----------

@router.post("/practice")
def submit_practice(
    req: PracticeSubmitRequest,
    student: User = Depends(require_student),
    db: Session = Depends(get_db),
):
    """提交练习记录(本期仅记录与自评,不自动判分)"""
    profile = _ensure_profile(db, student.id, req.course_id)

    if req.kp_id is not None:
        kp = (
            db.query(KnowledgePoint)
            .filter(KnowledgePoint.id == req.kp_id, KnowledgePoint.course_id == req.course_id)
            .first()
        )
        if not kp:
            raise HTTPException(status_code=400, detail="知识点不属于该课程")

    record = PracticeRecord(
        profile_id=profile.id,
        kp_id=req.kp_id,
        type=req.type,
        content=req.content,
        is_correct=req.is_correct,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return {
        "id": record.id,
        "profile_id": record.profile_id,
        "kp_id": record.kp_id,
        "type": record.type,
        "content": record.content,
        "is_correct": record.is_correct,
        "created_at": record.created_at,
    }


# ---------- 错题集 ----------

@router.get("/wrong-questions", response_model=List[WrongQuestionOut])
def list_wrong_questions(
    course_id: Optional[int] = Query(None, description="不传则汇总该生全部课程"),
    limit: int = Query(50, le=200),
    student: User = Depends(require_student),
    db: Session = Depends(get_db),
):
    query = db.query(WrongQuestion)
    if course_id is not None:
        profile = _ensure_profile(db, student.id, course_id)
        query = query.filter(WrongQuestion.profile_id == profile.id)
    else:
        profile_ids = [p.id for p in db.query(StudentProfile).filter(StudentProfile.user_id == student.id).all()]
        if not profile_ids:
            return []
        query = query.filter(WrongQuestion.profile_id.in_(profile_ids))
    return query.order_by(WrongQuestion.created_at.desc()).limit(limit).all()


# ---------- 复习计划 ----------

@router.get("/review-plans", response_model=List[ReviewPlanOut])
def list_review_plans(
    course_id: Optional[int] = Query(None, description="不传则汇总该生全部课程"),
    status: str = Query("pending"),
    student: User = Depends(require_student),
    db: Session = Depends(get_db),
):
    """查看待复习/已完成计划(遗忘曲线驱动)"""
    query = (
        db.query(ReviewPlan)
        .join(WrongQuestion, ReviewPlan.wrong_question_id == WrongQuestion.id)
    )
    if course_id is not None:
        profile = _ensure_profile(db, student.id, course_id)
        query = query.filter(WrongQuestion.profile_id == profile.id)
    else:
        profile_ids = [p.id for p in db.query(StudentProfile).filter(StudentProfile.user_id == student.id).all()]
        if not profile_ids:
            return []
        query = query.filter(WrongQuestion.profile_id.in_(profile_ids))
    if status != "all":
        query = query.filter(ReviewPlan.status == status)
    return query.order_by(ReviewPlan.next_review_at.asc()).limit(100).all()


@router.post("/review-plans/{plan_id}/complete")
def complete_review(
    plan_id: int,
    student: User = Depends(require_student),
    db: Session = Depends(get_db),
):
    """标记复习完成(进入下一个遗忘曲线间隔)"""
    plan = (
        db.query(ReviewPlan)
        .join(WrongQuestion, ReviewPlan.wrong_question_id == WrongQuestion.id)
        .join(StudentProfile, WrongQuestion.profile_id == StudentProfile.id)
        .filter(ReviewPlan.id == plan_id, StudentProfile.user_id == student.id)
        .first()
    )
    if not plan:
        raise HTTPException(status_code=404, detail="复习计划不存在")
    if plan.status == "done" or plan.next_review_at > utcnow():
        return {"id": plan.id, "status": plan.status, "next_review_at": str(plan.next_review_at)}

    intervals = [1, 2, 4, 7, 15, 30]
    plan.review_count += 1
    if plan.review_count >= len(intervals):
        plan.status = "done"
    else:
        plan.interval_days = intervals[plan.review_count]
        plan.next_review_at = utcnow() + timedelta(days=intervals[plan.review_count])
    db.commit()
    return {"id": plan.id, "status": plan.status, "next_review_at": str(plan.next_review_at)}


# ---------- 面试实训 ----------

def _interview_records(db: Session, student_id: int, course_id: Optional[int]) -> List[InterviewRecord]:
    """按课程或全量查询面试记录"""
    if course_id is not None:
        profile = _ensure_profile(db, student_id, course_id)
        profile_ids = [profile.id]
    else:
        profile_ids = [p.id for p in db.query(StudentProfile).filter(StudentProfile.user_id == student_id).all()]
        if not profile_ids:
            return []
    return (
        db.query(InterviewRecord)
        .filter(InterviewRecord.profile_id.in_(profile_ids))
        .order_by(InterviewRecord.round.asc())
        .all()
    )


@router.get("/interview-records", response_model=List[InterviewRecordOut])
def list_interview_records(
    course_id: Optional[int] = Query(None, description="不传则汇总该生全部课程"),
    student: User = Depends(require_student),
    db: Session = Depends(get_db),
):
    """面试记录(旧路径)"""
    return _interview_records(db, student.id, course_id)


@router.get("/interview/records", response_model=List[InterviewRecordOut])
def list_interview_records_by_path(
    course_id: Optional[int] = Query(None, description="不传则汇总该生全部课程"),
    student: User = Depends(require_student),
    db: Session = Depends(get_db),
):
    """面试记录(方案路径)"""
    return _interview_records(db, student.id, course_id)


@router.patch("/interview/records/{record_id}/visibility", response_model=InterviewRecordOut)
def update_interview_visibility(
    record_id: int,
    req: InterviewVisibilityUpdate,
    student: User = Depends(require_student),
    db: Session = Depends(get_db),
):
    record = (
        db.query(InterviewRecord)
        .join(StudentProfile, InterviewRecord.profile_id == StudentProfile.id)
        .filter(InterviewRecord.id == record_id, StudentProfile.user_id == student.id)
        .first()
    )
    if not record:
        raise HTTPException(status_code=404, detail="面试记录不存在")
    record.visibility = req.visibility
    db.commit()
    db.refresh(record)
    return record


def _visible_interview_assignment(
    db: Session, student_id: int, assignment_id: int, course_id: int,
) -> InterviewAssignment:
    assignment = db.query(InterviewAssignment).filter(
        InterviewAssignment.id == assignment_id,
    ).first()
    if not assignment:
        raise HTTPException(status_code=404, detail="面试作业不存在")
    if (
        assignment.status != "active"
        or (assignment.due_at and assignment.due_at < utcnow())
    ):
        raise HTTPException(status_code=403, detail="面试作业已关闭或已截止")

    if assignment.class_id is not None:
        visible = db.query(ClassMember).filter(
            ClassMember.class_id == assignment.class_id,
            ClassMember.student_id == student_id,
            ClassMember.status == "active",
        ).first() is not None
    else:
        visible = db.query(CourseEnrollment).filter(
            CourseEnrollment.course_id == assignment.course_id,
            CourseEnrollment.student_id == student_id,
        ).first() is not None
    if not visible:
        raise HTTPException(status_code=403, detail="无权开始该面试作业")
    if assignment.course_id is not None and assignment.course_id != course_id:
        raise HTTPException(status_code=400, detail="面试作业与课程不匹配")
    return assignment


@router.post("/interview/start")
def start_interview(
    req: InterviewStartRequest,
    request: Request,
    student: User = Depends(require_student),
    db: Session = Depends(get_db),
):
    """开启模拟面试(SSE,复用 Agent 图 interview 分支)"""
    if req.assignment_id is not None:
        _visible_interview_assignment(db, student.id, req.assignment_id, req.course_id)
    _ensure_profile(db, student.id, req.course_id)

    msg = f"请开始模拟面试,课程 ID 为 {req.course_id}。"
    if req.focus_kp_ids:
        names = [
            kp.name for kp in db.query(KnowledgePoint)
            .filter(KnowledgePoint.id.in_(req.focus_kp_ids))
            .all()
        ]
        if names:
            msg += "请重点考察以下知识点:" + "、".join(names) + "。"
    chat_req = ChatRequest(
        session_id=None, course_id=req.course_id, message=msg,
        interview_assignment_id=req.assignment_id,
    )
    return StreamingResponse(
        stream_agent_response(chat_req, student, db, force_branch="interview", request=request),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


# ---------- 通知 ----------

@router.get("/notifications")
def get_notifications(
    student: User = Depends(require_student),
    db: Session = Depends(get_db),
    unread_only: bool = False,
    category: Optional[str] = None,
):
    """持久化通知列表;读取不清空,未读数只统计已到投递时间的通知"""
    return list_notifications(db, student.id, unread_only, category)


@router.post("/notifications/read-all")
def mark_all_notifications_read(
    student: User = Depends(require_student),
    db: Session = Depends(get_db),
):
    updated = mark_all_notifications_read_service(db, student.id)
    db.commit()
    return {"updated": updated, "unread_count": 0}


@router.post("/notifications/{notification_id}/read")
def mark_notification_read(
    notification_id: int,
    student: User = Depends(require_student),
    db: Session = Depends(get_db),
):
    result = mark_notification_read_service(db, student.id, notification_id)
    db.commit()
    return result


@router.get("/notification-preferences")
def get_notification_preferences(
    student: User = Depends(require_student),
    db: Session = Depends(get_db),
):
    return preference_out(get_preferences(db, student.id))


@router.put("/notification-preferences")
def update_notification_preferences(
    req: NotificationPreferenceUpdate,
    student: User = Depends(require_student),
    db: Session = Depends(get_db),
):
    result = update_preferences(db, student.id, req)
    db.commit()
    return result


# ---------- 错题本空态:生成练习 / 手动录入错题 ----------

@router.post("/practice/generate")
async def generate_practice_api(
    req: PracticeGenerateRequest,
    student: User = Depends(require_student),
    db: Session = Depends(get_db),
):
    """按课程知识点生成针对性练习(不直接入库,由学生决定是否加入错题本)"""
    profile = _ensure_profile(db, student.id, req.course_id)
    course = db.query(Course).filter(Course.id == req.course_id).first()

    wrong_rows = (
        db.query(WrongQuestion, KnowledgePoint)
        .join(KnowledgePoint, WrongQuestion.kp_id == KnowledgePoint.id)
        .filter(WrongQuestion.profile_id == profile.id)
        .order_by(WrongQuestion.created_at.desc(), WrongQuestion.id.desc())
        .limit(5)
        .all()
    )
    mastery_rows = (
        db.query(MasteryRecord, KnowledgePoint)
        .join(KnowledgePoint, MasteryRecord.kp_id == KnowledgePoint.id)
        .filter(
            MasteryRecord.profile_id == profile.id,
            MasteryRecord.mastery_level < 60,
        )
        .order_by(MasteryRecord.last_assessed_at.desc(), MasteryRecord.id.desc())
        .limit(5)
        .all()
    )
    record_refs = [
        {
            "type": "wrong_question",
            "id": wq.id,
            "title": kp.name,
            "created_at": wq.created_at,
        }
        for wq, kp in wrong_rows
    ] + [
        {
            "type": "mastery",
            "id": record.id,
            "title": kp.name,
            "created_at": record.last_assessed_at,
        }
        for record, kp in mastery_rows
    ]

    if record_refs:
        names = list(dict.fromkeys(ref["title"] for ref in record_refs))
        sources = []
        if wrong_rows:
            sources.append("错题记录")
        if mastery_rows:
            sources.append("低掌握知识点记录")
        titles = "、".join(names)
        reason = f"根据你的{'和'.join(sources)}，推荐围绕「{titles}」进行巩固练习。"
    else:
        names = [
            name for (name,) in db.query(KnowledgePoint.name)
            .filter(KnowledgePoint.course_id == req.course_id)
            .limit(20).all()
        ]
        reason = "课程基础推荐：根据课程知识点生成基础练习。"

    items = await generate_practice(course.name if course else "课程", names, req.count)
    return {
        "course_id": req.course_id,
        "items": items,
        "recommendation": {"reason": reason, "record_refs": record_refs},
    }


@router.post("/wrong-questions", response_model=WrongQuestionOut)
def create_wrong_question(
    req: WrongQuestionCreate,
    student: User = Depends(require_student),
    db: Session = Depends(get_db),
):
    """手动/由生成练习加入错题本,并自动创建首轮复习计划"""
    profile = _ensure_profile(db, student.id, req.course_id)

    kp_id = None
    if req.kp_name:
        kp = db.query(KnowledgePoint).filter(
            KnowledgePoint.course_id == req.course_id,
            KnowledgePoint.name.like(f"%{req.kp_name}%"),
        ).first()
        kp_id = kp.id if kp else None

    wq = WrongQuestion(
        profile_id=profile.id,
        kp_id=kp_id,
        question_content=req.question_content[:2000],
        error_type=req.error_type or "概念不清",
    )
    db.add(wq)
    db.flush()
    db.add(ReviewPlan(
        wrong_question_id=wq.id,
        next_review_at=utcnow() + timedelta(days=1),
        review_count=0,
        interval_days=1,
        status="pending",
    ))
    db.commit()
    db.refresh(wq)
    return WrongQuestionOut(
        id=wq.id, kp_id=wq.kp_id, question_content=wq.question_content,
        error_type=wq.error_type, created_at=wq.created_at,
    )


# ---------- 面试作业(教师发布后学生可见) ----------

@router.get("/interview-assignments")
def list_my_interview_assignments(
    student: User = Depends(require_student),
    db: Session = Depends(get_db),
):
    from sqlalchemy import or_, and_

    class_ids = [
        cid for (cid,) in db.query(ClassMember.class_id)
        .filter(ClassMember.student_id == student.id, ClassMember.status == "active")
        .all()
    ]
    course_ids = [
        cid for (cid,) in db.query(CourseEnrollment.course_id)
        .filter(CourseEnrollment.student_id == student.id)
        .all()
    ]
    conditions = []
    if class_ids:
        conditions.append(InterviewAssignment.class_id.in_(class_ids))
    if course_ids:
        conditions.append(and_(
            InterviewAssignment.class_id.is_(None),
            InterviewAssignment.course_id.in_(course_ids),
        ))
    if not conditions:
        return []

    rows = (
        db.query(InterviewAssignment)
        .filter(
            InterviewAssignment.status == "active",
            or_(*conditions),
            or_(InterviewAssignment.due_at.is_(None),
                InterviewAssignment.due_at >= utcnow()),
        )
        .order_by(InterviewAssignment.id.desc())
        .limit(20)
        .all()
    )
    teachers = {
        u.id: u.name for u in db.query(User).filter(
            User.id.in_([r.teacher_id for r in rows] or [0])
        ).all()
    }
    return [
        {
            "id": r.id, "title": r.title, "description": r.description,
            "course_id": r.course_id, "class_id": r.class_id,
            "teacher_name": teachers.get(r.teacher_id, ""),
            "due_at": r.due_at, "duration_minutes": r.duration_minutes,
            "created_at": r.created_at,
        }
        for r in rows
    ]
