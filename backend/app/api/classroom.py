"""班级路由:教师建班/邀请,学生凭码加入,课程可见性由班级驱动"""
import logging
import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.core.deps import get_current_user, require_teacher, require_student
from app.models.user import User
from app.models.course import Course
from app.models.classroom import Classroom, ClassMember, CourseEnrollment
from app.schemas.classroom import (
    ClassCreate, ClassUpdate, ClassOut, ClassMembersOut, ClassMemberOut,
    ClassInviteRequest, JoinClassRequest, JoinClassOut, InviteResetOut,
)

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
    classroom = db.query(Classroom).filter(Classroom.id == class_id).first()
    if not classroom:
        raise HTTPException(status_code=404, detail="班级不存在")
    if teacher.role != "admin" and classroom.teacher_id != teacher.id:
        raise HTTPException(status_code=403, detail="只能管理自己创建的班级")
    return classroom


def _class_out(db: Session, classroom: Classroom) -> ClassOut:
    course = db.query(Course).filter(Course.id == classroom.course_id).first() \
        if classroom.course_id else None
    teacher = db.query(User).filter(User.id == classroom.teacher_id).first()
    member_count = db.query(ClassMember).filter(
        ClassMember.class_id == classroom.id,
        ClassMember.status == "active",
    ).count()
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
        created_at=classroom.created_at,
    )


def _grant_course(db: Session, student_id: int, classroom: Classroom) -> None:
    """加入班级时授予班级课程的选课关系(幂等)"""
    if not classroom.course_id:
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


def _join_member(db: Session, classroom: Classroom, student: User) -> bool:
    """把学生加入班级;返回是否为新加入"""
    member = db.query(ClassMember).filter(
        ClassMember.class_id == classroom.id,
        ClassMember.student_id == student.id,
    ).first()
    is_new = False
    if member is None:
        db.add(ClassMember(class_id=classroom.id, student_id=student.id, status="active"))
        is_new = True
    elif member.status != "active":
        member.status = "active"
        is_new = True
    if is_new:
        _grant_course(db, student.id, classroom)
    return is_new


# ---------- 教师端 ----------

@router.get("", response_model=list[ClassOut])
def list_classes(
    teacher: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    """教师:自己创建的班级;管理员:全部"""
    query = db.query(Classroom)
    if teacher.role != "admin":
        query = query.filter(Classroom.teacher_id == teacher.id)
    rows = query.order_by(Classroom.id.desc()).all()
    return [_class_out(db, c) for c in rows]


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
        status="active",
    )
    db.add(classroom)
    db.commit()
    db.refresh(classroom)
    logger.info("班级创建: %s (teacher=%s)", classroom.name, teacher.id)
    return _class_out(db, classroom)


@router.get("/{class_id}", response_model=ClassOut)
def get_class(
    class_id: int,
    teacher: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    return _class_out(db, _owned_class(db, class_id, teacher))


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
            _grant_course(db, m.student_id, classroom)
    for field in ("name", "semester", "description", "status"):
        value = getattr(req, field)
        if value is not None:
            setattr(classroom, field, value)
    db.commit()
    db.refresh(classroom)
    return _class_out(db, classroom)


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


@router.get("/{class_id}/members", response_model=ClassMembersOut)
def list_members(
    class_id: int,
    teacher: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    classroom = _owned_class(db, class_id, teacher)
    rows = (
        db.query(ClassMember, User)
        .join(User, ClassMember.student_id == User.id)
        .filter(ClassMember.class_id == classroom.id)
        .order_by(ClassMember.joined_at.desc())
        .all()
    )
    items = [
        ClassMemberOut(
            student_id=user.id, name=user.name, email=user.email,
            joined_at=member.joined_at, status=member.status,
        )
        for member, user in rows
    ]
    return ClassMembersOut(total=len(items), items=items)


@router.post("/{class_id}/members", response_model=ClassMemberOut)
def invite_member(
    class_id: int,
    req: ClassInviteRequest,
    teacher: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    """按邮箱或学生 ID 直接邀请(学生需已注册)"""
    classroom = _owned_class(db, class_id, teacher)
    if classroom.status != "active":
        raise HTTPException(status_code=400, detail="班级已归档，无法邀请")

    query = db.query(User).filter(User.role == "student")
    if req.student_id:
        student = query.filter(User.id == req.student_id).first()
    elif req.email:
        student = query.filter(User.email == req.email).first()
    else:
        raise HTTPException(status_code=400, detail="请提供学生 ID 或邮箱")
    if not student:
        raise HTTPException(status_code=404, detail="未找到该学生，请确认已注册")

    _join_member(db, classroom, student)
    db.commit()
    member = db.query(ClassMember).filter(
        ClassMember.class_id == classroom.id,
        ClassMember.student_id == student.id,
    ).first()
    return ClassMemberOut(
        student_id=student.id, name=student.name, email=student.email,
        joined_at=member.joined_at, status=member.status,
    )


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
        raise HTTPException(status_code=404, detail="该学生不在班级中")
    member.status = "left"
    _revoke_course_if_alone(db, student_id, classroom)
    db.commit()
    return {"class_id": classroom.id, "student_id": student_id, "status": "left"}


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
    return [_class_out(db, c) for c in rows]


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
