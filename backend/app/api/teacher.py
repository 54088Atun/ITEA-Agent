"""教师端路由:课程管理 / 素材 / 教案(SSE) / 班级学情 / 知识点草稿 / 导出"""
import json
import logging
import shutil
import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query, Request, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.db.session import get_db
from app.core.deps import require_teacher
from app.core.config import settings
from app.models.user import User
from app.models.course import Course, CourseMaterial, KnowledgePoint
from app.models.knowledge_draft import KnowledgeDraft
from app.models.interview_assignment import InterviewAssignment
from app.models.profile import StudentProfile, MasteryRecord, WrongQuestion
from app.schemas.course import CourseCreate, CourseOut, MaterialOut
from app.schemas.agent import ChatRequest
from app.schemas.teacher import (
    LessonPlanRequest, ClassReportOut, WeakPointItem, StudentBrief, ExportRequest,
    DraftAdoptRequest, InterviewAssignmentCreate,
)
from app.agent.tools.doc_generator import doc_generator
from app.agent.tools.stats_analyzer import stats_analyzer
from app.api.chat import stream_agent_response, SSE_HEADERS
from app.services.material_parser import extract_text
from app.services.kp_generator import generate_draft, dumps
from app.services.notifications import notify_task_students

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


def build_class_report(db: Session, course: Course) -> ClassReportOut:
    """班级学情报表:平均进度 / 薄弱知识点 / 学生简报"""
    course_id = course.id
    profiles = (
        db.query(StudentProfile, User)
        .join(User, StudentProfile.user_id == User.id)
        .filter(StudentProfile.course_id == course_id)
        .all()
    )
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
            user_id=u.id, name=u.name,
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

    save_dir = settings.upload_path / str(course_id)
    save_dir.mkdir(parents=True, exist_ok=True)
    file_path = save_dir / file.filename
    with file_path.open("wb") as f:
        shutil.copyfileobj(file.file, f)

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
):
    """课程列表:教师看自己的,admin 看全部"""
    query = db.query(Course)
    if teacher.role != "admin":
        query = query.filter(Course.teacher_id == teacher.id)
    return query.order_by(Course.id.desc()).all()


@router.post("/courses", response_model=CourseOut)
def create_my_course(
    req: CourseCreate,
    teacher: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    """教师创建课程(默认审核通过,不影响既有流程)"""
    course = Course(teacher_id=teacher.id, audit_status="approved", **req.model_dump())
    db.add(course)
    db.commit()
    db.refresh(course)
    logger.info("课程创建: %s (teacher=%s)", course.name, teacher.id)
    return course


@router.get("/courses/{course_id}", response_model=CourseOut)
def get_my_course(
    course_id: int,
    teacher: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    return _get_owned_course(db, course_id, teacher)


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


# ---------- 素材上传(方案路径) ----------

@router.post("/materials", response_model=MaterialOut)
def upload_material(
    course_id: int = Form(...),
    type: str = Form(...),
    title: str = Form(...),
    file: UploadFile = File(...),
    teacher: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    """上传课件素材(触发向量化由入库脚本完成)"""
    _get_owned_course(db, course_id, teacher)
    return save_material(db, course_id, type, title, file)


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
    top_n: int = Query(10, le=50),
    teacher: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    """薄弱知识点统计(调用 stats_analyzer)"""
    _get_owned_course(db, course_id, teacher)
    return stats_analyzer(course_id=course_id, metric="weakness", top_n=top_n)


@router.get("/stats/progress")
def progress_stats(
    course_id: int = Query(...),
    teacher: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    """班级进度统计(调用 stats_analyzer)"""
    _get_owned_course(db, course_id, teacher)
    return stats_analyzer(course_id=course_id, metric="progress")


@router.get("/stats/distribution")
def distribution_stats(
    course_id: int = Query(...),
    teacher: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    """掌握度分布统计(调用 stats_analyzer)"""
    _get_owned_course(db, course_id, teacher)
    return stats_analyzer(course_id=course_id, metric="distribution")

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

    suffix = f".{file.filename.rsplit('.', 1)[-1].lower()}" if "." in (file.filename or "") else ""
    save_dir = settings.upload_path / str(course_id) / "drafts"
    save_dir.mkdir(parents=True, exist_ok=True)
    save_path = save_dir / f"{uuid.uuid4().hex}{suffix}"
    with save_path.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    text = extract_text(save_path, file.filename or "")
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
        "course_id": row.course_id, "due_at": row.due_at, "status": row.status,
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
            "due_at": r.due_at, "status": r.status, "created_at": r.created_at,
        }
        for r in rows
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
