"""FastAPI 依赖注入:获取当前用户"""
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.core.security import decode_access_token
from app.models.user import User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    credentials_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="无效的认证凭据",
        headers={"WWW-Authenticate": "Bearer"},
    )
    payload = decode_access_token(token)
    if payload is None:
        raise credentials_exc
    user_id = int(payload.get("sub", 0))
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise credentials_exc
    if getattr(user, "status", "active") == "disabled":
        raise HTTPException(status_code=403, detail="账号已被禁用")
    return user


def require_teacher(user: User = Depends(get_current_user)) -> User:
    # admin 为超集角色,可访问教师端能力
    if user.role not in ("teacher", "admin"):
        raise HTTPException(status_code=403, detail="仅教师可访问")
    return user


def require_student(user: User = Depends(get_current_user)) -> User:
    # admin 为超集角色,可访问学生端能力
    if user.role not in ("student", "admin"):
        raise HTTPException(status_code=403, detail="仅学生可访问")
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可访问")
    if getattr(user, "status", "active") != "active":
        raise HTTPException(status_code=403, detail="账号已被禁用")
    return user


def admin_level_of(user: User) -> str:
    """历史管理员的空级别按超管兼容，新管理员由管理接口显式赋值。"""
    return user.admin_level or "super"


def require_admin_write(user: User = Depends(require_admin)) -> User:
    if admin_level_of(user) == "observer":
        raise HTTPException(status_code=403, detail="观察者仅可查看")
    return user


def require_super_admin(user: User = Depends(require_admin)) -> User:
    if admin_level_of(user) != "super":
        raise HTTPException(status_code=403, detail="仅超级管理员可执行此操作")
    return user
