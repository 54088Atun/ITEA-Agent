"""认证路由:注册 / 登录 / 当前用户 / 静态文件鉴权"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.core.security import hash_password, verify_password, create_access_token
from app.core.deps import get_current_user, user_from_token
from app.core.log_sanitizer import mask_email
from app.models.user import User
from app.schemas.auth import RegisterRequest, LoginRequest, TokenResponse, UserOut

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["认证"])

# 静态文件(/uploads、/static/generated)由 nginx auth_request 校验该 Cookie
AUTH_COOKIE = "itea_auth"


def _set_auth_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=AUTH_COOKIE,
        value=token,
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        httponly=True,
        secure=settings.ENVIRONMENT.strip().lower() == "production",
        samesite="lax",
        path="/",
    )


def _request_token(request: Request) -> str:
    token = request.cookies.get(AUTH_COOKIE) or ""
    if token:
        return token
    header = request.headers.get("authorization") or ""
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return ""



def _token_response(user: User) -> TokenResponse:
    """统一构造登录响应(兼容旧扁平字段 + 新 user 对象)"""
    token = create_access_token(
        user.id, user.role, getattr(user, "token_version", 0) or 0,
    )
    return TokenResponse(
        access_token=token,
        role=user.role,
        name=user.name,
        user_id=user.id,
        user=UserOut.model_validate(user),
    )


@router.post("/register", response_model=TokenResponse)
def register(req: RegisterRequest, response: Response, db: Session = Depends(get_db)):
    """用户注册(教师/学生)"""
    existing = db.query(User).filter(User.email == req.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="该邮箱已注册")

    user = User(
        role=req.role,
        name=req.name,
        email=req.email,
        password_hash=hash_password(req.password),
        status="active",
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    logger.info("新用户注册: %s (%s)", mask_email(user.email), user.role)
    payload = _token_response(user)
    _set_auth_cookie(response, payload.access_token)
    return payload


@router.post("/login", response_model=TokenResponse)
def login(req: LoginRequest, response: Response, db: Session = Depends(get_db)):
    """邮箱密码登录"""
    user = db.query(User).filter(User.email == req.email).first()
    if not user or not verify_password(req.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="邮箱或密码错误",
        )
    if getattr(user, "status", "active") == "disabled":
        raise HTTPException(status_code=403, detail="账号已被禁用")

    logger.info("用户登录: %s (%s)", mask_email(user.email), user.role)
    payload = _token_response(user)
    _set_auth_cookie(response, payload.access_token)
    return payload


@router.get("/verify")
def verify(request: Request, db: Session = Depends(get_db)):
    """供 nginx auth_request 校验静态文件访问;也接受 Authorization 头"""
    token = _request_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="未登录")
    user = user_from_token(token, db)
    return {"ok": True, "role": user.role}


@router.post("/logout")
def logout(response: Response):
    """退出登录时清除静态文件鉴权 Cookie"""
    response.delete_cookie(AUTH_COOKIE, path="/")
    return {"ok": True}


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    """获取当前登录用户信息"""
    return user
