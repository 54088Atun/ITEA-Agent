"""课程路由:课程 CRUD / 知识点 / 教材上传"""
import logging
import mimetypes
import os
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, UploadFile, File, Form
from fastapi.responses import FileResponse
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.core.deps import get_current_user, require_teacher
from app.core.config import settings
from app.models.user import User
from app.models.course import Course, CourseMaterial, KnowledgePoint, MaterialParseJob
from app.models.classroom import CourseCollaborator, CourseEnrollment
from app.schemas.course import (
    CourseCollaboratorAdd, CourseCreate, CourseOut, MaterialOut, MaterialUpdate,
)
from app.services.course_access import assert_course_visible, visible_course_ids
from app.services.material_parser import safe_filename, validate_filename
from app.services.uploads import UploadTooLarge, save_upload_limited
from app.services.material_parse_jobs import (
    enqueue as enqueue_parse, material_out, process_parse_job,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/course", tags=["课程"])


# ---------- 课程 ----------

@router.get("/list", response_model=List[CourseOut])
def list_courses(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    keyword: Optional[str] = None,
    semester: Optional[str] = None,
    audit_status: Optional[str] = None,
):
    """教师:自己创建或协作的课程;学生:已加入的课程;管理员:全部

    支持名称/代码搜索与学期、审核状态筛选。
    """
    query = db.query(Course).filter(Course.deleted_at.is_(None))
    if user.role != "admin":
        ids = visible_course_ids(user, db)
        if not ids:
            return []
        query = query.filter(Course.id.in_(ids))

    text = (keyword or "").strip()
    if text:
        like = f"%{text}%"
        query = query.filter(or_(Course.name.like(like), Course.code.like(like)))
    if semester:
        query = query.filter(Course.semester == semester)
    if audit_status:
        query = query.filter(Course.audit_status == audit_status)

    return query.order_by(Course.id.desc()).all()


@router.post("/create", response_model=CourseOut)
def create_course(
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


def _assert_course_owner(user: User, course_id: int, db: Session) -> Course:
    """协作者管理仅限课程拥有者或管理员"""
    course = assert_course_visible(user, course_id, db)
    if user.role != "admin" and course.teacher_id != user.id:
        raise HTTPException(status_code=403, detail="只有课程拥有者可管理协作者")
    return course


def _assert_material_manager(user: User, course_id: int, db: Session) -> Course:
    """课件管理权限:课程创建者或管理员"""
    course = assert_course_visible(user, course_id, db)
    if user.role != "admin" and course.teacher_id != user.id:
        raise HTTPException(status_code=403, detail="只有课程创建者或管理员可管理课件")
    return course


def _collaborator_out(row: CourseCollaborator, teacher: User) -> dict:
    return {
        "id": row.id,
        "course_id": row.course_id,
        "teacher_id": teacher.id,
        "teacher_name": teacher.name,
        "teacher_email": teacher.email,
        "added_by": row.added_by,
        "created_at": row.created_at,
    }


@router.get("/teachers")
def search_teachers(
    keyword: str = Query("", max_length=50),
    course_id: Optional[int] = Query(
        None, description="传入课程时排除课程拥有者与已有协作者",
    ),
    teacher: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    """教师目录检索:按姓名或邮箱搜索有效教师账号,用于选择课程协作教师"""
    query = db.query(User).filter(User.role == "teacher", User.status == "active")
    text = (keyword or "").strip()
    if text:
        like = f"%{text}%"
        query = query.filter(or_(User.name.like(like), User.email.like(like)))
    if course_id is not None:
        course = _assert_course_owner(teacher, course_id, db)
        collaborator_ids = [
            row.teacher_id for row in
            db.query(CourseCollaborator)
            .filter(CourseCollaborator.course_id == course_id)
            .all()
        ]
        query = query.filter(User.id != course.teacher_id)
        if collaborator_ids:
            query = query.filter(User.id.notin_(collaborator_ids))
    rows = query.order_by(User.name.asc()).limit(20).all()
    return [
        {"id": row.id, "name": row.name, "email": row.email}
        for row in rows
    ]


@router.get("/{course_id}/collaborators")
def list_collaborators(
    course_id: int,
    teacher: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    _assert_course_owner(teacher, course_id, db)
    rows = db.query(CourseCollaborator, User).join(
        User, User.id == CourseCollaborator.teacher_id,
    ).filter(CourseCollaborator.course_id == course_id).order_by(CourseCollaborator.id).all()
    return [_collaborator_out(row, user) for row, user in rows]


@router.post("/{course_id}/collaborators")
def add_collaborator(
    course_id: int,
    req: CourseCollaboratorAdd,
    teacher: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    course = _assert_course_owner(teacher, course_id, db)
    target = db.get(User, req.teacher_id)
    if not target or target.role != "teacher" or target.status != "active":
        raise HTTPException(status_code=400, detail="协作者必须是有效教师账号")
    if target.id == course.teacher_id:
        raise HTTPException(status_code=400, detail="课程拥有者无需添加为协作者")

    row = db.query(CourseCollaborator).filter(
        CourseCollaborator.course_id == course_id,
        CourseCollaborator.teacher_id == target.id,
    ).first()
    if not row:
        row = CourseCollaborator(course_id=course_id, teacher_id=target.id, added_by=teacher.id)
        db.add(row)
        db.commit()
        db.refresh(row)
    return _collaborator_out(row, target)


@router.delete("/{course_id}/collaborators/{teacher_id}")
def remove_collaborator(
    course_id: int,
    teacher_id: int,
    teacher: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    _assert_course_owner(teacher, course_id, db)
    row = db.query(CourseCollaborator).filter(
        CourseCollaborator.course_id == course_id,
        CourseCollaborator.teacher_id == teacher_id,
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="协作者不存在")
    db.delete(row)
    db.commit()
    return {"ok": True}


@router.get("/{course_id}", response_model=CourseOut)
def get_course(
    course_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    course = assert_course_visible(user, course_id, db)
    return course


@router.get("/{course_id}/search")
def search_course_materials(
    course_id: int,
    q: str = Query(..., min_length=1, description="检索问题或关键词"),
    top_k: int = Query(5, ge=1, le=10),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """课程知识库检索内部接口:供 Agent 运行时按需调用"""
    assert_course_visible(user, course_id, db)
    from app.agent.tools.rag_search import rag_search

    result = rag_search(query=q, course_id=course_id, top_k=top_k, user_id=user.id)
    return {
        "course_id": course_id,
        "context": result.get("context", ""),
        "fragments": result.get("fragments", []),
    }


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
    """教师添加知识点(仅课程拥有者、协作者或管理员)"""
    assert_course_visible(teacher, course_id, db)
    kp = KnowledgePoint(course_id=course_id, name=name, description=description, parent_id=parent_id)
    db.add(kp)
    db.commit()
    db.refresh(kp)
    return {"id": kp.id, "name": kp.name}


# ---------- 教材上传 ----------

@router.post("/{course_id}/materials", response_model=MaterialOut)
def upload_material(
    course_id: int,
    background_tasks: BackgroundTasks,
    type: str = Form(...),          # courseware/syllabus/exercise/interview
    title: str = Form(...),
    file: UploadFile = File(...),
    teacher: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    """教师上传课件素材:立即返回,解析与内容审核在后台异步执行"""
    if type not in ("courseware", "syllabus", "exercise", "interview"):
        raise HTTPException(status_code=400, detail="素材类型不合法")

    _assert_material_manager(teacher, course_id, db)

    save_dir = settings.upload_path / str(course_id)
    save_dir.mkdir(parents=True, exist_ok=True)
    filename = safe_filename(file.filename or "upload")
    validate_filename(filename)
    file_path = save_dir / filename
    try:
        save_upload_limited(file, file_path, settings.MATERIAL_MAX_BYTES)
    except UploadTooLarge as exc:
        raise HTTPException(
            status_code=413, detail=f"文件超过 {exc.limit_mb}MB 上限",
        ) from exc

    material = CourseMaterial(
        course_id=course_id, type=type, title=title,
        file_path=str(file_path), chunk_count=0,
        moderation_status="pending",
    )
    db.add(material)
    db.commit()
    db.refresh(material)

    job = enqueue_parse(db, material)
    background_tasks.add_task(process_parse_job, job.id)
    logger.info("素材上传: %s (course=%s, job=%s)", title, course_id, job.id)
    return material_out(material, job)


@router.get("/{course_id}/materials", response_model=List[MaterialOut])
def list_materials(
    course_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """素材列表:附带解析进度;学生看不到审核未通过的素材"""
    assert_course_visible(user, course_id, db)
    query = db.query(CourseMaterial).filter(CourseMaterial.course_id == course_id)
    if user.role not in ("teacher", "admin"):
        query = query.filter(CourseMaterial.moderation_status != "rejected")
    materials = query.order_by(CourseMaterial.id.desc()).all()

    ids = [m.id for m in materials]
    jobs = {}
    if ids:
        rows = db.query(MaterialParseJob).filter(
            MaterialParseJob.material_id.in_(ids),
        ).all()
        jobs = {row.material_id: row for row in rows}
    return [material_out(m, jobs.get(m.id)) for m in materials]


@router.post(
    "/{course_id}/materials/{material_id}/parse/retry",
    response_model=MaterialOut,
)
def retry_material_parse(
    course_id: int,
    material_id: int,
    background_tasks: BackgroundTasks,
    teacher: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    """重新解析/复核:仅课程创建者或管理员"""
    _assert_material_manager(teacher, course_id, db)
    material = db.query(CourseMaterial).filter(
        CourseMaterial.id == material_id,
        CourseMaterial.course_id == course_id,
    ).first()
    if not material:
        raise HTTPException(status_code=404, detail="素材不存在")

    job = enqueue_parse(db, material)
    background_tasks.add_task(process_parse_job, job.id)
    return material_out(material, job)


@router.patch("/{course_id}/materials/{material_id}", response_model=MaterialOut)
def update_material(
    course_id: int,
    material_id: int,
    req: MaterialUpdate,
    teacher: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    """修改课件标题/类型:仅课程创建者或管理员"""
    _assert_material_manager(teacher, course_id, db)
    material = db.query(CourseMaterial).filter(
        CourseMaterial.id == material_id,
        CourseMaterial.course_id == course_id,
    ).first()
    if not material:
        raise HTTPException(status_code=404, detail="素材不存在")

    if req.type is not None:
        if req.type not in ("courseware", "syllabus", "exercise", "interview"):
            raise HTTPException(status_code=400, detail="素材类型不合法")
        material.type = req.type
    if req.title is not None:
        title = req.title.strip()
        if not title:
            raise HTTPException(status_code=400, detail="素材标题不能为空")
        material.title = title
    db.commit()
    db.refresh(material)

    job = db.query(MaterialParseJob).filter(
        MaterialParseJob.material_id == material.id,
    ).first()
    return material_out(material, job)


@router.delete("/{course_id}/materials/{material_id}")
def delete_material(
    course_id: int,
    material_id: int,
    teacher: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    """删除课件:仅课程创建者或管理员,同步清理文件并重建检索索引"""
    _assert_material_manager(teacher, course_id, db)
    material = db.query(CourseMaterial).filter(
        CourseMaterial.id == material_id,
        CourseMaterial.course_id == course_id,
    ).first()
    if not material:
        raise HTTPException(status_code=404, detail="素材不存在")

    try:
        if material.file_path and os.path.exists(material.file_path):
            os.remove(material.file_path)
    except Exception as exc:  # noqa: BLE001
        logger.warning("素材文件删除失败: %s", exc)

    db.delete(material)
    db.commit()
    try:
        from app.agent.tools.rag_search import rebuild_course_index

        rebuild_course_index(db, course_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("课程索引重建失败 course=%s: %s", course_id, exc)
    logger.info("素材删除: id=%s (course=%s, by=%s)", material_id, course_id, teacher.id)
    return {"id": material_id, "deleted": True}


# 需要借助 LibreOffice 转 PDF 才能高保真预览的格式
OFFICE_EXTS = {
    ".doc", ".docx", ".xls", ".xlsx", ".xlsm", ".ppt", ".pptx",
    ".odt", ".ods", ".odp", ".rtf",
}
_PREVIEW_LOCK = threading.Lock()


def _visible_material(
    db: Session, course_id: int, material_id: int, user: User,
) -> CourseMaterial:
    """读取课程可见素材;学生不能看到审核未通过的素材"""
    assert_course_visible(user, course_id, db)
    material = db.query(CourseMaterial).filter(
        CourseMaterial.id == material_id,
        CourseMaterial.course_id == course_id,
    ).first()
    if not material:
        raise HTTPException(status_code=404, detail="素材不存在")
    if (
        user.role not in ("teacher", "admin")
        and material.moderation_status == "rejected"
    ):
        raise HTTPException(status_code=403, detail="素材未通过内容审核")
    return material


def _office_pdf(source: Path, material_id: int) -> Optional[Path]:
    """用 LibreOffice 把 Office 文档转成 PDF,按文件指纹缓存;失败返回 None"""
    try:
        stat = source.stat()
    except OSError:
        return None
    if stat.st_size > 100 * 1024 * 1024:
        return None

    cache_dir = Path(tempfile.gettempdir()) / "itea_material_previews"
    cache_dir.mkdir(parents=True, exist_ok=True)
    target = cache_dir / f"material-{material_id}-{int(stat.st_mtime)}-{stat.st_size}.pdf"
    if target.is_file() and target.stat().st_size > 0:
        return target

    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        return None

    with _PREVIEW_LOCK:
        # 等锁期间可能已有同文件的转换结果
        if target.is_file() and target.stat().st_size > 0:
            return target
        with tempfile.TemporaryDirectory(prefix="itea-lo-") as tmp:
            env = os.environ.copy()
            env["HOME"] = tmp
            try:
                subprocess.run(
                    [
                        soffice, "--headless", "--norestore", "--nolockcheck",
                        "--nodefault", "--convert-to", "pdf", "--outdir", tmp,
                        str(source),
                    ],
                    check=False,
                    timeout=180,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    env=env,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                logger.warning("LibreOffice 转换失败(%s): %s", source.name, exc)
                return None
            produced = Path(tmp) / f"{source.stem}.pdf"
            if not produced.is_file() or produced.stat().st_size == 0:
                return None
            shutil.copyfile(produced, target)
    return target


@router.get("/{course_id}/materials/{material_id}/preview")
def preview_material(
    course_id: int,
    material_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    render: Optional[str] = Query(None),
):
    """素材原文预览:PDF/图片直接返回;Office 文档可用 render=pdf 转成 PDF 预览"""
    material = _visible_material(db, course_id, material_id, user)
    path = Path(material.file_path)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="素材文件缺失，请重新上传")

    if render == "pdf" and path.suffix.lower() in OFFICE_EXTS:
        pdf = _office_pdf(path, material.id)
        if not pdf:
            raise HTTPException(
                status_code=503,
                detail="该文件暂时无法转换为在线预览，请下载后用 Office/WPS 打开",
            )
        return FileResponse(
            pdf,
            media_type="application/pdf",
            filename=f"{path.stem}.pdf",
            content_disposition_type="inline",
        )
    if render == "pdf" and path.suffix.lower() != ".pdf":
        raise HTTPException(status_code=415, detail="该文件不支持 PDF 预览")

    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return FileResponse(
        path,
        media_type=media_type,
        filename=path.name,
        content_disposition_type="inline",
    )


@router.get("/{course_id}/materials/{material_id}/download")
def download_material(
    course_id: int,
    material_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """素材下载:学生与教师均可下载课程可见素材"""
    material = _visible_material(db, course_id, material_id, user)
    path = Path(material.file_path)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="素材文件缺失，请重新上传")
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return FileResponse(
        path,
        media_type=media_type,
        filename=path.name,
        content_disposition_type="attachment",
    )


@router.get("/{course_id}/materials/{material_id}/text")
def material_text(
    course_id: int,
    material_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """素材解析文本:Office 等浏览器无法直接渲染的文件用它做文字预览"""
    material = _visible_material(db, course_id, material_id, user)
    job = db.query(MaterialParseJob).filter(
        MaterialParseJob.material_id == material.id,
    ).first()
    return {
        "material_id": material.id,
        "status": job.status if job else None,
        "text": (job.result_text if job else "") or "",
    }