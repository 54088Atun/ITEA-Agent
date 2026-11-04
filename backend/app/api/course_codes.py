"""统一课程码:一个入口按角色分流

口径(CL-07):
- 班级课程码:学生用 → 加入班级;教师用 → 复制该班绑定课程(需已绑定且已审核)
- 教师课程码(原分享码):仅教师可用 → 复制课程快照
- 所有使用写 code_redemptions 审计;过期/撤销/超次由底层接口统一拦截
"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.classroom import join_class
from app.api.course_share import import_course
from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.classroom import Classroom, CodeRedemption, CourseShare
from app.models.course import Course
from app.models.user import User
from app.schemas.assignment import CourseImportRequest
from app.schemas.classroom import CourseCodeRedeemRequest, JoinClassRequest
from app.services.course_access import is_open_to_students
from app.services.course_copy import copy_course_structure

router = APIRouter(prefix="/codes", tags=["课程码"])


def _norm(code: str) -> str:
    return (code or "").strip().upper()


def _find(db: Session, code: str):
    classroom = db.query(Classroom).filter(Classroom.invite_code == code).first()
    if classroom:
        return "class", classroom
    share = db.query(CourseShare).filter(CourseShare.code == code).first()
    if share:
        return "course", share
    return None, None


def _remaining(used: int, maximum: int) -> int:
    return max(0, (maximum or 0) - (used or 0))


def _preview(db: Session, code: str) -> dict:
    scope, target = _find(db, code)
    if not scope:
        raise HTTPException(status_code=404, detail="课程码无效")

    if scope == "class":
        course = db.query(Course).filter(Course.id == target.course_id).first() \
            if target.course_id else None
        owner = db.query(User).filter(User.id == target.teacher_id).first()
        expired = bool(target.invite_expires_at and target.invite_expires_at < datetime.utcnow())
        used_up = target.invite_used >= target.invite_max_uses
        available = target.status == "active" and not expired and not used_up
        return {
            "code": code,
            "scope": "class",
            "name": target.name,
            "class_id": target.id,
            "course_id": target.course_id,
            "course_name": course.name if course else None,
            "owner_id": target.teacher_id,
            "owner_name": owner.name if owner else None,
            "expires_at": target.invite_expires_at,
            "remaining_uses": _remaining(target.invite_used, target.invite_max_uses),
            "available": available,
            "usable_for": ["teacher", "student"] if target.course_id else ["student"],
            "reason": None if available else (
                "班级已归档" if target.status != "active"
                else "课程码已过期" if expired else "使用次数已用尽"
            ),
        }

    course = db.query(Course).filter(Course.id == target.course_id).first()
    owner = db.query(User).filter(User.id == target.owner_id).first()
    expired = bool(target.expires_at and target.expires_at < datetime.utcnow())
    used_up = target.used_count >= target.max_uses
    revoked = bool(target.revoked_at)
    available = not revoked and not expired and not used_up
    return {
        "code": code,
        "scope": "course",
        "name": course.name if course else "课程已删除",
        "class_id": None,
        "course_id": target.course_id,
        "course_name": course.name if course else None,
        "owner_id": target.owner_id,
        "owner_name": owner.name if owner else None,
        "expires_at": target.expires_at,
        "remaining_uses": _remaining(target.used_count, target.max_uses),
        "available": available,
        "usable_for": ["teacher"],
        "reason": None if available else (
            "课程码已撤销" if revoked else "课程码已过期" if expired else "使用次数已用尽"
        ),
    }


@router.get("/{code}")
def preview_code(
    code: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """预览课程码用途与剩余次数(不消耗次数)"""
    data = _preview(db, _norm(code))
    data["role"] = user.role
    data["can_redeem"] = data["available"] and (
        (user.role in ("teacher", "admin") and "teacher" in data["usable_for"])
        or (user.role == "student" and "student" in data["usable_for"])
    )
    return data


@router.post("/redeem")
def redeem_code(
    body: CourseCodeRedeemRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """按当前用户角色使用课程码:教师复制课程,学生加入班级"""
    code = _norm(body.code)
    if not code:
        raise HTTPException(status_code=400, detail="请输入课程码")
    scope, target = _find(db, code)
    if not scope:
        raise HTTPException(status_code=404, detail="课程码无效")

    if user.role in ("teacher", "admin"):
        if scope == "course":
            result = import_course(CourseImportRequest(code=code), user, db)
            db.add(CodeRedemption(
                code=code, scope="course", user_id=user.id, role=user.role,
                action="course_copy", target_id=result["course_id"],
            ))
            db.commit()
            return {"scope": "course", "action": "course_copy", **result}

        # 班级课程码 → 复制该班绑定课程
        if not target.course_id:
            raise HTTPException(status_code=400, detail="该班级未绑定课程，教师无法复制")
        source = db.query(Course).filter(Course.id == target.course_id).first()
        if not source:
            raise HTTPException(status_code=400, detail="班级绑定课程不存在")
        if not is_open_to_students(source):
            raise HTTPException(status_code=403, detail="课程未通过平台审核，暂不可复制")
        if source.teacher_id == user.id and user.role != "admin":
            raise HTTPException(status_code=400, detail="不能复制自己的课程")
        new_course, stats = copy_course_structure(
            db, source, user.id, audit_status="approved",
        )
        db.add(CodeRedemption(
            code=code, scope="class", user_id=user.id, role=user.role,
            action="course_copy", target_id=new_course.id,
        ))
        db.commit()
        db.refresh(new_course)
        return {
            "scope": "class", "action": "course_copy",
            "course_id": new_course.id, "name": new_course.name,
            "code": new_course.code, "source_course_id": source.id,
            "class_id": target.id,
            "knowledge_points": stats["knowledge_points"],
            "materials": stats["materials"],
        }

    if user.role == "student":
        if scope == "course":
            raise HTTPException(status_code=403, detail="该课程码仅教师可用，请向老师索取班级课程码")
        result = join_class(JoinClassRequest(invite_code=code), user, db)
        db.add(CodeRedemption(
            code=code, scope="class", user_id=user.id, role=user.role,
            action="class_join", target_id=target.id,
        ))
        db.commit()
        return {"scope": "class", "action": "class_join", **result.model_dump()}

    raise HTTPException(status_code=403, detail="当前角色不能使用课程码")
