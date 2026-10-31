"""课程路由:课程 CRUD / 知识点 / 教材上传"""
import logging
import shutil
from typing import List

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.core.deps import get_current_user, require_teacher
from app.core.config import settings
from app.models.user import User
from app.models.course import Course, CourseMaterial, KnowledgePoint
from app.models.classroom import CourseEnrollment
from app.schemas.course import CourseCreate, CourseOut, MaterialOut
from app.services.course_access import assert_course_visible, visible_course_ids

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/course", tags=["课程"])


# ---------- 课程 ----------

@router.get("/list", response_model=List[CourseOut])
def list_courses(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """教师:自己创建的课程;学生:已加入的课程;管理员:全部"""
    if user.role == "admin":
        return db.query(Course).all()
    ids = visible_course_ids(user, db)
    if not ids:
        return []
    return db.query(Course).filter(Course.id.in_(ids)).all()


@router.post("/create", response_model=CourseOut)
def create_course(
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


@router.get("/{course_id}", response_model=CourseOut)
def get_course(
    course_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    course = assert_course_visible(user, course_id, db)
    return course


# ---------- 知识点 ----------

@router.get("/{course_id}/knowledge-points")
def list_knowledge_points(
    course_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """课程的知识点树(需课程可见)"""
    assert_course_visible(user, course_id, db)
    kps = db.query(KnowledgePoint).filter(KnowledgePoint.course_id == course_id).all()
    return [
        {"id": kp.id, "name": kp.name, "description": kp.description, "parent_id": kp.parent_id}
        for kp in kps
    ]


@router.post("/{course_id}/knowledge-points")
def add_knowledge_point(
    course_id: int,
    name: str = Form(...),
    description: str = Form(""),
    parent_id: int = Form(None),
    teacher: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    """教师添加知识点(仅课程归属教师或管理员)"""
    course = assert_course_visible(teacher, course_id, db)
    if teacher.role == "teacher" and course.teacher_id != teacher.id:
        raise HTTPException(status_code=403, detail="只能维护自己的课程")
    kp = KnowledgePoint(course_id=course_id, name=name, description=description, parent_id=parent_id)
    db.add(kp)
    db.commit()
    db.refresh(kp)
    return {"id": kp.id, "name": kp.name}


# ---------- 教材上传 ----------

@router.post("/{course_id}/materials", response_model=MaterialOut)
async def upload_material(
    course_id: int,
    type: str = Form(...),          # courseware/syllabus/exercise/interview
    title: str = Form(...),
    file: UploadFile = File(...),
    teacher: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    """教师上传课件素材(仅课程归属教师或管理员)"""
    if type not in ("courseware", "syllabus", "exercise", "interview"):
        raise HTTPException(status_code=400, detail="素材类型不合法")

    course = assert_course_visible(teacher, course_id, db)
    if teacher.role == "teacher" and course.teacher_id != teacher.id:
        raise HTTPException(status_code=403, detail="只能维护自己的课程")

    save_dir = settings.upload_path / str(course_id)
    save_dir.mkdir(parents=True, exist_ok=True)
    file_path = save_dir / file.filename
    with file_path.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    material = CourseMaterial(
        course_id=course_id, type=type, title=title,
        file_path=str(file_path), chunk_count=0,
    )
    db.add(material)
    db.commit()
    db.refresh(material)
    logger.info("素材上传: %s (course=%s)", title, course_id)
    return material


@router.get("/{course_id}/materials", response_model=List[MaterialOut])
def list_materials(
    course_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    assert_course_visible(user, course_id, db)
    return db.query(CourseMaterial).filter(CourseMaterial.course_id == course_id).all()