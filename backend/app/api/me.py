"""个人中心:资料/密码、数据导出、账号注销

注销口径(与需求 PC-04 对齐):
- 教师:名下仍有课程或进行中班级时不允许注销,需先处理;分享码自动撤销
- 学生:删除学情、练习、错题、复习、面试、作业提交、会话与班级/选课关系,
  账号改为禁用并匿名化(邮箱/姓名/密码不可恢复),保留必要的匿名审计记录
- 管理员:不支持自助注销,由管理后台处理
"""
import json
import logging
import secrets
import shutil
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import get_current_user
from app.core.security import hash_password, verify_password
from app.db.session import get_db
from app.models.assignment import Assignment, Submission
from app.models.classroom import Classroom, ClassMember, CourseEnrollment, CourseShare
from app.models.conversation import ChatMessage, Conversation
from app.models.course import Course, CourseMaterial, KnowledgePoint
from app.models.interview import InterviewRecord
from app.models.interview_assignment import InterviewAssignment
from app.models.log import OperationLog
from app.models.practice import PracticeRecord
from app.models.profile import MasteryRecord, ReviewPlan, StudentProfile, WrongQuestion
from app.models.upload_event import UploadEvent
from app.models.user import User
from app.schemas.auth import UserOut

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/me", tags=["个人中心"])


class ProfileUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=50)
    email: EmailStr | None = None


class PasswordChange(BaseModel):
    old_password: str = Field(..., min_length=6, max_length=128)
    new_password: str = Field(..., min_length=6, max_length=128)


class DeactivateRequest(BaseModel):
    password: str = Field(..., min_length=6, max_length=128)
    confirm: str = Field(..., min_length=1, max_length=20, description="需输入「注销」")


def _iso(dt) -> str | None:
    return dt.isoformat() if dt else None


@router.get("", response_model=UserOut)
def get_profile(user: User = Depends(get_current_user)):
    return user


@router.patch("", response_model=UserOut)
def update_profile(
    req: ProfileUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if req.email and req.email != user.email:
        exists = db.query(User).filter(User.email == req.email, User.id != user.id).first()
        if exists:
            raise HTTPException(status_code=400, detail="该邮箱已被占用")
        user.email = req.email
    if req.name is not None:
        user.name = req.name
    db.commit()
    db.refresh(user)
    logger.info("个人资料更新: user=%s", user.id)
    return user


@router.patch("/password")
def change_password(
    req: PasswordChange,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not verify_password(req.old_password, user.password_hash):
        raise HTTPException(status_code=400, detail="原密码不正确")
    if req.old_password == req.new_password:
        raise HTTPException(status_code=400, detail="新密码不能与原密码相同")
    user.password_hash = hash_password(req.new_password)
    db.commit()
    return {"updated": True}


# ---------- 数据导出 ----------

def _student_export(db: Session, user: User) -> dict:
    profiles = db.query(StudentProfile).filter(StudentProfile.user_id == user.id).all()
    pids = [p.id for p in profiles]
    course_ids = {p.course_id for p in profiles}
    enrollments = db.query(CourseEnrollment).filter(
        CourseEnrollment.student_id == user.id
    ).all()
    course_ids.update(e.course_id for e in enrollments)
    courses = {
        c.id: c.name for c in db.query(Course).filter(Course.id.in_(course_ids or {0})).all()
    }

    kp_names = {}
    if pids:
        kp_ids = {
            kp_id for (kp_id,) in db.query(MasteryRecord.kp_id).filter(
                MasteryRecord.profile_id.in_(pids)
            ).all()
        } | {
            kp_id for (kp_id,) in db.query(WrongQuestion.kp_id).filter(
                WrongQuestion.profile_id.in_(pids), WrongQuestion.kp_id.isnot(None)
            ).all()
        }
        if kp_ids:
            kp_names = {
                kid: name for kid, name in db.query(KnowledgePoint.id, KnowledgePoint.name).filter(
                    KnowledgePoint.id.in_(kp_ids)
                ).all()
            }

    profile_payload = []
    for p in profiles:
        mastery = db.query(MasteryRecord).filter(MasteryRecord.profile_id == p.id).all()
        wrongs = db.query(WrongQuestion).filter(WrongQuestion.profile_id == p.id).all()
        wrong_ids = [w.id for w in wrongs]
        reviews = (
            db.query(ReviewPlan).filter(ReviewPlan.wrong_question_id.in_(wrong_ids)).all()
            if wrong_ids else []
        )
        practice = db.query(PracticeRecord).filter(PracticeRecord.profile_id == p.id).all()
        interviews = db.query(InterviewRecord).filter(InterviewRecord.profile_id == p.id).all()
        profile_payload.append({
            "course_id": p.course_id,
            "course_name": courses.get(p.course_id),
            "overall_progress": float(p.overall_progress or 0),
            "mastery": [
                {"kp_id": m.kp_id, "kp_name": kp_names.get(m.kp_id),
                 "mastery_level": m.mastery_level, "assessed_at": _iso(m.last_assessed_at)}
                for m in mastery
            ],
            "wrong_questions": [
                {"question": w.question_content, "error_type": w.error_type,
                 "kp_name": kp_names.get(w.kp_id), "created_at": _iso(w.created_at)}
                for w in wrongs
            ],
            "review_plans": [
                {"wrong_question_id": r.wrong_question_id, "next_review_at": _iso(r.next_review_at),
                 "review_count": r.review_count, "status": r.status}
                for r in reviews
            ],
            "practice_records": [
                {"type": r.type, "content": r.content, "is_correct": r.is_correct,
                 "created_at": _iso(r.created_at)}
                for r in practice
            ],
            "interview_records": [
                {"round": r.round, "question": r.question, "answer": r.answer,
                 "score": r.score, "feedback": r.feedback, "created_at": _iso(r.created_at)}
                for r in interviews
            ],
        })

    subs = (
        db.query(Submission, Assignment)
        .join(Assignment, Submission.assignment_id == Assignment.id)
        .filter(Submission.student_id == user.id)
        .all()
    )
    submissions = [
        {
            "assignment_id": a.id,
            "assignment_title": a.title,
            "kind": a.kind,
            "course_id": a.course_id,
            "content": s.content,
            "score": s.score if s.confirmed_at else None,
            "feedback": s.feedback if s.confirmed_at else None,
            "confirmed": s.confirmed_at is not None,
            "submitted_at": _iso(s.created_at),
        }
        for s, a in subs
    ]

    classes = (
        db.query(Classroom, ClassMember)
        .join(ClassMember, ClassMember.class_id == Classroom.id)
        .filter(ClassMember.student_id == user.id)
        .all()
    )
    return {
        "enrollments": [
            {"course_id": e.course_id, "course_name": courses.get(e.course_id),
             "source": e.source, "created_at": _iso(e.created_at)}
            for e in enrollments
        ],
        "classes": [
            {"class_id": c.id, "class_name": c.name, "status": m.status,
             "joined_at": _iso(m.joined_at)}
            for c, m in classes
        ],
        "learning": profile_payload,
        "submissions": submissions,
    }


def _teacher_export(db: Session, user: User) -> dict:
    courses = db.query(Course).filter(Course.teacher_id == user.id).all()
    course_ids = [c.id for c in courses] or [0]
    kps = db.query(KnowledgePoint).filter(KnowledgePoint.course_id.in_(course_ids)).all()
    materials = db.query(CourseMaterial).filter(
        CourseMaterial.course_id.in_(course_ids)
    ).all()
    classes = db.query(Classroom).filter(Classroom.teacher_id == user.id).all()
    assignments = db.query(Assignment).filter(Assignment.teacher_id == user.id).all()
    interviews = db.query(InterviewAssignment).filter(
        InterviewAssignment.teacher_id == user.id
    ).all()
    shares = db.query(CourseShare).filter(CourseShare.owner_id == user.id).all()

    assignment_payload = []
    for a in assignments:
        total = db.query(Submission).filter(Submission.assignment_id == a.id).count()
        graded = db.query(Submission).filter(
            Submission.assignment_id == a.id,
            Submission.confirmed_at.isnot(None),
        ).count()
        assignment_payload.append({
            "id": a.id, "title": a.title, "kind": a.kind,
            "course_id": a.course_id, "class_id": a.class_id,
            "status": a.status, "due_at": _iso(a.due_at),
            "created_at": _iso(a.created_at),
            "submission_count": total, "graded_count": graded,
        })

    return {
        "courses": [
            {"id": c.id, "name": c.name, "code": c.code, "semester": c.semester,
             "syllabus": c.syllabus, "created_at": _iso(c.created_at)}
            for c in courses
        ],
        "knowledge_points": [
            {"course_id": k.course_id, "name": k.name, "description": k.description,
             "parent_id": k.parent_id}
            for k in kps
        ],
        "materials": [
            {"course_id": m.course_id, "type": m.type, "title": m.title,
             "chunk_count": m.chunk_count, "uploaded_at": _iso(m.uploaded_at)}
            for m in materials
        ],
        "classes": [
            {"id": c.id, "name": c.name, "course_id": c.course_id,
             "semester": c.semester, "status": c.status}
            for c in classes
        ],
        "assignments": assignment_payload,
        "interview_assignments": [
            {"id": r.id, "title": r.title, "class_id": r.class_id,
             "course_id": r.course_id, "status": r.status, "due_at": _iso(r.due_at)}
            for r in interviews
        ],
        "course_shares": [
            {"course_id": s.course_id, "code": s.code, "expires_at": _iso(s.expires_at),
             "max_uses": s.max_uses, "used_count": s.used_count,
             "revoked_at": _iso(s.revoked_at)}
            for s in shares
        ],
    }


def _conversation_export(db: Session, user: User) -> list:
    convs = db.query(Conversation).filter(
        Conversation.user_id == user.id,
        Conversation.deleted_at.is_(None),
    ).order_by(Conversation.id.desc()).limit(100).all()
    if not convs:
        return []
    conv_ids = [c.id for c in convs]
    msgs = db.query(ChatMessage).filter(
        ChatMessage.conversation_id.in_(conv_ids)
    ).order_by(ChatMessage.id.asc()).limit(2000).all()
    grouped: dict[int, list] = {}
    for m in msgs:
        grouped.setdefault(m.conversation_id, []).append({
            "role": m.role, "content": m.content, "created_at": _iso(m.created_at),
        })
    return [
        {
            "title": c.title, "branch": c.branch, "course_id": c.course_id,
            "created_at": _iso(c.created_at),
            "messages": grouped.get(c.id, []),
        }
        for c in convs
    ]


@router.get("/export")
def export_my_data(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """导出本人数据(JSON):不含密码与他人数据"""
    payload = {
        "exported_at": datetime.utcnow().isoformat(),
        "account": {
            "id": user.id, "name": user.name, "email": user.email,
            "role": user.role, "status": user.status,
        },
        "conversations": _conversation_export(db, user),
    }
    if user.role == "student":
        payload["student"] = _student_export(db, user)
    if user.role in ("teacher", "admin"):
        payload["teacher"] = _teacher_export(db, user)

    body = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    filename = f"itea_export_{user.id}_{datetime.utcnow().strftime('%Y%m%d')}.json"
    logger.info("数据导出: user=%s role=%s", user.id, user.role)
    return Response(
        content=body,
        media_type="application/json; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------- 账号注销 ----------

@router.post("/deactivate")
def deactivate_account(
    req: DeactivateRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """注销账号:删除个人学习数据并匿名化账号,不可恢复"""
    if user.role == "admin":
        raise HTTPException(status_code=403, detail="管理员账号不支持自助注销，请联系平台处理")
    if not verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=400, detail="密码不正确")
    if req.confirm.strip() != "注销":
        raise HTTPException(status_code=400, detail="请输入「注销」以确认操作")

    if user.role == "teacher":
        if db.query(Course).filter(Course.teacher_id == user.id).count() > 0:
            raise HTTPException(status_code=400, detail="名下仍有课程，请先转移或删除课程后再注销")
        active_class = db.query(Classroom).filter(
            Classroom.teacher_id == user.id,
            Classroom.status == "active",
        ).count()
        if active_class > 0:
            raise HTTPException(status_code=400, detail="名下仍有进行中的班级，请先归档后再注销")
        db.query(CourseShare).filter(
            CourseShare.owner_id == user.id,
            CourseShare.revoked_at.is_(None),
        ).update({CourseShare.revoked_at: datetime.utcnow()}, synchronize_session=False)
    else:
        profiles = db.query(StudentProfile).filter(StudentProfile.user_id == user.id).all()
        pids = [p.id for p in profiles]
        if pids:
            wrong_ids = [wid for (wid,) in db.query(WrongQuestion.id).filter(
                WrongQuestion.profile_id.in_(pids)
            ).all()]
            if wrong_ids:
                db.query(ReviewPlan).filter(
                    ReviewPlan.wrong_question_id.in_(wrong_ids)
                ).delete(synchronize_session=False)
            db.query(WrongQuestion).filter(
                WrongQuestion.profile_id.in_(pids)
            ).delete(synchronize_session=False)
            db.query(MasteryRecord).filter(
                MasteryRecord.profile_id.in_(pids)
            ).delete(synchronize_session=False)
            db.query(PracticeRecord).filter(
                PracticeRecord.profile_id.in_(pids)
            ).delete(synchronize_session=False)
            db.query(InterviewRecord).filter(
                InterviewRecord.profile_id.in_(pids)
            ).delete(synchronize_session=False)
            db.query(StudentProfile).filter(
                StudentProfile.user_id == user.id
            ).delete(synchronize_session=False)

        db.query(Submission).filter(
            Submission.student_id == user.id
        ).delete(synchronize_session=False)

        conv_ids = [cid for (cid,) in db.query(Conversation.id).filter(
            Conversation.user_id == user.id
        ).all()]
        if conv_ids:
            db.query(ChatMessage).filter(
                ChatMessage.conversation_id.in_(conv_ids)
            ).delete(synchronize_session=False)
            db.query(Conversation).filter(
                Conversation.user_id == user.id
            ).delete(synchronize_session=False)

        db.query(CourseEnrollment).filter(
            CourseEnrollment.student_id == user.id
        ).delete(synchronize_session=False)
        db.query(ClassMember).filter(
            ClassMember.student_id == user.id
        ).delete(synchronize_session=False)

    db.query(UploadEvent).filter(UploadEvent.user_id == user.id).delete(
        synchronize_session=False
    )

    role = user.role
    user.name = "已注销用户"
    user.email = f"deleted_{user.id}@deleted.local"
    user.password_hash = hash_password(secrets.token_hex(24))
    user.status = "disabled"

    # 仅记录操作事实,不落原邮箱等个人信息
    db.add(OperationLog(
        admin_id=user.id,
        action="deactivate",
        target_type="user",
        target_id=user.id,
        detail=json.dumps({"role": role}, ensure_ascii=False),
    ))
    db.commit()

    vision_dir = settings.upload_path / "vision" / str(user.id)
    shutil.rmtree(vision_dir, ignore_errors=True)
    logger.info("账号注销: user=%s role=%s", user.id, role)
    return {"deactivated": True, "message": "账号已注销，个人学习数据与资料已清除"}
