"""教师端路由:课程管理 / 素材 / 教案(SSE) / 班级学情 / 知识点草稿 / 导出"""
import json
import logging
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from fastapi import (
    APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, UploadFile, File, Form,
)
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import func, or_

from app.db.session import get_db
from app.core.deps import require_teacher
from app.core.config import settings
from app.models.user import User
from app.models.course import Course, CourseMaterial, KnowledgePoint
from app.models.classroom import Classroom, ClassMember, CourseEnrollment
from app.models.assignment import Assignment, Submission
from app.models.exam import Exam
from app.models.knowledge_draft import KnowledgeDraft
from app.models.log import OperationLog
from app.models.interview_assignment import InterviewAssignment
from app.models.interview import InterviewRecord
from app.models.profile import StudentProfile, MasteryRecord, WrongQuestion, ReviewPlan
from app.schemas.course import (
    CourseCreate, CourseDuplicateRequest, CourseOut, MaterialOut,
)
from app.schemas.agent import ChatRequest
from app.schemas.teacher import (
    LessonPlanRequest, ClassReportOut, WeakPointItem, StudentBrief, ExportRequest,
    DraftAdoptRequest, InterviewAssignmentCreate,
)
from app.agent.tools.doc_generator import doc_generator
from app.agent.tools.stats_analyzer import stats_analyzer
from app.api.chat import stream_agent_response, SSE_HEADERS
from app.services.material_parser import (
    extract_text_async, safe_filename, validate_filename,
)
from app.services.uploads import UploadTooLarge, save_upload_limited
from app.services.course_copy import copy_course_structure
from app.services.kp_generator import generate_draft, dumps
from app.services.content_moderation import (
    moderation_enabled, record_rejection, screen_with_config,
)
from app.services.material_parse_jobs import (
    enqueue as enqueue_parse, material_out, process_parse_job,
)
from app.services.notifications import notify_task_students
from app.services import privacy as privacy_service
from app.services.write_approval import authorize_write, record_executed

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/teacher", tags=["教师端"])

MATERIAL_TYPES = ("courseware", "syllabus", "exercise", "interview")


def _get_owned_course(db: Session, course_id: int, teacher: User) -> Course:
    """校验课程归属:教师只能访问自己的课程,admin 可访问全部"""
    course = db.query(Course).filter(Course.id == course_id).first()
    if not course:
        raise HTTPException(status_code=404, detail="课程不存在或无权访问")
    if teacher.role != "admin" and course.teacher_id != teacher.id:
        raise HTTPException(status_code=404, detail="课程不存在或无权访问")
    return course


def _owned_class_in_course(
    db: Session, class_id: int, course_id: int, teacher: User,
) -> "Classroom":
    """校验班级归属与课程一致(决策 #7 分班独立统计)"""
    from app.models.classroom import Classroom

    classroom = db.query(Classroom).filter(Classroom.id == class_id).first()
    if not classroom:
        raise HTTPException(status_code=404, detail="班级不存在")
    if teacher.role != "admin" and classroom.teacher_id != teacher.id:
        raise HTTPException(status_code=403, detail="只能查看自己班级的学情")
    if classroom.course_id and classroom.course_id != course_id:
        raise HTTPException(status_code=400, detail="班级不属于该课程")
    return classroom


def build_class_report(db: Session, course: Course) -> ClassReportOut:
    """班级学情报表:平均进度 / 薄弱知识点 / 学生简报"""
    course_id = course.id
    profiles = (
        db.query(StudentProfile, User)
        .join(User, StudentProfile.user_id == User.id)
        .filter(StudentProfile.course_id == course_id)
        .all()
    )
    prefs = privacy_service.get_map(db, [u.id for _, u in profiles])
    # 学习记录设为「仅自己」的学生不进入教师报表明细与聚合
    profiles = [
        (p, u) for p, u in profiles
        if privacy_service.learning_visible(prefs.get(u.id), "teacher")
    ]
    if not profiles:
        return ClassReportOut(course_id=course_id, course_name=course.name,
                              student_count=0, avg_progress=0)

    profile_ids = [p.id for p, _ in profiles]
    avg_progress = sum(float(p.overall_progress or 0) for p, _ in profiles) / len(profiles)

    # 薄弱知识点:平均掌握度最低 TOP 10
    weak_rows = (
        db.query(
            KnowledgePoint.id, KnowledgePoint.name,
            func.avg(MasteryRecord.mastery_level).label("avg_mastery"),
        )
        .join(MasteryRecord, MasteryRecord.kp_id == KnowledgePoint.id)
        .filter(MasteryRecord.profile_id.in_(profile_ids))
        .group_by(KnowledgePoint.id, KnowledgePoint.name)
        .order_by(func.avg(MasteryRecord.mastery_level).asc())
        .limit(10)
        .all()
    )
    weak_points = []
    for kp_id, kp_name, avg_m in weak_rows:
        wrong_count = (
            db.query(func.count(WrongQuestion.id))
            .join(MasteryRecord, MasteryRecord.kp_id == WrongQuestion.kp_id)
            .filter(MasteryRecord.profile_id.in_(profile_ids), WrongQuestion.kp_id == kp_id)
            .scalar() or 0
        )
        weak_points.append(WeakPointItem(
            kp_id=kp_id, kp_name=kp_name,
            avg_mastery=round(float(avg_m or 0), 1), wrong_count=wrong_count,
        ))

    # 学生简报
    students = []
    for p, u in profiles:
        weak_count = (
            db.query(func.count(MasteryRecord.id))
            .filter(MasteryRecord.profile_id == p.id, MasteryRecord.mastery_level < 60)
            .scalar() or 0
        )
        students.append(StudentBrief(
            user_id=u.id,
            name=privacy_service.name_of(u, prefs.get(u.id), "teacher"),
            overall_progress=float(p.overall_progress or 0), weak_count=weak_count,
        ))

    return ClassReportOut(
        course_id=course_id, course_name=course.name,
        student_count=len(profiles), avg_progress=round(avg_progress, 1),
        weak_points=weak_points, students=students,
    )


def save_material(db: Session, course_id: int, material_type: str, title: str,
                  file: UploadFile) -> CourseMaterial:
    """保存上传文件并写入素材记录"""
    if material_type not in MATERIAL_TYPES:
        raise HTTPException(status_code=400, detail="素材类型不合法")

    filename = safe_filename(file.filename or "upload")
    validate_filename(filename)

    save_dir = settings.upload_path / str(course_id)
    save_dir.mkdir(parents=True, exist_ok=True)
    file_path = save_dir / filename
    try:
        save_upload_limited(file, file_path, settings.MATERIAL_MAX_BYTES)
    except UploadTooLarge as exc:
        raise HTTPException(
            status_code=413, detail=f"文件超过 {exc.limit_mb}MB 上限",
        ) from exc

    material = CourseMaterial(
        course_id=course_id, type=material_type, title=title,
        file_path=str(file_path), chunk_count=0,
    )
    db.add(material)
    db.commit()
    db.refresh(material)
    logger.info("素材上传: %s (course=%s)", title, course_id)
    return material


# ---------- 课程管理(方案路径) ----------

@router.get("/courses", response_model=List[CourseOut])
def list_my_courses(
    teacher: User = Depends(require_teacher),
    db: Session = Depends(get_db),
    keyword: Optional[str] = None,
    semester: Optional[str] = None,
    audit_status: Optional[str] = None,
    lifecycle: str = "active",
):
    """课程列表:按正常/归档/回收站筛选,教师看自己的,admin 看全部"""
    if lifecycle not in ("active", "archived", "deleted"):
        raise HTTPException(status_code=400, detail="课程生命周期筛选不合法")
    query = db.query(Course)
    if lifecycle == "active":
        query = query.filter(Course.archived_at.is_(None), Course.deleted_at.is_(None))
    elif lifecycle == "archived":
        query = query.filter(Course.archived_at.is_not(None), Course.deleted_at.is_(None))
    else:
        query = query.filter(Course.deleted_at.is_not(None))
    if teacher.role != "admin":
        query = query.filter(Course.teacher_id == teacher.id)

    text = (keyword or "").strip()
    if text:
        like = f"%{text}%"
        query = query.filter(or_(Course.name.like(like), Course.code.like(like)))
    if semester:
        query = query.filter(Course.semester == semester)
    if audit_status:
        query = query.filter(Course.audit_status == audit_status)

    return query.order_by(Course.id.desc()).all()


@router.post("/courses", response_model=CourseOut)
def create_my_course(
    req: CourseCreate,
    teacher: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    """教师创建课程(默认待审核,管理员通过后学生可见)"""
    course = Course(teacher_id=teacher.id, audit_status="pending", **req.model_dump())
    db.add(course)
    db.commit()
    db.refresh(course)
    logger.info("课程创建: %s (teacher=%s)", course.name, teacher.id)
    return course


@router.get("/course-templates")
def list_course_templates(
    teacher: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    """可作为复制模板的正常课程列表(教师自己的课程;admin 为全部),含结构数量"""
    query = db.query(Course).filter(
        Course.archived_at.is_(None), Course.deleted_at.is_(None),
    )
    if teacher.role != "admin":
        query = query.filter(Course.teacher_id == teacher.id)
    courses = query.order_by(Course.id.desc()).all()
    ids = [c.id for c in courses]
    if not ids:
        return {"items": []}

    kp_counts = dict(
        db.query(KnowledgePoint.course_id, func.count(KnowledgePoint.id))
        .filter(KnowledgePoint.course_id.in_(ids))
        .group_by(KnowledgePoint.course_id)
        .all()
    )
    material_counts = dict(
        db.query(CourseMaterial.course_id, func.count(CourseMaterial.id))
        .filter(CourseMaterial.course_id.in_(ids))
        .group_by(CourseMaterial.course_id)
        .all()
    )
    return {"items": [
        {
            "id": c.id,
            "name": c.name,
            "code": c.code,
            "semester": c.semester,
            "audit_status": c.audit_status,
            "knowledge_points": int(kp_counts.get(c.id, 0)),
            "materials": int(material_counts.get(c.id, 0)),
            "created_at": c.created_at,
        }
        for c in courses
    ]}


@router.get("/courses/{course_id}", response_model=CourseOut)
def get_my_course(
    course_id: int,
    teacher: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    return _get_owned_course(db, course_id, teacher)


@router.get("/courses/{course_id}/overview")
def get_course_overview(
    course_id: int,
    teacher: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    """课程概览:素材、知识点、班级、作业、考试一次返回

    管理助手与教师助手都通过这个接口回答“这门课现在什么情况”，
    避免前端或 Agent 连续拼 6-8 个请求。
    """
    course = _get_owned_course(db, course_id, teacher)

    material_rows = (
        db.query(CourseMaterial.type, func.count(CourseMaterial.id))
        .filter(CourseMaterial.course_id == course_id)
        .group_by(CourseMaterial.type)
        .all()
    )
    materials_by_type = {str(kind): int(count) for kind, count in material_rows}
    material_total = sum(materials_by_type.values())

    kp_total = (
        db.query(func.count(KnowledgePoint.id))
        .filter(KnowledgePoint.course_id == course_id)
        .scalar()
        or 0
    )

    classes = (
        db.query(Classroom)
        .filter(Classroom.course_id == course_id, Classroom.status == "active")
        .all()
    )
    class_ids = [item.id for item in classes]
    student_total = 0
    if class_ids:
        student_total = (
            db.query(func.count(func.distinct(ClassMember.student_id)))
            .filter(
                ClassMember.class_id.in_(class_ids),
                ClassMember.status == "active",
                ClassMember.role != "teacher",
            )
            .scalar()
            or 0
        )
    enrollment_total = (
        db.query(func.count(CourseEnrollment.id))
        .filter(CourseEnrollment.course_id == course_id)
        .scalar()
        or 0
    )

    assignments = (
        db.query(Assignment)
        .filter(Assignment.course_id == course_id)
        .all()
    )
    assignment_ids = [item.id for item in assignments]
    assignment_status = {"draft": 0, "published": 0, "closed": 0}
    for item in assignments:
        if item.status in assignment_status:
            assignment_status[item.status] += 1

    pending_grading = 0
    if assignment_ids:
        pending_grading = (
            db.query(func.count(Submission.id))
            .filter(
                Submission.assignment_id.in_(assignment_ids),
                Submission.status == "submitted",
                Submission.confirmed_at.is_(None),
            )
            .scalar()
            or 0
        )

    exams = db.query(Exam).filter(Exam.course_id == course_id).all()
    exam_status = {"draft": 0, "published": 0, "closed": 0}
    for item in exams:
        if item.status in exam_status:
            exam_status[item.status] += 1

    return {
        "course": {
            "id": course.id,
            "name": course.name,
            "code": course.code,
            "semester": course.semester,
            "audit_status": course.audit_status,
            "archived": course.archived_at is not None,
            "created_at": course.created_at,
        },
        "materials": {"total": material_total, "by_type": materials_by_type},
        "knowledge_points": int(kp_total),
        "classes": {
            "total": len(classes),
            "students": int(student_total),
            "enrollments": int(enrollment_total),
        },
        "assignments": {
            "total": len(assignments),
            **assignment_status,
            "pending_grading": int(pending_grading),
        },
        "exams": {"total": len(exams), **exam_status},
    }


@router.get("/courses/{course_id}/students/{student_id}/overview")
def get_student_course_overview(
    course_id: int,
    student_id: int,
    teacher: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    """单个学生的课程学情:进度、薄弱点、错题、复习、面试一次返回

    教师助手回答“这个学生这门课什么情况”时不再跨多个接口拼装。
    """
    course = _get_owned_course(db, course_id, teacher)
    student = db.query(User).filter(User.id == student_id).first()
    if not student or student.role != "student":
        raise HTTPException(status_code=404, detail="学生不存在")

    class_ids = [
        cid for (cid,) in db.query(Classroom.id)
        .filter(Classroom.course_id == course_id).all()
    ]
    enrolled = db.query(CourseEnrollment).filter(
        CourseEnrollment.course_id == course_id,
        CourseEnrollment.student_id == student_id,
    ).first()
    in_class = False
    if class_ids:
        in_class = db.query(ClassMember).filter(
            ClassMember.class_id.in_(class_ids),
            ClassMember.student_id == student_id,
            ClassMember.status == "active",
        ).first() is not None
    if not enrolled and not in_class:
        raise HTTPException(status_code=403, detail="该学生不属于这门课程")

    payload = {
        "course": {"id": course.id, "name": course.name, "code": course.code},
        "student": {
            "id": student.id, "name": student.name, "email": student.email,
            "status": student.status,
        },
        "progress": {"overall_progress": 0.0, "mastery": [], "weak_points": []},
        "wrong_questions": {"total": 0, "recent": []},
        "review_plans": {"pending": 0, "due": 0, "next_review_at": None},
        "interviews": {"total": 0, "avg_score": None, "recent": []},
    }

    profile = db.query(StudentProfile).filter(
        StudentProfile.user_id == student_id,
        StudentProfile.course_id == course_id,
    ).first()
    if not profile:
        return payload

    mastery_rows = (
        db.query(MasteryRecord, KnowledgePoint)
        .join(KnowledgePoint, MasteryRecord.kp_id == KnowledgePoint.id)
        .filter(MasteryRecord.profile_id == profile.id)
        .order_by(MasteryRecord.mastery_level.asc())
        .all()
    )
    mastery = [
        {
            "kp_id": kp.id,
            "kp_name": kp.name,
            "mastery_level": int(rec.mastery_level or 0),
        }
        for rec, kp in mastery_rows
    ]
    payload["progress"] = {
        "overall_progress": float(profile.overall_progress or 0),
        "mastery": mastery,
        "weak_points": [item for item in mastery if item["mastery_level"] < 60][:5],
    }

    payload["wrong_questions"]["total"] = int(
        db.query(func.count(WrongQuestion.id))
        .filter(WrongQuestion.profile_id == profile.id)
        .scalar() or 0
    )
    wrong_rows = (
        db.query(WrongQuestion, KnowledgePoint.name)
        .outerjoin(KnowledgePoint, WrongQuestion.kp_id == KnowledgePoint.id)
        .filter(WrongQuestion.profile_id == profile.id)
        .order_by(WrongQuestion.id.desc())
        .limit(5)
        .all()
    )
    payload["wrong_questions"]["recent"] = [
        {
            "id": item.id,
            "kp_name": kp_name,
            "question_content": item.question_content,
            "error_type": item.error_type,
            "created_at": item.created_at,
        }
        for item, kp_name in wrong_rows
    ]

    review_query = (
        db.query(ReviewPlan)
        .join(WrongQuestion, ReviewPlan.wrong_question_id == WrongQuestion.id)
        .filter(WrongQuestion.profile_id == profile.id)
    )
    pending_plan = review_query.filter(ReviewPlan.status == "pending")
    next_plan = pending_plan.order_by(ReviewPlan.next_review_at.asc()).first()
    payload["review_plans"] = {
        "pending": int(pending_plan.count()),
        "due": int(
            pending_plan.filter(ReviewPlan.next_review_at <= datetime.utcnow()).count()
        ),
        "next_review_at": next_plan.next_review_at if next_plan else None,
    }

    payload["interviews"]["total"] = int(
        db.query(func.count(InterviewRecord.id))
        .filter(InterviewRecord.profile_id == profile.id)
        .scalar() or 0
    )
    avg_score = (
        db.query(func.avg(InterviewRecord.score))
        .filter(
            InterviewRecord.profile_id == profile.id,
            InterviewRecord.score.isnot(None),
        )
        .scalar()
    )
    payload["interviews"]["avg_score"] = (
        round(float(avg_score), 1) if avg_score is not None else None
    )
    payload["interviews"]["recent"] = [
        {
            "id": row.id,
            "round": row.round,
            "question": row.question,
            "score": row.score,
            "created_at": row.created_at,
        }
        for row in db.query(InterviewRecord)
        .filter(InterviewRecord.profile_id == profile.id)
        .order_by(InterviewRecord.id.desc())
        .limit(5)
        .all()
    ]
    return payload


@router.get("/courses/{course_id}/grading-queue")
def get_grading_queue(
    course_id: int,
    assignment_id: Optional[int] = Query(None, description="只看某次作业"),
    class_id: Optional[int] = Query(None, description="只看某个班级"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    teacher: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    """待批改队列:按课程聚合跨作业的待批改提交

    只返回已正式提交且教师尚未确认的提交,支持按作业、班级筛选。
    """
    _get_owned_course(db, course_id, teacher)

    query = (
        db.query(Submission, Assignment, User)
        .join(Assignment, Submission.assignment_id == Assignment.id)
        .join(User, Submission.student_id == User.id)
        .filter(
            Assignment.course_id == course_id,
            Submission.status == "submitted",
            Submission.confirmed_at.is_(None),
        )
    )
    if assignment_id is not None:
        query = query.filter(Assignment.id == assignment_id)
    if class_id is not None:
        query = query.filter(Assignment.class_id == class_id)

    total = query.count()
    rows = (
        query.order_by(Submission.submitted_at.desc(), Submission.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    items = [
        {
            "submission_id": sub.id,
            "assignment_id": assignment.id,
            "assignment_title": assignment.title,
            "assignment_kind": assignment.kind,
            "class_id": assignment.class_id,
            "student_id": student.id,
            "student_name": student.name,
            "submitted_at": sub.submitted_at or sub.created_at,
            "ai_score": sub.ai_score,
            "ai_feedback": (sub.ai_feedback or "")[:200],
            "has_ai_suggestion": sub.ai_graded_at is not None,
        }
        for sub, assignment, student in rows
    ]

    return {
        "course_id": course_id,
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": items,
    }


@router.put("/courses/{course_id}", response_model=CourseOut)
def update_my_course(
    course_id: int,
    req: CourseCreate,
    teacher: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    course = _get_owned_course(db, course_id, teacher)
    course.name = req.name
    course.code = req.code
    course.syllabus = req.syllabus
    course.semester = req.semester
    db.commit()
    db.refresh(course)
    return course


@router.post("/courses/{course_id}/archive", response_model=CourseOut)
def archive_my_course(
    course_id: int,
    teacher: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    course = _get_owned_course(db, course_id, teacher)
    if course.deleted_at is not None:
        raise HTTPException(status_code=400, detail="回收站课程不能归档，请先恢复")
    course.archived_at = datetime.utcnow()
    db.commit()
    db.refresh(course)
    return course


@router.delete("/courses/{course_id}")
def delete_my_course(
    course_id: int,
    teacher: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    course = _get_owned_course(db, course_id, teacher)
    course.deleted_at = datetime.utcnow()
    db.commit()
    return {"id": course_id, "deleted": True}


@router.post("/courses/{course_id}/restore", response_model=CourseOut)
def restore_my_course(
    course_id: int,
    teacher: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    course = _get_owned_course(db, course_id, teacher)
    course.archived_at = None
    course.deleted_at = None
    db.commit()
    db.refresh(course)
    return course


@router.post("/courses/{course_id}/duplicate", response_model=CourseOut)
def duplicate_my_course(
    course_id: int,
    req: CourseDuplicateRequest,
    teacher: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    """复制自己的课程结构(课程信息 + 知识点树 + 素材元数据)

    不复制选课关系、学情、班级、作业/考试与提交;新课程归属当前教师。
    """
    source = _get_owned_course(db, course_id, teacher)

    name = (req.name or "").strip() or None
    code = (req.code or "").strip() or None
    semester = (req.semester or "").strip() or None
    if code and db.query(Course).filter(Course.code == code).first():
        raise HTTPException(status_code=400, detail="课程代码已存在")

    new_course, stats = copy_course_structure(
        db, source, teacher.id, name=name, code=code, semester=semester,
        # 已通过审核的课程复制后仍通过;未过审课程副本需重新审核
        audit_status="approved" if source.audit_status == "approved" else "pending",
    )
    db.add(OperationLog(
        admin_id=teacher.id,
        action="course_duplicate",
        target_type="course",
        target_id=new_course.id,
        detail=json.dumps({
            "source_course_id": source.id,
            "knowledge_points": stats["knowledge_points"],
            "materials": stats["materials"],
        }, ensure_ascii=False),
    ))
    db.commit()
    db.refresh(new_course)
    logger.info("课程复制: source=%s -> new=%s (teacher=%s)",
                source.id, new_course.id, teacher.id)
    return new_course


# ---------- 素材上传(方案路径) ----------

@router.post("/materials", response_model=MaterialOut)
def upload_material(
    background_tasks: BackgroundTasks,
    course_id: int = Form(...),
    type: str = Form(...),
    title: str = Form(...),
    file: UploadFile = File(...),
    teacher: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    """上传课件素材:解析与内容审核在后台异步执行"""
    _get_owned_course(db, course_id, teacher)
    material = save_material(db, course_id, type, title, file)
    job = enqueue_parse(db, material)
    background_tasks.add_task(process_parse_job, job.id)
    return material_out(material, job)


# ---------- 教案生成(SSE) ----------

@router.post("/lesson-plan")
def generate_lesson_plan(
    req: LessonPlanRequest,
    request: Request,
    teacher: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    """生成教案框架(SSE,复用 Agent 图 teacher 分支)"""
    course = _get_owned_course(db, req.course_id, teacher)

    msg = f"请为课程《{course.name}》生成教案框架。"
    if req.chapter:
        msg += f"指定章节:{req.chapter}。"
    if req.hours:
        msg += f"课时数:{req.hours}。"
    msg += "要求给出教学目标、重难点、教学环节与时间分配,供教师审核修改。"

    chat_req = ChatRequest(session_id=None, course_id=req.course_id, message=msg)
    return StreamingResponse(
        stream_agent_response(chat_req, teacher, db, force_branch="teacher", request=request),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


# ---------- 班级学情报表 ----------

@router.get("/class-report", response_model=ClassReportOut)
def class_report(
    course_id: int = Query(...),
    teacher: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    """班级学情报表(旧路径)"""
    course = _get_owned_course(db, course_id, teacher)
    return build_class_report(db, course)


@router.get("/class-report/{course_id}", response_model=ClassReportOut)
def class_report_by_path(
    course_id: int,
    teacher: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    """班级学情报表(方案路径)"""
    course = _get_owned_course(db, course_id, teacher)
    return build_class_report(db, course)


# ---------- 导出 ----------

@router.post("/export")
def export_document(
    req: ExportRequest,
    teacher: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    """导出教案 / 预习单 / 学情报表(调用 doc_generator 工具)"""
    if req.type not in ("lesson_plan", "preview_sheet", "report"):
        raise HTTPException(status_code=400, detail="导出类型不合法")

    # 将上下文信息并入 data 供模板渲染
    payload = {**req.data, "course_id": req.course_id, "teacher_name": teacher.name}
    result = doc_generator(doc_type=req.type, data=payload)
    if result.get("error"):
        raise HTTPException(status_code=500, detail=result["error"])
    return result


# ---------- 学情统计 ----------

@router.get("/stats/weakness")
def weakness_stats(
    course_id: int = Query(...),
    class_id: int | None = Query(None),
    top_n: int = Query(10, le=50),
    teacher: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    """薄弱知识点统计(调用 stats_analyzer,可按班级独立统计)"""
    _get_owned_course(db, course_id, teacher)
    if class_id:
        _owned_class_in_course(db, class_id, course_id, teacher)
    return stats_analyzer(course_id=course_id, metric="weakness", top_n=top_n,
                          user_id=teacher.id, class_id=class_id)


@router.get("/stats/progress")
def progress_stats(
    course_id: int = Query(...),
    class_id: int | None = Query(None),
    teacher: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    """班级进度统计(调用 stats_analyzer,可按班级独立统计)"""
    _get_owned_course(db, course_id, teacher)
    if class_id:
        _owned_class_in_course(db, class_id, course_id, teacher)
    return stats_analyzer(course_id=course_id, metric="progress",
                          user_id=teacher.id, class_id=class_id)


@router.get("/stats/distribution")
def distribution_stats(
    course_id: int = Query(...),
    class_id: int | None = Query(None),
    teacher: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    """掌握度分布统计(调用 stats_analyzer,可按班级独立统计)"""
    _get_owned_course(db, course_id, teacher)
    if class_id:
        _owned_class_in_course(db, class_id, course_id, teacher)
    return stats_analyzer(course_id=course_id, metric="distribution",
                          user_id=teacher.id, class_id=class_id)

# ---------- 知识点/大纲草稿 ----------

def _owned_draft(db: Session, draft_id: int, teacher: User) -> KnowledgeDraft:
    draft = db.query(KnowledgeDraft).filter(KnowledgeDraft.id == draft_id).first()
    if not draft:
        raise HTTPException(status_code=404, detail="草稿不存在")
    if teacher.role != "admin" and draft.teacher_id != teacher.id:
        raise HTTPException(status_code=403, detail="只能操作自己的草稿")
    return draft


def _walk_nodes(nodes, prefix=""):
    """遍历草稿树,产出 (path, node)"""
    for i, node in enumerate(nodes or []):
        path = f"{i}" if not prefix else f"{prefix}-{i}"
        yield path, node
        for child_path, child in _walk_nodes(node.get("children") or [], path):
            yield child_path, child


@router.post("/courses/{course_id}/kp-drafts")
async def create_kp_draft(
    course_id: int,
    file: UploadFile = File(...),
    teacher: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    """上传课程目录/大纲,由 Agent 解析为知识点与大纲草稿(不直接入库)"""
    course = _get_owned_course(db, course_id, teacher)

    filename = safe_filename(file.filename or "upload")
    suffix = Path(filename).suffix.lower()
    validate_filename(filename)
    save_dir = settings.upload_path / str(course_id) / "drafts"
    save_dir.mkdir(parents=True, exist_ok=True)
    save_path = save_dir / f"{uuid.uuid4().hex}{suffix}"
    with save_path.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    text = await extract_text_async(save_path, filename)
    if moderation_enabled(db):
        verdict = screen_with_config(db, text)
        if verdict["flagged"]:
            save_path.unlink(missing_ok=True)
            record_rejection(db, teacher.id, text, verdict, "知识点大纲")
            db.commit()
            raise HTTPException(status_code=400, detail="文件内容未通过审核，请修改后重试")
    payload = await generate_draft(course.name, text)

    draft = KnowledgeDraft(
        course_id=course_id,
        teacher_id=teacher.id,
        filename=file.filename,
        source_text_length=len(text),
        payload=dumps(payload),
        status="draft",
    )
    db.add(draft)
    db.commit()
    db.refresh(draft)
    return {
        "id": draft.id,
        "filename": draft.filename,
        "status": draft.status,
        "payload": payload,
    }


@router.get("/courses/{course_id}/kp-drafts")
def list_kp_drafts(
    course_id: int,
    teacher: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    _get_owned_course(db, course_id, teacher)
    rows = (
        db.query(KnowledgeDraft)
        .filter(KnowledgeDraft.course_id == course_id)
        .order_by(KnowledgeDraft.id.desc())
        .limit(20)
        .all()
    )
    return [
        {
            "id": r.id,
            "filename": r.filename,
            "status": r.status,
            "created_at": r.created_at,
            "payload": json.loads(r.payload),
        }
        for r in rows
    ]


@router.post("/kp-drafts/{draft_id}/adopt")
def adopt_kp_draft(
    draft_id: int,
    req: DraftAdoptRequest,
    teacher: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    """采纳草稿:按路径创建正式知识点,可选同步课程大纲"""
    draft = _owned_draft(db, draft_id, teacher)
    if draft.status == "adopted":
        raise HTTPException(status_code=400, detail="该草稿已采纳")

    action = authorize_write(
        db, teacher, "course.kp_adopt", confirmed=True,
        target_type="knowledge_draft", target_id=draft.id,
        detail={"course_id": draft.course_id, "adopt_all": req.adopt_all},
    )
    payload = json.loads(draft.payload)
    nodes = payload.get("knowledge_points") or []

    selected = set()
    if req.adopt_all:
        selected = {path for path, _ in _walk_nodes(nodes)}
    else:
        for path in req.paths:
            current = path
            while current:
                selected.add(current)
                current = current.rsplit("-", 1)[0] if "-" in current else ""

    existing = {
        kp.name
        for kp in db.query(KnowledgePoint).filter(KnowledgePoint.course_id == draft.course_id).all()
    }
    created_ids = {}
    created = 0
    skipped = 0

    for path, node in _walk_nodes(nodes):
        if path not in selected:
            continue
        name = (node.get("name") or "").strip()[:100]
        if not name:
            continue
        if name in existing:
            skipped += 1
            continue
        parent_id = None
        if "-" in path:
            parent_id = created_ids.get(path.rsplit("-", 1)[0])
        kp = KnowledgePoint(
            course_id=draft.course_id,
            name=name,
            description=(node.get("description") or "")[:500],
            parent_id=parent_id,
        )
        db.add(kp)
        db.flush()
        created_ids[path] = kp.id
        existing.add(name)
        created += 1

    if req.apply_syllabus:
        final_syllabus = req.syllabus if req.syllabus is not None else payload.get("syllabus")
        if final_syllabus:
            course = db.query(Course).filter(Course.id == draft.course_id).first()
            if course:
                course.syllabus = final_syllabus

    draft.status = "adopted"
    record_executed(
        db, teacher, action, target_type="knowledge_draft", target_id=draft.id,
        detail={"created": created, "skipped": skipped},
    )
    db.commit()
    return {
        "draft_id": draft.id,
        "created": created,
        "skipped": skipped,
        "syllabus_applied": bool(req.apply_syllabus and (req.syllabus or payload.get("syllabus"))),
    }


@router.delete("/kp-drafts/{draft_id}")
def discard_kp_draft(
    draft_id: int,
    teacher: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    draft = _owned_draft(db, draft_id, teacher)
    draft.status = "discarded"
    db.commit()
    return {"draft_id": draft.id, "status": draft.status}


# ---------- 面试作业 ----------

@router.post("/interview-assignments")
def create_interview_assignment(
    req: InterviewAssignmentCreate,
    teacher: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    """发布面试作业:指定班级或课程,学生端仅在发布后可见"""
    if not req.class_id and not req.course_id:
        raise HTTPException(status_code=400, detail="请至少指定班级或课程")
    if req.course_id:
        _get_owned_course(db, req.course_id, teacher)
    if req.class_id:
        from app.models.classroom import Classroom
        classroom = db.query(Classroom).filter(Classroom.id == req.class_id).first()
        if not classroom:
            raise HTTPException(status_code=404, detail="班级不存在")
        if teacher.role != "admin" and classroom.teacher_id != teacher.id:
            raise HTTPException(status_code=403, detail="只能向自己的班级发布")

    from datetime import datetime as _dt, timedelta as _td
    due_at = _dt.utcnow() + _td(days=req.due_days) if req.due_days else None
    row = InterviewAssignment(
        teacher_id=teacher.id,
        class_id=req.class_id,
        course_id=req.course_id,
        title=req.title.strip()[:120],
        description=req.description,
        due_at=due_at,
        duration_minutes=req.duration_minutes,
        status="active",
    )
    db.add(row)
    db.flush()
    notify_task_students(
        db, "interview", row.id, row.title, row.course_id, row.class_id,
        f"/student/interview?assignment_id={row.id}",
    )
    db.commit()
    db.refresh(row)
    return {
        "id": row.id, "title": row.title, "class_id": row.class_id,
        "course_id": row.course_id, "due_at": row.due_at,
        "duration_minutes": row.duration_minutes, "status": row.status,
    }


@router.get("/interview-assignments")
def list_interview_assignments(
    teacher: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    query = db.query(InterviewAssignment)
    if teacher.role != "admin":
        query = query.filter(InterviewAssignment.teacher_id == teacher.id)
    rows = query.order_by(InterviewAssignment.id.desc()).limit(50).all()
    return [
        {
            "id": r.id, "title": r.title, "class_id": r.class_id,
            "course_id": r.course_id, "description": r.description,
            "due_at": r.due_at, "duration_minutes": r.duration_minutes,
            "status": r.status, "created_at": r.created_at,
        }
        for r in rows
    ]


@router.get("/interview-records")
def list_shared_interview_records(
    course_id: Optional[int] = None,
    assignment_id: Optional[int] = None,
    teacher: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    """仅查看学生授权且归属本人课程或本人面试作业的记录"""
    query = (
        db.query(InterviewRecord, StudentProfile, Course, InterviewAssignment, User)
        .join(StudentProfile, InterviewRecord.profile_id == StudentProfile.id)
        .join(Course, StudentProfile.course_id == Course.id)
        .join(User, StudentProfile.user_id == User.id)
        .outerjoin(InterviewAssignment, InterviewRecord.assignment_id == InterviewAssignment.id)
        .filter(InterviewRecord.visibility == "teacher")
    )
    if teacher.role != "admin":
        query = query.filter(or_(
            Course.teacher_id == teacher.id,
            InterviewAssignment.teacher_id == teacher.id,
        ))
    if course_id is not None:
        query = query.filter(StudentProfile.course_id == course_id)
    if assignment_id is not None:
        query = query.filter(InterviewRecord.assignment_id == assignment_id)

    rows = query.order_by(InterviewRecord.created_at.desc(), InterviewRecord.id.desc()).limit(100).all()
    return [
        {
            "id": record.id,
            "profile_id": record.profile_id,
            "student_id": student.id,
            "student_name": student.name,
            "course_id": course.id,
            "course_name": course.name,
            "assignment_id": record.assignment_id,
            "assignment_title": assignment.title if assignment else None,
            "round": record.round,
            "question": record.question,
            "answer": record.answer,
            "score": record.score,
            "score_dimensions": record.score_dimensions,
            "feedback": record.feedback,
            "visibility": record.visibility,
            "created_at": record.created_at,
        }
        for record, profile, course, assignment, student in rows
    ]


@router.delete("/interview-assignments/{assignment_id}")
def close_interview_assignment(
    assignment_id: int,
    teacher: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    row = db.query(InterviewAssignment).filter(
        InterviewAssignment.id == assignment_id
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="面试作业不存在")
    if teacher.role != "admin" and row.teacher_id != teacher.id:
        raise HTTPException(status_code=403, detail="只能关闭自己发布的面试作业")
    row.status = "closed"
    db.commit()
    return {"id": row.id, "status": row.status}
