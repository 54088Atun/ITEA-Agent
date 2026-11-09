"""认证路由:注册 / 登录 / 当前用户 / 静态文件鉴权"""
import logging
import threading
import time
from collections import deque
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.core.security import (
    create_access_token, create_refresh_token, decode_refresh_token, hash_password,
    verify_password,
)
from app.core.deps import get_current_user, user_from_token
from app.core.log_sanitizer import mask_email
from app.models.user import User
from app.schemas.auth import RegisterRequest, LoginRequest, TokenResponse, UserOut
from app.services.captcha import (
    captcha_required, generate_captcha, verify_captcha,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["认证"])

# 静态文件(/uploads、/static/generated)由 nginx auth_request 校验该 Cookie
AUTH_COOKIE = "itea_auth"
# 刷新令牌只在本站接口内使用,Path 收窄到 /api/auth,减少暴露面
AUTH_REFRESH_COOKIE = "itea_refresh"

# 登录失败限流:同一账号 5 分钟内失败 5 次后暂时锁定(内存级,多实例由网关限流兜底)
LOGIN_MAX_FAILURES = 5
LOGIN_FAILURE_WINDOW = 300
_login_failures: dict[str, deque] = {}
_login_failures_lock = threading.Lock()


def _login_key(email: str) -> str:
    return (email or "").strip().lower()


def _prune_login_failures(key: str, now: float) -> deque:
    bucket = _login_failures.setdefault(key, deque())
    while bucket and now - bucket[0] > LOGIN_FAILURE_WINDOW:
        bucket.popleft()
    return bucket


def _assert_login_allowed(email: str) -> None:
    key = _login_key(email)
    if not key:
        return
    with _login_failures_lock:
        bucket = _prune_login_failures(key, time.monotonic())
        if not bucket:
            _login_failures.pop(key, None)
            return
        if len(bucket) >= LOGIN_MAX_FAILURES:
            raise HTTPException(
                status_code=429,
                detail="登录失败次数过多，请 5 分钟后再试",
                headers={"Retry-After": str(LOGIN_FAILURE_WINDOW)},
            )


def _record_login_failure(email: str) -> None:
    key = _login_key(email)
    if not key:
        return
    with _login_failures_lock:
        if len(_login_failures) > 5000:
            _login_failures.clear()
        now = time.monotonic()
        _prune_login_failures(key, now).append(now)


def _clear_login_failures(email: str) -> None:
    with _login_failures_lock:
        _login_failures.pop(_login_key(email), None)


def _register_domains() -> list[str]:
    raw = settings.REGISTER_EMAIL_DOMAINS or ""
    return [
        item.strip().lower().lstrip("@")
        for item in raw.split(",")
        if item.strip()
    ]


def _assert_register_domain(email: str) -> None:
    """配置了校园域白名单时,只允许白名单及其子域注册"""
    domains = _register_domains()
    if not domains:
        return
    local, _, domain = (email or "").rpartition("@")
    domain = domain.lower()
    allowed = bool(local) and any(
        domain == item or domain.endswith("." + item) for item in domains
    )
    if not allowed:
        raise HTTPException(
            status_code=403,
            detail="仅支持校园邮箱注册，请联系管理员",
        )


def _assert_captcha(captcha_id: Optional[str], code: Optional[str]) -> None:
    """开启图形验证码时,登录/注册必须携带有效的一次性验证码"""
    if not captcha_required():
        return
    if not verify_captcha(captcha_id or "", code or ""):
        raise HTTPException(
            status_code=400,
            detail="验证码错误或已过期，请刷新后重试",
        )


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


def _set_refresh_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=AUTH_REFRESH_COOKIE,
        value=token,
        max_age=settings.REFRESH_TOKEN_EXPIRE_MINUTES * 60,
        httponly=True,
        secure=settings.ENVIRONMENT.strip().lower() == "production",
        samesite="lax",
        path="/api/auth",
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
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        role=user.role,
        name=user.name,
        user_id=user.id,
        user=UserOut.model_validate(user),
    )


def _issue_session(user: User, response: Response) -> TokenResponse:
    """签发访问令牌 + 刷新令牌,并写入 HttpOnly Cookie"""
    payload = _token_response(user)
    refresh = create_refresh_token(
        user.id, getattr(user, "token_version", 0) or 0,
    )
    _set_auth_cookie(response, payload.access_token)
    _set_refresh_cookie(response, refresh)
    return payload


@router.get("/captcha")
def get_captcha():
    """获取图形验证码;未启用时返回 required=False,前端据此隐藏输入框"""
    if not captcha_required():
        return {"required": False, "captcha_id": "", "image": "", "expires_in": 0}
    return {"required": True, **generate_captcha()}


@router.post("/register", response_model=TokenResponse)
def register(req: RegisterRequest, response: Response, db: Session = Depends(get_db)):
    """用户注册(公开注册仅开放学生;教师账号需管理员开通)"""
    _assert_captcha(req.captcha_id, req.captcha_code)
    if req.role != "student":
        raise HTTPException(status_code=403, detail="教师账号需由管理员开通")
    _assert_register_domain(req.email)
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
    return _issue_session(user, response)


@router.post("/login", response_model=TokenResponse)
def login(req: LoginRequest, response: Response, db: Session = Depends(get_db)):
    """邮箱密码登录"""
    _assert_captcha(req.captcha_id, req.captcha_code)
    _assert_login_allowed(req.email)
    user = db.query(User).filter(User.email == req.email).first()
    if not user or not verify_password(req.password, user.password_hash):
        _record_login_failure(req.email)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="邮箱或密码错误",
        )
    if getattr(user, "status", "active") == "disabled":
        raise HTTPException(status_code=403, detail="账号已被禁用")

    _clear_login_failures(req.email)
    logger.info("用户登录: %s (%s)", mask_email(user.email), user.role)
    return _issue_session(user, response)


@router.post("/refresh", response_model=TokenResponse)
def refresh(request: Request, response: Response, db: Session = Depends(get_db)):
    """用 HttpOnly 刷新令牌换发新的访问令牌,并轮换刷新令牌"""
    token = request.cookies.get(AUTH_REFRESH_COOKIE) or ""
    payload = decode_refresh_token(token) if token else None
    if payload is None:
        raise HTTPException(status_code=401, detail="登录状态已失效，请重新登录")
    try:
        user_id = int(payload.get("sub"))
        token_version = int(payload.get("ver", 0))
    except (TypeError, ValueError):
        raise HTTPException(status_code=401, detail="登录状态已失效，请重新登录")

    user = db.query(User).filter(User.id == user_id).first()
    if user is None or int(getattr(user, "token_version", 0) or 0) != token_version:
        raise HTTPException(status_code=401, detail="登录状态已失效，请重新登录")
    if getattr(user, "status", "active") == "disabled":
        raise HTTPException(status_code=403, detail="账号已被禁用")
    return _issue_session(user, response)


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
    """退出登录时清除访问令牌与刷新令牌 Cookie"""
    response.delete_cookie(AUTH_COOKIE, path="/")
    response.delete_cookie(AUTH_REFRESH_COOKIE, path="/api/auth")
    return {"ok": True}


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    """获取当前登录用户信息"""
    return user
