"""班级路由:教师建班/邀请,学生凭码加入,课程可见性由班级驱动"""
import logging
import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.core.deps import get_current_user, require_teacher, require_student
from app.models.user import User
from app.models.course import Course
from app.models.classroom import (
    Classroom, ClassMember, CourseEnrollment, ClassAnnouncement,
)
from app.schemas.classroom import (
    ClassCreate, ClassUpdate, ClassOut, ClassMembersOut, ClassMemberOut,
    ClassInviteRequest, ClassMemberRoleUpdate, ClassSelfTitleUpdate,
    ClassTransferRequest, AnnouncementCreate, AnnouncementOut,
    JoinClassRequest, JoinClassOut, InviteResetOut,
)
from app.schemas.teacher import ClassStatsOut
from app.services.class_stats import build_class_stats
from app.services.class_import import parse_student_rows
from app.services.course_access import is_open_to_students
from app.services import class_roles
from app.services import privacy as privacy_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/classes", tags=["班级"])

CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


# ---------- 内部工具 ----------

def _gen_invite_code(db: Session) -> str:
    for _ in range(20):
        code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(8))
        if not db.query(Classroom).filter(Classroom.invite_code == code).first():
            return code
    raise HTTPException(status_code=500, detail="邀请码生成失败，请重试")


def _owned_class(db: Session, class_id: int, teacher: User) -> Classroom:
    """仅班主任/管理员可管理班级设置"""
    classroom = db.query(Classroom).filter(Classroom.id == class_id).first()
    if not classroom:
        raise HTTPException(status_code=404, detail="班级不存在")
    if teacher.role != "admin" and classroom.teacher_id != teacher.id:
        raise HTTPException(status_code=403, detail="只能管理自己创建的班级")
    return classroom


def _class_for_teacher(db: Session, class_id: int, teacher: User) -> Classroom:
    """班主任、管理员或本班任课教师可访问"""
    classroom = db.query(Classroom).filter(Classroom.id == class_id).first()
    if not classroom:
        raise HTTPException(status_code=404, detail="班级不存在")
    if teacher.role == "admin" or classroom.teacher_id == teacher.id:
        return classroom
    member = class_roles.active_member(db, classroom.id, teacher.id)
    if member and member.role == "teacher":
        return classroom
    raise HTTPException(status_code=403, detail="你不是该班级成员")


def _class_for_member(db: Session, class_id: int, user: User) -> Classroom:
    """班主任、管理员、任课教师或班级学生成员均可访问"""
    classroom = db.query(Classroom).filter(Classroom.id == class_id).first()
    if not classroom:
        raise HTTPException(status_code=404, detail="班级不存在")
    if user.role == "admin" or classroom.teacher_id == user.id:
        return classroom
    if class_roles.active_member(db, classroom.id, user.id):
        return classroom
    raise HTTPException(status_code=403, detail="你不是该班级成员")


def _class_out(db: Session, classroom: Classroom, viewer: User | None = None) -> ClassOut:
    course = db.query(Course).filter(Course.id == classroom.course_id).first() \
        if classroom.course_id else None
    teacher = db.query(User).filter(User.id == classroom.teacher_id).first()
    member_count = _active_student_count(db, classroom.id)
    return ClassOut(
        id=classroom.id,
        teacher_id=classroom.teacher_id,
        teacher_name=teacher.name if teacher else None,
        course_id=classroom.course_id,
        course_name=course.name if course else None,
        name=classroom.name,
        semester=classroom.semester,
        description=classroom.description,
        status=classroom.status,
        invite_code=classroom.invite_code,
        invite_expires_at=classroom.invite_expires_at,
        invite_max_uses=classroom.invite_max_uses,
        invite_used=classroom.invite_used,
        member_count=member_count,
        max_students=classroom.max_students,
        my_role=class_roles.my_role(db, classroom, viewer) if viewer else None,
        created_at=classroom.created_at,
    )


def _active_student_count(db: Session, class_id: int) -> int:
    return db.query(ClassMember).filter(
        ClassMember.class_id == class_id,
        ClassMember.status == "active",
        ClassMember.role.in_(class_roles.STUDENT_ROLES),
    ).count()


def _ensure_capacity(db: Session, classroom: Classroom) -> None:
    if _active_student_count(db, classroom.id) >= (classroom.max_students or 100):
        raise HTTPException(status_code=400, detail="班级人数已达上限")


def _grant_course(db: Session, student_id: int, classroom: Classroom) -> None:
    """加入班级时授予班级课程的选课关系(幂等);未过审课程不授予"""
    if not classroom.course_id:
        return
    course = db.query(Course).filter(Course.id == classroom.course_id).first()
    if not course or not is_open_to_students(course):
        return
    existing = db.query(CourseEnrollment).filter(
        CourseEnrollment.course_id == classroom.course_id,
        CourseEnrollment.student_id == student_id,
    ).first()
    if existing:
        return
    db.add(CourseEnrollment(
        course_id=classroom.course_id,
        student_id=student_id,
        source="class",
        class_id=classroom.id,
    ))


def _revoke_course_if_alone(db: Session, student_id: int, classroom: Classroom) -> None:
    """退出班级时回收课程可见性:若该生仍在其他同课程班级则不回收"""
    if not classroom.course_id:
        return
    others = (
        db.query(ClassMember)
        .join(Classroom, ClassMember.class_id == Classroom.id)
        .filter(
            ClassMember.student_id == student_id,
            ClassMember.status == "active",
            Classroom.course_id == classroom.course_id,
            Classroom.id != classroom.id,
        )
        .first()
    )
    if others:
        return
    enrollment = db.query(CourseEnrollment).filter(
        CourseEnrollment.course_id == classroom.course_id,
        CourseEnrollment.student_id == student_id,
    ).first()
    # 仅回收"班级来源"的关系,自助/分享/历史迁移保留
    if enrollment and enrollment.source == "class":
        db.delete(enrollment)


def _join_member(
    db: Session,
    classroom: Classroom,
    member_user: User,
    *,
    role: str = "student",
    title: str | None = None,
    permissions: list[str] | None = None,
    invited_by: int | None = None,
) -> bool:
    """把用户加入班级;返回是否为新加入/重新激活"""
    member = db.query(ClassMember).filter(
        ClassMember.class_id == classroom.id,
        ClassMember.student_id == member_user.id,
    ).first()
    is_new = False
    if member is None:
        if role in class_roles.STUDENT_ROLES:
            _ensure_capacity(db, classroom)
        member = ClassMember(
            class_id=classroom.id,
            student_id=member_user.id,
            role=role,
            title=title,
            permissions=class_roles.dump_permissions(permissions),
            invited_by=invited_by,
            status="active",
        )
        db.add(member)
        is_new = True
    else:
        if member.status == "active":
            # 已在班:邀请幂等,不隐式改角色/头衔(改角色走专用接口)
            return False
        if role in class_roles.STUDENT_ROLES:
            _ensure_capacity(db, classroom)
        member.status = "active"
        member.role = role
        member.title = title
        member.permissions = class_roles.dump_permissions(permissions)
        member.invited_by = invited_by
        is_new = True
    if is_new and role in class_roles.STUDENT_ROLES:
        _grant_course(db, member_user.id, classroom)
    return is_new


# ---------- 教师端 ----------

@router.get("", response_model=list[ClassOut])
def list_classes(
    teacher: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    """教师:自己创建或任课的班级;管理员:全部"""
    query = db.query(Classroom)
    if teacher.role != "admin":
        member_class_ids = db.query(ClassMember.class_id).filter(
            ClassMember.student_id == teacher.id,
            ClassMember.role == "teacher",
            ClassMember.status == "active",
        )
        query = query.filter(or_(
            Classroom.teacher_id == teacher.id,
            Classroom.id.in_(member_class_ids),
        ))
    rows = query.order_by(Classroom.id.desc()).all()
    return [_class_out(db, c, teacher) for c in rows]


@router.post("", response_model=ClassOut)
def create_class(
    req: ClassCreate,
    teacher: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    """创建班级;绑定课程后,成员会自动获得该课程可见性"""
    if req.course_id:
        course = db.query(Course).filter(Course.id == req.course_id).first()
        if not course:
            raise HTTPException(status_code=404, detail="课程不存在")
        if teacher.role != "admin" and course.teacher_id != teacher.id:
            raise HTTPException(status_code=403, detail="只能绑定自己的课程")

    classroom = Classroom(
        teacher_id=teacher.id,
        course_id=req.course_id,
        name=req.name,
        semester=req.semester,
        description=req.description,
        invite_code=_gen_invite_code(db),
        invite_expires_at=datetime.utcnow() + timedelta(days=req.invite_days),
        invite_max_uses=req.invite_max_uses,
        invite_used=0,
        max_students=req.max_students,
        status="active",
    )
    db.add(classroom)
    db.commit()
    db.refresh(classroom)
    logger.info("班级创建: %s (teacher=%s)", classroom.name, teacher.id)
    return _class_out(db, classroom, teacher)


@router.get("/permissions")
def permission_catalog(teacher: User = Depends(require_teacher)):
    """班级角色与可配置权限清单"""
    return {
        "permissions": [
            {"key": key, "label": label}
            for key, label in class_roles.PERMISSION_CATALOG.items()
        ],
        "roles": class_roles.ROLE_LABELS,
        "teacher_permissions": sorted(class_roles.TEACHER_PERMISSIONS),
    }


@router.get("/{class_id}", response_model=ClassOut)
def get_class(
    class_id: int,
    teacher: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    return _class_out(db, _class_for_teacher(db, class_id, teacher), teacher)


@router.get("/{class_id}/report", response_model=ClassStatsOut)
def get_class_report(
    class_id: int,
    teacher: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    """班级维度学情与作业/考试统计(班主任与任课教师均可查看)"""
    return build_class_stats(db, _class_for_teacher(db, class_id, teacher))


@router.put("/{class_id}", response_model=ClassOut)
def update_class(
    class_id: int,
    req: ClassUpdate,
    teacher: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    classroom = _owned_class(db, class_id, teacher)
    if req.course_id is not None and req.course_id != classroom.course_id:
        course = db.query(Course).filter(Course.id == req.course_id).first()
        if not course:
            raise HTTPException(status_code=404, detail="课程不存在")
        if teacher.role != "admin" and course.teacher_id != teacher.id:
            raise HTTPException(status_code=403, detail="只能绑定自己的课程")
        classroom.course_id = req.course_id
        # 绑定新课程后,为现有成员补授可见性(旧课程关系不自动回收)
        members = db.query(ClassMember).filter(
            ClassMember.class_id == classroom.id,
            ClassMember.status == "active",
        ).all()
        for m in members:
            if m.role in class_roles.STUDENT_ROLES:
                _grant_course(db, m.student_id, classroom)
    if req.max_students is not None:
        current = _active_student_count(db, classroom.id)
        if req.max_students < current:
            raise HTTPException(
                status_code=400,
                detail=f"容量不能小于当前学生数({current})",
            )
        classroom.max_students = req.max_students
    for field in ("name", "semester", "description", "status"):
        value = getattr(req, field)
        if value is not None:
            setattr(classroom, field, value)
    db.commit()
    db.refresh(classroom)
    return _class_out(db, classroom, teacher)


@router.delete("/{class_id}")
def archive_class(
    class_id: int,
    teacher: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    """归档班级(不删除成员与学情数据)"""
    classroom = _owned_class(db, class_id, teacher)
    classroom.status = "archived"
    db.commit()
    return {"id": classroom.id, "status": classroom.status}


@router.post("/{class_id}/invite/reset", response_model=InviteResetOut)
def reset_invite(
    class_id: int,
    days: int = 7,
    max_uses: int = 50,
    teacher: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    """重置邀请码:旧码立即失效"""
    classroom = _owned_class(db, class_id, teacher)
    classroom.invite_code = _gen_invite_code(db)
    classroom.invite_used = 0
    classroom.invite_max_uses = max(1, min(max_uses, 1000))
    classroom.invite_expires_at = datetime.utcnow() + timedelta(days=max(1, min(days, 365)))
    db.commit()
    db.refresh(classroom)
    return InviteResetOut(
        invite_code=classroom.invite_code,
        invite_expires_at=classroom.invite_expires_at,
        invite_max_uses=classroom.invite_max_uses,
    )


def _member_out(member: ClassMember, user: User, prefs) -> ClassMemberOut:
    return ClassMemberOut(
        student_id=user.id,
        name=privacy_service.name_of(user, prefs.get(user.id), "teacher"),
        email=privacy_service.email_of(user, prefs.get(user.id), "teacher"),
        joined_at=member.joined_at,
        status=member.status,
        role=member.role,
        title=member.title,
        permissions=sorted(class_roles.parse_permissions(member.permissions)),
        member_type="teacher" if member.role == "teacher" else "student",
    )


@router.get("/{class_id}/members", response_model=ClassMembersOut)
def list_members(
    class_id: int,
    teacher: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    classroom = _class_for_teacher(db, class_id, teacher)
    rows = (
        db.query(ClassMember, User)
        .join(User, ClassMember.student_id == User.id)
        .filter(ClassMember.class_id == classroom.id)
        .order_by(ClassMember.joined_at.desc())
        .all()
    )
    prefs = privacy_service.get_map(db, [user.id for _, user in rows])
    items = [_member_out(member, user, prefs) for member, user in rows]
    return ClassMembersOut(total=len(items), items=items)


@router.post("/{class_id}/members", response_model=ClassMemberOut)
def invite_member(
    class_id: int,
    req: ClassInviteRequest,
    teacher: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    """邀请教师或学生进班;头衔与自定义权限按邀请人角色校验"""
    classroom = _class_for_teacher(db, class_id, teacher)
    if classroom.status != "active":
        raise HTTPException(status_code=400, detail="班级已归档，无法邀请")
    class_roles.require_permission(db, classroom, teacher, "member.invite")

    inviter_role = class_roles.my_role(db, classroom, teacher)
    if not class_roles.can_invite_role(inviter_role, req.role):
        raise HTTPException(status_code=403, detail="当前班级角色无权邀请该角色")
    if inviter_role == "teacher" and req.title and req.role != "representative":
        raise HTTPException(status_code=403, detail="任课教师只能授予课代表头衔")

    query = db.query(User)
    if req.role == "teacher":
        query = query.filter(User.role.in_(("teacher", "admin")))
    else:
        query = query.filter(User.role == "student")
    if req.student_id:
        target = query.filter(User.id == req.student_id).first()
    elif req.email:
        target = query.filter(User.email == req.email).first()
    else:
        raise HTTPException(status_code=400, detail="请提供用户 ID 或邮箱")
    if not target:
        raise HTTPException(status_code=404, detail="未找到该用户，请确认已注册")

    class_roles.ensure_role_matches_user(target, req.role)
    permissions = None
    if req.role == "custom":
        permissions = class_roles.validate_custom_permissions(req.permissions)
    title = req.title
    if req.role == "representative" and not title:
        title = "课代表"

    _join_member(
        db, classroom, target,
        role=req.role, title=title, permissions=permissions,
        invited_by=teacher.id,
    )
    db.commit()
    member = db.query(ClassMember).filter(
        ClassMember.class_id == classroom.id,
        ClassMember.student_id == target.id,
    ).first()
    prefs = privacy_service.get_map(db, [target.id])
    return _member_out(member, target, prefs)


@router.patch("/{class_id}/members/{user_id}/role", response_model=ClassMemberOut)
def assign_member_role(
    class_id: int,
    user_id: int,
    req: ClassMemberRoleUpdate,
    teacher: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    """班主任可赋予任意班级角色;任课教师仅可授予课代表"""
    classroom = _class_for_teacher(db, class_id, teacher)
    inviter_role = class_roles.my_role(db, classroom, teacher)
    if not class_roles.can_assign_role(inviter_role, req.role):
        raise HTTPException(status_code=403, detail="当前班级角色无权赋予该角色")

    member = class_roles.active_member(db, classroom.id, user_id)
    if not member:
        raise HTTPException(status_code=404, detail="该用户不在班级中")
    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="用户不存在")
    class_roles.ensure_role_matches_user(target, req.role)

    permissions = None
    if req.role == "custom":
        permissions = class_roles.validate_custom_permissions(req.permissions)
    title = req.title
    if req.role == "representative" and not title:
        title = "课代表"

    old_role = member.role
    member.role = req.role
    member.title = title
    member.permissions = class_roles.dump_permissions(permissions)

    # 学生角色 ↔ 任课教师切换时同步课程可见性
    if old_role in class_roles.STUDENT_ROLES and req.role == "teacher":
        _revoke_course_if_alone(db, user_id, classroom)
    elif old_role == "teacher" and req.role in class_roles.STUDENT_ROLES:
        _grant_course(db, user_id, classroom)

    db.commit()
    db.refresh(member)
    prefs = privacy_service.get_map(db, [target.id])
    return _member_out(member, target, prefs)


@router.patch("/{class_id}/me/title", response_model=ClassMemberOut)
def set_my_title(
    class_id: int,
    req: ClassSelfTitleUpdate,
    teacher: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    """任课教师设置自己在本班的头衔(如“数据结构教师”)"""
    classroom = _class_for_teacher(db, class_id, teacher)
    member = class_roles.active_member(db, classroom.id, teacher.id)
    if not member or member.role != "teacher":
        raise HTTPException(status_code=400, detail="仅任课教师可设置自己的头衔")
    member.title = req.title
    db.commit()
    db.refresh(member)
    prefs = privacy_service.get_map(db, [teacher.id])
    return _member_out(member, teacher, prefs)


@router.delete("/{class_id}/members/{student_id}")
def remove_member(
    class_id: int,
    student_id: int,
    teacher: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    classroom = _owned_class(db, class_id, teacher)
    member = db.query(ClassMember).filter(
        ClassMember.class_id == classroom.id,
        ClassMember.student_id == student_id,
    ).first()
    if not member:
        raise HTTPException(status_code=404, detail="该用户不在班级中")
    member.status = "left"
    if member.role in class_roles.STUDENT_ROLES:
        _revoke_course_if_alone(db, student_id, classroom)
    db.commit()
    return {"class_id": classroom.id, "student_id": student_id, "status": "left"}


@router.post("/{class_id}/members/import")
async def import_members(
    class_id: int,
    file: UploadFile = File(...),
    teacher: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    """批量导入学生(CSV/XLSX):列名支持 email/邮箱、student_id/id/学号"""
    classroom = _owned_class(db, class_id, teacher)
    if classroom.status != "active":
        raise HTTPException(status_code=400, detail="班级已归档，无法导入")
    try:
        content = await file.read()
        rows = parse_student_rows(content, file.filename or "")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    imported = skipped = failed = 0
    items = []
    for row in rows:
        email = (row.get("email") or "").strip().lower()
        raw_id = (row.get("student_id") or "").strip()
        student = None
        if raw_id.isdigit():
            student = db.query(User).filter(
                User.id == int(raw_id), User.role == "student").first()
        if not student and email:
            student = db.query(User).filter(
                User.email == email, User.role == "student").first()

        if not student:
            failed += 1
            items.append({**row, "status": "failed", "message": "未找到该学生"})
            continue
        existing = class_roles.active_member(db, classroom.id, student.id)
        if existing:
            skipped += 1
            items.append({**row, "status": "skipped", "message": "已在班级中"})
            continue
        try:
            _join_member(
                db, classroom, student, role="student",
                invited_by=teacher.id,
            )
            imported += 1
            items.append({**row, "status": "imported", "message": "已加入"})
        except HTTPException as exc:
            failed += 1
            items.append({**row, "status": "failed", "message": str(exc.detail)})

    db.commit()
    return {
        "class_id": classroom.id,
        "total": len(rows),
        "imported": imported,
        "skipped": skipped,
        "failed": failed,
        "max_students": classroom.max_students,
        "items": items,
    }


@router.post("/{class_id}/members/{student_id}/transfer")
def transfer_member(
    class_id: int,
    student_id: int,
    req: ClassTransferRequest,
    teacher: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    """把本班学生转到另一班级(班主任/管理员)"""
    source = _owned_class(db, class_id, teacher)
    if req.target_class_id == source.id:
        raise HTTPException(status_code=400, detail="目标班级不能是当前班级")
    target = db.query(Classroom).filter(Classroom.id == req.target_class_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="目标班级不存在")
    if teacher.role != "admin" and target.teacher_id != teacher.id:
        raise HTTPException(status_code=403, detail="只能转到自己创建的班级")
    if target.status != "active":
        raise HTTPException(status_code=400, detail="目标班级已归档")

    member = class_roles.active_member(db, source.id, student_id)
    if not member or member.role not in class_roles.STUDENT_ROLES:
        raise HTTPException(status_code=404, detail="该学生不在当前班级中")
    if class_roles.active_member(db, target.id, student_id):
        raise HTTPException(status_code=400, detail="该学生已在目标班级中")

    student = db.query(User).filter(User.id == student_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="学生不存在")

    # 先加入目标班(容量不足会直接失败,源班状态不变)
    _join_member(
        db, target, student,
        role=member.role,
        title=member.title,
        permissions=class_roles.parse_permissions(member.permissions),
        invited_by=teacher.id,
    )
    member.status = "left"
    _revoke_course_if_alone(db, student_id, source)
    db.commit()
    return {
        "student_id": student_id,
        "from_class_id": source.id,
        "to_class_id": target.id,
        "status": "transferred",
    }


@router.get("/{class_id}/announcements", response_model=list[AnnouncementOut])
def list_announcements(
    class_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """班级成员(班主任/任课教师/学生)均可查看本班公告"""
    classroom = _class_for_member(db, class_id, user)
    rows = (
        db.query(ClassAnnouncement, User)
        .join(User, ClassAnnouncement.author_id == User.id)
        .filter(ClassAnnouncement.class_id == classroom.id)
        .order_by(ClassAnnouncement.id.desc())
        .limit(50)
        .all()
    )
    return [
        AnnouncementOut(
            id=ann.id, class_id=ann.class_id, author_id=ann.author_id,
            author_name=author.name, content=ann.content, created_at=ann.created_at,
        )
        for ann, author in rows
    ]


@router.post("/{class_id}/announcements", response_model=AnnouncementOut)
def create_announcement(
    class_id: int,
    req: AnnouncementCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """发布公告:班主任或拥有 notice.post 权限的自定义角色"""
    classroom = _class_for_member(db, class_id, user)
    class_roles.require_permission(db, classroom, user, "notice.post")
    content = req.content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="公告内容不能为空")
    announcement = ClassAnnouncement(
        class_id=classroom.id, author_id=user.id, content=content,
    )
    db.add(announcement)
    db.commit()
    db.refresh(announcement)
    return AnnouncementOut(
        id=announcement.id, class_id=announcement.class_id,
        author_id=announcement.author_id, author_name=user.name,
        content=announcement.content, created_at=announcement.created_at,
    )


# ---------- 学生端 ----------

@router.get("/student/mine", response_model=list[ClassOut])
def my_classes(
    student: User = Depends(require_student),
    db: Session = Depends(get_db),
):
    """我加入的班级"""
    rows = (
        db.query(Classroom)
        .join(ClassMember, ClassMember.class_id == Classroom.id)
        .filter(ClassMember.student_id == student.id, ClassMember.status == "active")
        .order_by(Classroom.id.desc())
        .all()
    )
    return [_class_out(db, c, student) for c in rows]


@router.post("/student/join", response_model=JoinClassOut)
def join_class(
    req: JoinClassRequest,
    student: User = Depends(require_student),
    db: Session = Depends(get_db),
):
    """凭邀请码加入班级,自动获得班级课程可见性"""
    classroom = db.query(Classroom).filter(
        Classroom.invite_code == req.invite_code.strip().upper()
    ).first()
    if not classroom:
        raise HTTPException(status_code=404, detail="邀请码无效")

    # 已在班级中的成员重复提交视为幂等成功,不受次数/有效期影响
    existing = db.query(ClassMember).filter(
        ClassMember.class_id == classroom.id,
        ClassMember.student_id == student.id,
        ClassMember.status == "active",
    ).first()
    if existing:
        return JoinClassOut(
            class_id=classroom.id, class_name=classroom.name,
            course_id=classroom.course_id, joined=True,
        )

    if classroom.status != "active":
        raise HTTPException(status_code=400, detail="班级已归档")
    if classroom.invite_expires_at and classroom.invite_expires_at < datetime.utcnow():
        raise HTTPException(status_code=400, detail="邀请码已过期")
    if classroom.invite_used >= classroom.invite_max_uses:
        raise HTTPException(status_code=400, detail="邀请码使用次数已用尽")

    if classroom.course_id:
        course = db.query(Course).filter(Course.id == classroom.course_id).first()
        if not course:
            raise HTTPException(status_code=404, detail="课程不存在")
        if not is_open_to_students(course):
            raise HTTPException(status_code=403, detail="课程未通过平台审核，暂不可加入")

    is_new = _join_member(db, classroom, student)
    if is_new:
        classroom.invite_used += 1
    db.commit()
    return JoinClassOut(
        class_id=classroom.id, class_name=classroom.name,
        course_id=classroom.course_id, joined=True,
    )


@router.post("/{class_id}/leave")
def leave_class(
    class_id: int,
    student: User = Depends(require_student),
    db: Session = Depends(get_db),
):
    classroom = db.query(Classroom).filter(Classroom.id == class_id).first()
    if not classroom:
        raise HTTPException(status_code=404, detail="班级不存在")
    member = db.query(ClassMember).filter(
        ClassMember.class_id == class_id,
        ClassMember.student_id == student.id,
    ).first()
    if not member or member.status != "active":
        raise HTTPException(status_code=400, detail="你不在该班级中")
    member.status = "left"
    _revoke_course_if_alone(db, student.id, classroom)
    db.commit()
    return {"class_id": class_id, "status": "left"}
