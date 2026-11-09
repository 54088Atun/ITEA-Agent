"""请求级 request_id 上下文

同一个请求产生的日志、工具决策审计、上传拒绝、通知写入与运行轨迹
都可通过 request_id 串联;客户端传入的 X-Request-ID 只作为追踪标识,
不参与任何鉴权或幂等判定。
"""
import contextvars
import logging
import uuid

_request_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id", default="-",
)
_client_ip: contextvars.ContextVar[str] = contextvars.ContextVar(
    "client_ip", default="",
)


def get_request_id() -> str:
    return _request_id.get()


def get_client_ip() -> str:
    return _client_ip.get()


def _extract_client_ip(scope) -> str:
    headers = dict(scope.get("headers") or [])
    forwarded = (headers.get(b"x-forwarded-for") or b"").decode("latin-1")
    if forwarded:
        return forwarded.split(",")[0].strip()
    client = scope.get("client") or ()
    return client[0] if client else ""


class RequestContextMiddleware:
    """纯 ASGI 中间件:生成/透传 request_id 并回写响应头(兼容 SSE 流式响应)"""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers") or [])
        incoming = (headers.get(b"x-request-id") or b"").decode("latin-1").strip()
        request_id = incoming[:64] or uuid.uuid4().hex[:16]
        scope.setdefault("state", {})["request_id"] = request_id
        token = _request_id.set(request_id)
        ip_token = _client_ip.set(_extract_client_ip(scope))

        async def send_with_header(message):
            if message["type"] == "http.response.start":
                message.setdefault("headers", []).append(
                    (b"x-request-id", request_id.encode("latin-1")),
                )
            await send(message)

        try:
            await self.app(scope, receive, send_with_header)
        finally:
            _client_ip.reset(ip_token)
            _request_id.reset(token)


class RequestIdLogFilter(logging.Filter):
    """把当前请求 request_id 注入日志记录;非请求上下文显示为 '-'"""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id()
        return True
