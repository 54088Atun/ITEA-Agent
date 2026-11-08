"""高危工具确认令牌

工具循环遇到 `requires_confirmation` 的工具时签发一次性令牌,前端展示确认卡片;
用户确认后凭令牌调用 `/chat/confirm-tool` 执行。令牌与「会话 + 用户 + 工具 + 参数摘要」
绑定并带过期时间,模型与客户端都无法伪造,只有真实用户点击确认才能放行。
"""
import hashlib
import hmac
import json
import time

from app.core.config import settings

# 确认卡片有效期:超时后需重新发起对话
TOKEN_TTL_SECONDS = 600
_SEPARATOR = "."


def _args_digest(arguments) -> str:
    raw = json.dumps(
        arguments or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def _sign(session_id, user_id, tool, arguments, expires_at: int) -> str:
    payload = json.dumps(
        {
            "s": str(session_id or ""),
            "u": int(user_id or 0),
            "t": str(tool or ""),
            "a": _args_digest(arguments),
            "e": int(expires_at),
        },
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    )
    return hmac.new(
        settings.SECRET_KEY.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def issue_tool_token(session_id, user_id, tool, arguments) -> str:
    """签发确认令牌:返回 `过期时间戳.签名`"""
    expires_at = int(time.time()) + TOKEN_TTL_SECONDS
    return f"{expires_at}{_SEPARATOR}{_sign(session_id, user_id, tool, arguments, expires_at)}"


def verify_tool_token(token, session_id, user_id, tool, arguments) -> bool:
    """校验令牌:签名不符、参数被改或已过期均返回 False"""
    try:
        expires_raw, signature = str(token or "").split(_SEPARATOR, 1)
        expires_at = int(expires_raw)
    except (ValueError, AttributeError):
        return False
    if expires_at < int(time.time()):
        return False
    expected = _sign(session_id, user_id, tool, arguments, expires_at)
    return hmac.compare_digest(expected, signature)
