"""学生端路由:我的课程 / 学情档案 / 错题 / 复习计划 / 练习 / 面试 / 通知"""
import logging
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.core.deps import require_student
from app.models.user import User
from app.models.course import Course, KnowledgePoint
from app.models.classroom import CourseEnrollment, ClassMember
from app.models.interview_assignment import InterviewAssignment
from app.models.profile import StudentProfile, MasteryRecord, WrongQuestion, ReviewPlan
from app.models.practice import PracticeRecord
from app.models.interview import InterviewRecord
from app.schemas.agent import ChatRequest
from app.schemas.student import (
    WrongQuestionOut, ReviewPlanOut, ProgressOut, MasteryItem, InterviewRecordOut,
    InterviewStartRequest, EnrollOut, PracticeSubmitRequest,
    PracticeGenerateRequest, WrongQuestionCreate, NotificationPreferenceUpdate,
)
from app.api.chat import stream_agent_response, SSE_HEADERS
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


# ---------- 我的课程 ----------

@router.get("/courses")
def my_courses(
    student: User = Depends(require_student),
    db: Session = Depends(get_db),
):
    """我的课程列表(已加入的课程)"""
    rows = (
        db.query(Course, StudentProfile)
        .join(StudentProfile, StudentProfile.course_id == Course.id)
        .filter(StudentProfile.user_id == student.id)
        .order_by(Course.id.desc())
        .all()
    )
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
    plan = db.query(ReviewPlan).filter(ReviewPlan.id == plan_id).first()
    if not plan:
        raise HTTPException(status_code=404, detail="复习计划不存在")

    intervals = [1, 2, 4, 7, 15, 30]
    plan.review_count += 1
    if plan.review_count >= len(intervals):
        plan.status = "done"
    else:
        from datetime import datetime, timedelta
        plan.interval_days = intervals[plan.review_count]
        plan.next_review_at = datetime.now() + timedelta(days=intervals[plan.review_count])
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


@router.post("/interview/start")
def start_interview(
    req: InterviewStartRequest,
    request: Request,
    student: User = Depends(require_student),
    db: Session = Depends(get_db),
):
    """开启模拟面试(SSE,复用 Agent 图 interview 分支)"""
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
    chat_req = ChatRequest(session_id=None, course_id=req.course_id, message=msg)
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

    names = [
        name for (name,) in db.query(KnowledgePoint.name)
        .filter(KnowledgePoint.course_id == req.course_id)
        .limit(20).all()
    ]
    weak = (
        db.query(KnowledgePoint.name)
        .join(WrongQuestion, WrongQuestion.kp_id == KnowledgePoint.id)
        .filter(WrongQuestion.profile_id == profile.id)
        .limit(5)
        .all()
    )
    for (name,) in weak:
        if name and name not in names:
            names.insert(0, name)

    items = await generate_practice(course.name if course else "课程", names, req.count)
    return {"course_id": req.course_id, "items": items}


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
        next_review_at=datetime.utcnow() + timedelta(days=1),
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
                InterviewAssignment.due_at >= datetime.utcnow()),
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
            "due_at": r.due_at, "created_at": r.created_at,
        }
        for r in rows
    ]
