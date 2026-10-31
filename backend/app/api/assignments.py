"""作业路由:教师发布作业 / AI 建议批改 / 教师确认 / 学生提交与查看

权限与可见性:
- 教师只能操作自己课程或自己班级的作业
- 学生仅能看到已发布且命中目标(班级成员 或 已选课程)的作业
- 截止前不下发参考答案;AI 建议不写正式成绩,必须教师确认
"""
import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from app.core.deps import require_student, require_teacher
from app.db.session import get_db
from app.models.assignment import Assignment, Submission
from app.models.classroom import ClassMember, Classroom, CourseEnrollment
from app.models.course import Course
from app.models.user import User
from app.schemas.assignment import (
    AssignmentCreate, GradeConfirmRequest, SubmissionCreate,
)
from app.services.feature_flags import is_enabled
from app.services.grader import grade_submission
from app.services.notifications import notify_task_students

logger = logging.getLogger(__name__)
router = APIRouter(tags=["作业"])


# ---------- 内部工具 ----------

def _owned_course(db: Session, course_id: int, teacher: User) -> Course:
    course = db.query(Course).filter(Course.id == course_id).first()
    if not course:
        raise HTTPException(status_code=404, detail="课程不存在")
    if teacher.role != "admin" and course.teacher_id != teacher.id:
        raise HTTPException(status_code=403, detail="只能操作自己的课程")
    return course


def _owned_assignment(db: Session, assignment_id: int, teacher: User) -> Assignment:
    row = db.query(Assignment).filter(Assignment.id == assignment_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="作业不存在")
    if teacher.role != "admin" and row.teacher_id != teacher.id:
        raise HTTPException(status_code=403, detail="只能操作自己发布的作业")
    return row


def _owned_submission(db: Session, submission_id: int, teacher: User) -> Submission:
    sub = db.query(Submission).filter(Submission.id == submission_id).first()
    if not sub:
        raise HTTPException(status_code=404, detail="提交记录不存在")
    _owned_assignment(db, sub.assignment_id, teacher)
    return sub


def _student_conditions(db: Session, student: User):
    """学生可见作业的过滤条件:班级成员 或 已选课程的课程级作业"""
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
        conditions.append(Assignment.class_id.in_(class_ids))
    if course_ids:
        conditions.append(and_(
            Assignment.class_id.is_(None),
            Assignment.course_id.in_(course_ids),
        ))
    return conditions


def _visible_assignment(db: Session, assignment_id: int, student: User) -> Assignment:
    row = db.query(Assignment).filter(Assignment.id == assignment_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="作业不存在")
    conditions = _student_conditions(db, student)
    if conditions:
        visible = db.query(Assignment).filter(
            Assignment.id == assignment_id,
            Assignment.status == "published",
            or_(*conditions),
        ).first()
    else:
        visible = None
    if not visible:
        raise HTTPException(status_code=403, detail="无权查看该作业")
    return visible


def _due_passed(row: Assignment) -> bool:
    return bool(row.due_at and row.due_at < datetime.utcnow())


def _teacher_summary(row: Assignment, total: int, pending: int) -> dict:
    return {
        "id": row.id,
        "title": row.title,
        "kind": row.kind,
        "course_id": row.course_id,
        "class_id": row.class_id,
        "description": row.description,
        "due_at": row.due_at,
        "status": row.status,
        "created_at": row.created_at,
        "submission_count": total,
        "pending_count": pending,
    }


# ---------- 教师端 ----------

@router.post("/teacher/assignments")
def create_assignment(
    req: AssignmentCreate,
    teacher: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    """发布作业:至少指定课程或班级之一"""
    if not is_enabled(db, "feature_assignments"):
        raise HTTPException(status_code=403, detail="作业与考试功能已关闭")
    if not req.course_id and not req.class_id:
        raise HTTPException(status_code=400, detail="请至少指定课程或班级")
    if req.course_id:
        _owned_course(db, req.course_id, teacher)
    if req.class_id:
        classroom = db.query(Classroom).filter(Classroom.id == req.class_id).first()
        if not classroom:
            raise HTTPException(status_code=404, detail="班级不存在")
        if teacher.role != "admin" and classroom.teacher_id != teacher.id:
            raise HTTPException(status_code=403, detail="只能向自己的班级发布作业")

    due_at = req.due_at
    if due_at is None and req.due_days:
        due_at = datetime.utcnow() + timedelta(days=req.due_days)

    row = Assignment(
        teacher_id=teacher.id,
        course_id=req.course_id,
        class_id=req.class_id,
        title=req.title.strip()[:120],
        kind=req.kind,
        description=req.description,
        reference_answer=req.reference_answer,
        due_at=due_at,
        status="published" if req.publish else "draft",
    )
    db.add(row)
    db.flush()
    if row.status == "published":
        notify_task_students(
            db, "assignment", row.id, row.title, row.course_id, row.class_id,
            f"/student/assignments?assignment_id={row.id}",
        )
    db.commit()
    db.refresh(row)
    logger.info("作业发布: %s (teacher=%s)", row.title, teacher.id)
    return _teacher_summary(row, 0, 0)


@router.get("/teacher/assignments")
def list_assignments(
    teacher: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    query = db.query(Assignment)
    if teacher.role != "admin":
        query = query.filter(Assignment.teacher_id == teacher.id)
    rows = query.order_by(Assignment.id.desc()).limit(50).all()
    result = []
    for row in rows:
        total = db.query(func.count(Submission.id)).filter(
            Submission.assignment_id == row.id
        ).scalar() or 0
        pending = db.query(func.count(Submission.id)).filter(
            Submission.assignment_id == row.id,
            Submission.confirmed_at.is_(None),
        ).scalar() or 0
        result.append(_teacher_summary(row, total, pending))
    return result


@router.get("/teacher/assignments/{assignment_id}")
def get_assignment(
    assignment_id: int,
    teacher: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    """作业详情与提交列表(AI 建议与正式成绩分开展示)"""
    row = _owned_assignment(db, assignment_id, teacher)
    subs = (
        db.query(Submission, User)
        .join(User, Submission.student_id == User.id)
        .filter(Submission.assignment_id == row.id)
        .order_by(Submission.id.desc())
        .all()
    )
    submissions = [
        {
            "id": sub.id,
            "student_id": sub.student_id,
            "student_name": user.name,
            "content": sub.content,
            "attachment_url": sub.attachment_url,
            "ai_score": sub.ai_score,
            "ai_feedback": sub.ai_feedback,
            "ai_graded_at": sub.ai_graded_at,
            "score": sub.score,
            "feedback": sub.feedback,
            "confirmed": sub.confirmed_at is not None,
            "confirmed_at": sub.confirmed_at,
            "submitted_at": sub.created_at,
        }
        for sub, user in subs
    ]
    data = _teacher_summary(row, len(submissions), sum(
        1 for s in submissions if not s["confirmed"]
    ))
    data["reference_answer"] = row.reference_answer
    data["submissions"] = submissions
    return data


@router.post("/teacher/assignments/{assignment_id}/publish")
def publish_assignment(
    assignment_id: int,
    teacher: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    row = _owned_assignment(db, assignment_id, teacher)
    row.status = "published"
    notify_task_students(
        db, "assignment", row.id, row.title, row.course_id, row.class_id,
        f"/student/assignments?assignment_id={row.id}",
    )
    db.commit()
    return {"id": row.id, "status": row.status}


@router.post("/teacher/assignments/{assignment_id}/close")
def close_assignment(
    assignment_id: int,
    teacher: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    row = _owned_assignment(db, assignment_id, teacher)
    row.status = "closed"
    db.commit()
    return {"id": row.id, "status": row.status}


@router.post("/teacher/submissions/{submission_id}/ai-grade")
async def ai_grade_submission(
    submission_id: int,
    teacher: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    """生成 AI 建议评分:只写 ai_* 字段,不改变正式成绩"""
    sub = _owned_submission(db, submission_id, teacher)
    assignment = db.query(Assignment).filter(
        Assignment.id == sub.assignment_id
    ).first()
    result = await grade_submission(
        assignment.title, assignment.description, sub.content,
        assignment.reference_answer,
    )
    sub.ai_score = result["score"]
    sub.ai_feedback = result["feedback"]
    sub.ai_graded_at = datetime.utcnow()
    db.commit()
    return {
        "submission_id": sub.id,
        "ai_score": sub.ai_score,
        "ai_feedback": sub.ai_feedback,
        "source": result["source"],
        "confirmed": sub.confirmed_at is not None,
    }


@router.post("/teacher/submissions/{submission_id}/confirm")
def confirm_grade(
    submission_id: int,
    req: GradeConfirmRequest,
    teacher: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    """教师确认评分:写入正式 score/feedback 后学生才可见"""
    sub = _owned_submission(db, submission_id, teacher)
    sub.score = req.score
    sub.feedback = req.feedback if req.feedback is not None else sub.ai_feedback
    sub.confirmed_at = datetime.utcnow()
    sub.confirmed_by = teacher.id
    db.commit()
    return {
        "submission_id": sub.id,
        "score": sub.score,
        "feedback": sub.feedback,
        "confirmed": True,
    }


# ---------- 学生端 ----------

def _student_submission_state(sub: Submission | None, due_passed: bool) -> str:
    if sub is None:
        return "overdue" if due_passed else "not_submitted"
    if sub.confirmed_at is not None:
        return "graded"
    return "pending_review"


@router.get("/student/assignments")
def list_my_assignments(
    student: User = Depends(require_student),
    db: Session = Depends(get_db),
):
    """我的作业:仅已发布且命中目标"""
    conditions = _student_conditions(db, student)
    if not conditions:
        return []
    rows = (
        db.query(Assignment)
        .filter(Assignment.status == "published", or_(*conditions))
        .order_by(Assignment.id.desc())
        .limit(50)
        .all()
    )
    teachers = {
        u.id: u.name for u in db.query(User).filter(
            User.id.in_([r.teacher_id for r in rows] or [0])
        ).all()
    }
    courses = {
        c.id: c.name for c in db.query(Course).filter(
            Course.id.in_([r.course_id for r in rows if r.course_id] or [0])
        ).all()
    }
    subs = {
        s.assignment_id: s for s in db.query(Submission).filter(
            Submission.student_id == student.id,
            Submission.assignment_id.in_([r.id for r in rows] or [0]),
        ).all()
    }
    result = []
    for row in rows:
        sub = subs.get(row.id)
        result.append({
            "id": row.id,
            "title": row.title,
            "kind": row.kind,
            "description": row.description,
            "course_id": row.course_id,
            "course_name": courses.get(row.course_id),
            "teacher_name": teachers.get(row.teacher_id, ""),
            "due_at": row.due_at,
            "created_at": row.created_at,
            "state": _student_submission_state(sub, _due_passed(row)),
            "score": sub.score if sub and sub.confirmed_at else None,
        })
    return result


@router.get("/student/assignments/{assignment_id}")
def get_my_assignment(
    assignment_id: int,
    student: User = Depends(require_student),
    db: Session = Depends(get_db),
):
    """作业详情:截止前不下发参考答案;未确认的 AI 建议不下发"""
    row = _visible_assignment(db, assignment_id, student)
    sub = db.query(Submission).filter(
        Submission.assignment_id == row.id,
        Submission.student_id == student.id,
    ).first()
    due_passed = _due_passed(row)
    my_submission = None
    if sub:
        my_submission = {
            "id": sub.id,
            "content": sub.content,
            "attachment_url": sub.attachment_url,
            "submitted_at": sub.created_at,
            "confirmed": sub.confirmed_at is not None,
            "score": sub.score if sub.confirmed_at else None,
            "feedback": sub.feedback if sub.confirmed_at else None,
        }
    return {
        "id": row.id,
        "title": row.title,
        "kind": row.kind,
        "description": row.description,
        "course_id": row.course_id,
        "due_at": row.due_at,
        "status": row.status,
        "due_passed": due_passed,
        "reference_answer": row.reference_answer if due_passed else None,
        "state": _student_submission_state(sub, due_passed),
        "my_submission": my_submission,
    }


@router.post("/student/assignments/{assignment_id}/submit")
def submit_assignment(
    assignment_id: int,
    req: SubmissionCreate,
    student: User = Depends(require_student),
    db: Session = Depends(get_db),
):
    """提交作业:截止后拒绝;已确认评分的提交不可修改"""
    row = _visible_assignment(db, assignment_id, student)
    if row.status != "published":
        raise HTTPException(status_code=400, detail="作业已关闭，无法提交")
    if _due_passed(row):
        raise HTTPException(status_code=400, detail="已过截止时间，无法提交")

    sub = db.query(Submission).filter(
        Submission.assignment_id == row.id,
        Submission.student_id == student.id,
    ).first()
    if sub and sub.confirmed_at is not None:
        raise HTTPException(status_code=400, detail="作业已批改，不能再次提交")

    if sub is None:
        sub = Submission(
            assignment_id=row.id,
            student_id=student.id,
            content=req.content.strip(),
            attachment_url=req.attachment_url,
        )
        db.add(sub)
    else:
        sub.content = req.content.strip()
        sub.attachment_url = req.attachment_url
        # 内容变更后,旧的 AI 建议失效
        sub.ai_score = None
        sub.ai_feedback = None
        sub.ai_graded_at = None
    db.commit()
    db.refresh(sub)
    return {
        "id": sub.id,
        "assignment_id": row.id,
        "state": "pending_review",
        "submitted_at": sub.created_at,
    }
