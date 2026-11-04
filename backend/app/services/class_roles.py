"""班级内角色与权限

口径(CL-08):
- 班主任 = 班级创建者,只在该班生效,拥有全部权限
- 普通老师 = 被邀请进班的教师,可查看、邀请成员、授予课代表
- 学生角色:班长/课代表/普通学生/自定义;班长与课代表权限固定,自定义由班主任配置
- 角色与头衔只在当前班级生效
"""
import json

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.classroom import ClassMember, Classroom
from app.models.user import User

# 可分配给自定义角色的权限清单(同时用于前端展示)
PERMISSION_CATALOG = {
    "class.view": "查看班级",
    "member.view": "查看成员",
    "member.invite": "邀请成员",
    "member.manage": "管理成员（移出/改角色）",
    "role.assign_representative": "授予课代表",
    "role.assign": "赋予角色与头衔",
    "custom.manage": "配置自定义权限",
    "notice.post": "发布公告",
    "class.manage": "班级设置与归档",
}

ALL_PERMISSIONS = set(PERMISSION_CATALOG)

ROLE_LABELS = {
    "head_teacher": "班主任",
    "teacher": "任课教师",
    "monitor": "班长",
    "representative": "课代表",
    "student": "普通学生",
    "custom": "自定义",
}

# 普通老师的固定权限
TEACHER_PERMISSIONS = {
    "class.view", "member.view", "member.invite", "role.assign_representative",
}
# 学生固定角色权限
STUDENT_ROLE_PERMISSIONS = {
    "student": {"class.view"},
    "monitor": {"class.view", "member.view"},
    "representative": {"class.view", "member.view"},
}
STUDENT_ROLES = {"student", "monitor", "representative", "custom"}


def parse_permissions(raw: str | None) -> set[str]:
    if not raw:
        return set()
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return set()
    if not isinstance(data, list):
        return set()
    return {str(item) for item in data if str(item) in ALL_PERMISSIONS}


def dump_permissions(permissions) -> str | None:
    if not permissions:
        return None
    return json.dumps(sorted({p for p in permissions if p in ALL_PERMISSIONS}),
                      ensure_ascii=False)


def active_member(db: Session, class_id: int, user_id: int) -> ClassMember | None:
    return db.query(ClassMember).filter(
        ClassMember.class_id == class_id,
        ClassMember.student_id == user_id,
        ClassMember.status == "active",
    ).first()


def my_role(db: Session, classroom: Classroom, user: User) -> str | None:
    if user.role == "admin":
        return "admin"
    if classroom.teacher_id == user.id:
        return "head_teacher"
    member = active_member(db, classroom.id, user.id)
    return member.role if member else None


def permissions_of(db: Session, classroom: Classroom, user: User) -> set[str]:
    role = my_role(db, classroom, user)
    if role in ("admin", "head_teacher"):
        return set(ALL_PERMISSIONS)
    if role == "teacher":
        return set(TEACHER_PERMISSIONS)
    if role in STUDENT_ROLE_PERMISSIONS:
        return set(STUDENT_ROLE_PERMISSIONS[role])
    if role == "custom":
        member = active_member(db, classroom.id, user.id)
        return parse_permissions(member.permissions if member else None)
    return set()


def has_permission(db: Session, classroom: Classroom, user: User, permission: str) -> bool:
    return permission in permissions_of(db, classroom, user)


def require_permission(db: Session, classroom: Classroom, user: User, permission: str):
    if not has_permission(db, classroom, user, permission):
        raise HTTPException(status_code=403, detail="当前班级角色无权执行该操作")


def can_assign_role(inviter_role: str, target_role: str) -> bool:
    if target_role == "head_teacher":
        return False
    if inviter_role in ("admin", "head_teacher"):
        return target_role in ({"teacher"} | STUDENT_ROLES)
    if inviter_role == "teacher":
        return target_role == "representative"
    return False


def can_invite_role(inviter_role: str, target_role: str) -> bool:
    if inviter_role in ("admin", "head_teacher"):
        return target_role in ({"teacher"} | STUDENT_ROLES)
    if inviter_role == "teacher":
        return target_role in {"teacher", "student", "representative"}
    return False


def validate_custom_permissions(permissions) -> list[str]:
    if permissions is None:
        return []
    invalid = [p for p in permissions if p not in ALL_PERMISSIONS]
    if invalid:
        raise HTTPException(
            status_code=400,
            detail=f"无效权限: {', '.join(invalid)}",
        )
    return list(dict.fromkeys(permissions))


def ensure_role_matches_user(member_user: User, role: str) -> None:
    if role == "teacher":
        if member_user.role not in ("teacher", "admin"):
            raise HTTPException(status_code=400, detail="该用户不是教师，不能设为任课教师")
    elif role in STUDENT_ROLES:
        if member_user.role != "student":
            raise HTTPException(status_code=400, detail="该用户不是学生，不能设为班级学生角色")
    else:
        raise HTTPException(status_code=400, detail="角色不合法")
