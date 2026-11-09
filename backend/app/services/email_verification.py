"""邮箱验证码签发与校验

安全约束:
- 只存 HMAC-SHA256(SECRET_KEY, purpose:email:code),库泄露也无法离线还原
- 6 位数字、限时有效、单码限次、成功即消费、新码使旧码失效
- 同邮箱冷却 + 邮箱/IP 双维度小时限流,配合前置图形验证码防轰炸
"""
import hashlib
import hmac
import logging
import secrets
from datetime import datetime, timedelta
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.email_verification import EmailVerificationCode
from app.services.mailer import MailSendError, send_verification_code

logger = logging.getLogger(__name__)

PURPOSE_REGISTER = "register"
PURPOSE_RESET_PASSWORD = "reset_password"
PURPOSE_CHANGE_EMAIL = "change_email"
VALID_PURPOSES = (
    PURPOSE_REGISTER, PURPOSE_RESET_PASSWORD, PURPOSE_CHANGE_EMAIL,
)

# 开发/测试环境最近一次签发的明文码,仅用于联调与自动化测试
_dev_codes: dict[tuple[str, str], str] = {}


def normalize_email(email: Optional[str]) -> str:
    return (email or "").strip().lower()


def _hash_code(email: str, purpose: str, code: str) -> str:
    message = f"{purpose}:{email}:{code.strip()}".encode("utf-8")
    return hmac.new(
        settings.SECRET_KEY.encode("utf-8"), message, hashlib.sha256,
    ).hexdigest()


def latest_dev_code(email: str, purpose: str) -> Optional[str]:
    """返回最近一次签发的明文验证码(仅非生产环境用于联调/测试)"""
    return _dev_codes.get((normalize_email(email), purpose))


def assert_can_send(db: Session, email: str, purpose: str, ip: str) -> None:
    """发送前限流:同邮箱冷却、邮箱与 IP 的小时配额"""
    if not email:
        raise HTTPException(status_code=400, detail="邮箱格式不正确")
    now = datetime.utcnow()
    resend_after = max(0, int(settings.EMAIL_CODE_RESEND_SECONDS))

    last = (
        db.query(EmailVerificationCode)
        .filter(
            EmailVerificationCode.email == email,
            EmailVerificationCode.purpose == purpose,
        )
        .order_by(EmailVerificationCode.id.desc())
        .first()
    )
    if last and last.created_at:
        elapsed = (now - last.created_at).total_seconds()
        if elapsed < resend_after:
            wait = max(1, int(resend_after - elapsed))
            raise HTTPException(
                status_code=429,
                detail=f"发送过于频繁，请 {wait} 秒后再试",
                headers={"Retry-After": str(wait)},
            )

    hour_ago = now - timedelta(seconds=3600)
    email_count = (
        db.query(EmailVerificationCode)
        .filter(
            EmailVerificationCode.email == email,
            EmailVerificationCode.created_at >= hour_ago,
        )
        .count()
    )
    if settings.EMAIL_CODE_MAX_PER_HOUR_EMAIL > 0 and email_count >= settings.EMAIL_CODE_MAX_PER_HOUR_EMAIL:
        raise HTTPException(
            status_code=429,
            detail="该邮箱验证码请求过于频繁，请稍后再试",
            headers={"Retry-After": "3600"},
        )

    if ip and settings.EMAIL_CODE_MAX_PER_HOUR_IP > 0:
        ip_count = (
            db.query(EmailVerificationCode)
            .filter(
                EmailVerificationCode.request_ip == ip,
                EmailVerificationCode.created_at >= hour_ago,
            )
            .count()
        )
        if ip_count >= settings.EMAIL_CODE_MAX_PER_HOUR_IP:
            raise HTTPException(
                status_code=429,
                detail="当前网络验证码请求过于频繁，请稍后再试",
                headers={"Retry-After": "3600"},
            )


def issue_code(db: Session, email: str, purpose: str, ip: str) -> dict:
    """签发并发送验证码;发信失败时作废该码并抛 502"""
    now = datetime.utcnow()
    ttl = max(60, int(settings.EMAIL_CODE_TTL_SECONDS))

    # 新码使同邮箱同用途的旧码立即失效
    db.query(EmailVerificationCode).filter(
        EmailVerificationCode.email == email,
        EmailVerificationCode.purpose == purpose,
        EmailVerificationCode.consumed_at.is_(None),
    ).update({EmailVerificationCode.consumed_at: now}, synchronize_session=False)

    code = f"{secrets.randbelow(1000000):06d}"
    row = EmailVerificationCode(
        email=email,
        purpose=purpose,
        code_hash=_hash_code(email, purpose, code),
        expires_at=now + timedelta(seconds=ttl),
        attempts=0,
        request_ip=ip or None,
        created_at=now,
    )
    db.add(row)
    db.commit()

    if settings.ENVIRONMENT.strip().lower() != "production":
        _dev_codes[(email, purpose)] = code

    try:
        send_verification_code(email, purpose, code)
    except MailSendError as exc:
        row.consumed_at = datetime.utcnow()
        db.commit()
        logger.warning("验证码邮件发送失败,已作废该码: %s", type(exc).__name__)
        raise HTTPException(status_code=502, detail="邮件发送失败，请稍后重试")

    return {
        "expires_in": ttl,
        "resend_after": max(0, int(settings.EMAIL_CODE_RESEND_SECONDS)),
    }


def consume_code(db: Session, email: str, purpose: str, code: str) -> None:
    """校验并消费验证码;错误/过期/重放/超次一律 400"""
    email = normalize_email(email)
    code = (code or "").strip()
    if not email or not code:
        raise HTTPException(status_code=400, detail="验证码错误或已过期")

    row = (
        db.query(EmailVerificationCode)
        .filter(
            EmailVerificationCode.email == email,
            EmailVerificationCode.purpose == purpose,
            EmailVerificationCode.consumed_at.is_(None),
        )
        .order_by(EmailVerificationCode.id.desc())
        .first()
    )
    if row is None:
        raise HTTPException(status_code=400, detail="验证码错误或已过期")

    now = datetime.utcnow()
    if row.expires_at and row.expires_at <= now:
        row.consumed_at = now
        db.commit()
        raise HTTPException(status_code=400, detail="验证码错误或已过期")

    expected = row.code_hash or ""
    actual = _hash_code(email, purpose, code)
    if not hmac.compare_digest(expected, actual):
        row.attempts = int(row.attempts or 0) + 1
        if row.attempts >= max(1, int(settings.EMAIL_CODE_MAX_ATTEMPTS)):
            row.consumed_at = now
        db.commit()
        raise HTTPException(status_code=400, detail="验证码错误或已过期")

    row.consumed_at = now
    db.commit()
