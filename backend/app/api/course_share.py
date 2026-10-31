"""课程分享码:教师之间限时/限次分享,凭码复制为快照副本

约束:
- 仅教师/管理员可生成与使用;只能分享自己的课程
- 复制为新课程,归属复制者;复制课程、知识点树、素材元数据
- 不复制学生学情、选课关系、作业与提交,原课程学生数据不外泄
- 过期/撤销/超次立即失效;生成、撤销、复制均写操作审计
"""
import json
import logging
import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.deps import require_teacher
from app.db.session import get_db
from app.models.classroom import CourseShare
from app.models.course import Course, CourseMaterial, KnowledgePoint
from app.models.log import OperationLog
from app.models.user import User
from app.schemas.assignment import CourseImportRequest, CourseShareCreate
from app.services.feature_flags import is_enabled

logger = logging.getLogger(__name__)
router = APIRouter(tags=["课程分享"])

CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def _require_teacher_role(user: User) -> None:
    if user.role not in ("teacher", "admin"):
        raise HTTPException(status_code=403, detail="仅教师可使用课程分享")


def _owned_course(db: Session, course_id: int, teacher: User) -> Course:
    course = db.query(Course).filter(Course.id == course_id).first()
    if not course:
        raise HTTPException(status_code=404, detail="课程不存在")
    if teacher.role != "admin" and course.teacher_id != teacher.id:
        raise HTTPException(status_code=403, detail="只能分享自己的课程")
    return course


def _owned_share(db: Session, share_id: int, teacher: User) -> CourseShare:
    share = db.query(CourseShare).filter(CourseShare.id == share_id).first()
    if not share:
        raise HTTPException(status_code=404, detail="分享记录不存在")
    if teacher.role != "admin" and share.owner_id != teacher.id:
        raise HTTPException(status_code=403, detail="只能撤销自己生成的分享码")
    return share


def _gen_code(db: Session) -> str:
    for _ in range(20):
        code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(8))
        if not db.query(CourseShare).filter(CourseShare.code == code).first():
            return code
    raise HTTPException(status_code=500, detail="分享码生成失败，请重试")


def _share_status(share: CourseShare) -> str:
    if share.revoked_at:
        return "revoked"
    if share.expires_at and share.expires_at < datetime.utcnow():
        return "expired"
    if share.used_count >= share.max_uses:
        return "exhausted"
    return "active"


def _log(db: Session, actor: User, action: str, target_id: int, detail: dict) -> None:
    db.add(OperationLog(
        admin_id=actor.id,
        action=action,
        target_type="course",
        target_id=target_id,
        detail=json.dumps(detail, ensure_ascii=False),
    ))


def _unique_course_code(db: Session, source_code: str) -> str:
    base = (source_code or "COPY")[:14]
    for i in range(1, 100):
        candidate = f"{base}-C{i}"
        if not db.query(Course).filter(Course.code == candidate).first():
            return candidate
    return f"COPY-{secrets.token_hex(4)}"[:20]


# ---------- 分享码管理 ----------

@router.post("/teacher/courses/{course_id}/shares")
def create_share(
    course_id: int,
    req: CourseShareCreate,
    teacher: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    """生成分享码:默认 7 天、1 次可用,可随时撤销"""
    _require_teacher_role(teacher)
    if not is_enabled(db, "feature_course_share"):
        raise HTTPException(status_code=403, detail="课程分享功能已关闭")
    course = _owned_course(db, course_id, teacher)

    share = CourseShare(
        course_id=course.id,
        owner_id=teacher.id,
        code=_gen_code(db),
        expires_at=datetime.utcnow() + timedelta(days=req.expires_days),
        max_uses=req.max_uses,
        used_count=0,
    )
    db.add(share)
    db.flush()
    _log(db, teacher, "share_create", course.id, {
        "share_id": share.id, "code": share.code,
        "expires_days": req.expires_days, "max_uses": req.max_uses,
    })
    db.commit()
    db.refresh(share)
    logger.info("课程分享码生成: course=%s share=%s", course.id, share.id)
    return {
        "id": share.id,
        "course_id": share.course_id,
        "code": share.code,
        "expires_at": share.expires_at,
        "max_uses": share.max_uses,
        "used_count": share.used_count,
        "status": _share_status(share),
    }


@router.get("/teacher/courses/{course_id}/shares")
def list_shares(
    course_id: int,
    teacher: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    _require_teacher_role(teacher)
    _owned_course(db, course_id, teacher)
    rows = (
        db.query(CourseShare)
        .filter(CourseShare.course_id == course_id)
        .order_by(CourseShare.id.desc())
        .limit(20)
        .all()
    )
    return [
        {
            "id": r.id,
            "code": r.code,
            "expires_at": r.expires_at,
            "max_uses": r.max_uses,
            "used_count": r.used_count,
            "revoked_at": r.revoked_at,
            "created_at": r.created_at,
            "status": _share_status(r),
        }
        for r in rows
    ]


@router.delete("/teacher/shares/{share_id}")
def revoke_share(
    share_id: int,
    teacher: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    _require_teacher_role(teacher)
    share = _owned_share(db, share_id, teacher)
    if not share.revoked_at:
        share.revoked_at = datetime.utcnow()
        _log(db, teacher, "share_revoke", share.course_id, {"share_id": share.id})
        db.commit()
    return {"id": share.id, "status": _share_status(share)}


# ---------- 凭码复制 ----------

@router.post("/teacher/courses/import")
def import_course(
    req: CourseImportRequest,
    teacher: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    """凭分享码复制课程快照:不含学生学情、选课关系、作业与提交"""
    _require_teacher_role(teacher)
    if not is_enabled(db, "feature_course_share"):
        raise HTTPException(status_code=403, detail="课程分享功能已关闭")
    code = req.code.strip().upper()
    share = db.query(CourseShare).filter(CourseShare.code == code).first()
    if not share:
        raise HTTPException(status_code=404, detail="分享码无效")
    if share.revoked_at:
        raise HTTPException(status_code=400, detail="分享码已撤销")
    if share.expires_at and share.expires_at < datetime.utcnow():
        raise HTTPException(status_code=400, detail="分享码已过期")
    if share.used_count >= share.max_uses:
        raise HTTPException(status_code=400, detail="分享码使用次数已用尽")

    source = db.query(Course).filter(Course.id == share.course_id).first()
    if not source:
        raise HTTPException(status_code=400, detail="源课程已不存在")
    if source.teacher_id == teacher.id and teacher.role != "admin":
        raise HTTPException(status_code=400, detail="不能复制自己的课程")

    new_course = Course(
        teacher_id=teacher.id,
        name=f"{source.name}（副本）"[:100],
        code=_unique_course_code(db, source.code),
        syllabus=source.syllabus,
        semester=source.semester,
        audit_status="approved",
    )
    db.add(new_course)
    db.flush()

    # 知识点树:两遍写入保留父子关系
    kps = (
        db.query(KnowledgePoint)
        .filter(KnowledgePoint.course_id == source.id)
        .order_by(KnowledgePoint.id.asc())
        .all()
    )
    id_map = {}
    for kp in kps:
        new_kp = KnowledgePoint(
            course_id=new_course.id,
            name=kp.name,
            description=kp.description,
            parent_id=None,
        )
        db.add(new_kp)
        db.flush()
        id_map[kp.id] = new_kp
    for kp in kps:
        if kp.parent_id and kp.parent_id in id_map:
            id_map[kp.id].parent_id = id_map[kp.parent_id].id

    # 素材元数据:复用原文件路径,分块数归零提示需重新入库
    materials = (
        db.query(CourseMaterial)
        .filter(CourseMaterial.course_id == source.id)
        .all()
    )
    for m in materials:
        db.add(CourseMaterial(
            course_id=new_course.id,
            type=m.type,
            title=m.title,
            file_path=m.file_path,
            chunk_count=0,
        ))

    share.used_count += 1
    _log(db, teacher, "course_import", new_course.id, {
        "source_course_id": source.id,
        "share_id": share.id,
        "knowledge_points": len(kps),
        "materials": len(materials),
    })
    db.commit()
    db.refresh(new_course)
    logger.info(
        "课程复制: source=%s -> new=%s (teacher=%s)",
        source.id, new_course.id, teacher.id,
    )
    return {
        "course_id": new_course.id,
        "name": new_course.name,
        "code": new_course.code,
        "source_course_id": source.id,
        "knowledge_points": len(kps),
        "materials": len(materials),
    }
