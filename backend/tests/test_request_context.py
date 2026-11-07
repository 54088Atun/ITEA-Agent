"""请求级 request_id:透传、生成与日志注入"""
import asyncio
import logging

import httpx

from app.core.request_context import (
    RequestContextMiddleware,
    RequestIdLogFilter,
    get_request_id,
)


async def _call_app(headers=None):
    seen = {}

    async def app(scope, receive, send):
        seen["request_id"] = get_request_id()
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    transport = httpx.ASGITransport(app=RequestContextMiddleware(app))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/", headers=headers or {})
    return response, seen


def test_middleware_echoes_incoming_request_id():
    response, seen = asyncio.run(_call_app({"X-Request-ID": "trace-123"}))

    assert response.status_code == 200
    assert response.headers["x-request-id"] == "trace-123"
    assert seen["request_id"] == "trace-123"
    # 请求结束后上下文清理,后续日志不会串号
    assert get_request_id() == "-"


def test_middleware_generates_request_id_when_missing():
    response, seen = asyncio.run(_call_app())

    generated = response.headers["x-request-id"]
    assert generated and generated != "-"
    assert seen["request_id"] == generated


def test_request_id_log_filter_injects_context():
    record = logging.LogRecord(
        "test", logging.INFO, __file__, 1, "msg", None, None,
    )

    assert RequestIdLogFilter().filter(record) is True
    assert record.request_id == "-"
