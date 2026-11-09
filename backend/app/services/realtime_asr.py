"""百炼实时语音识别:浏览器 WebSocket 与 DashScope WebSocket 桥接

链路:
浏览器 PCM16/16k 音频分片 → 本服务 WebSocket → DashScope 实时 ASR
DashScope 的中间/最终识别结果 → 浏览器输入框实时回填

鉴权:
浏览器 WebSocket 无法携带 Authorization 头,因此先由 HTTP 接口签发
60 秒有效的一次性 JWT(typ=asr_stream),再通过查询参数建立连接。
"""
import asyncio
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone

import websockets
from fastapi import WebSocket
from jose import JWTError, jwt

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.user import User
from app.services.quotas import record_audio_upload

logger = logging.getLogger(__name__)

TICKET_TTL_SECONDS = 60
# 16k 单声道 PCM16:1 秒 = 32000 字节,300 秒约 9.6MB
MAX_STREAM_BYTES = 10 * 1024 * 1024
BYTES_PER_SECOND = 32000


def _api_key() -> str:
    return settings.ASR_API_KEY or settings.DASHSCOPE_API_KEY


def issue_stream_ticket(user: User) -> str:
    """签发短时实时识别票据,只允许建立一次 WebSocket"""
    expire = datetime.now(timezone.utc) + timedelta(seconds=TICKET_TTL_SECONDS)
    payload = {
        "sub": str(user.id),
        "ver": int(getattr(user, "token_version", 0) or 0),
        "typ": "asr_stream",
        "exp": expire,
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def user_from_stream_ticket(token: str, db) -> User | None:
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM],
        )
    except JWTError:
        return None
    if payload.get("typ") != "asr_stream":
        return None
    try:
        user_id = int(payload.get("sub") or 0)
    except (TypeError, ValueError):
        return None
    user = db.query(User).filter(User.id == user_id).first()
    if not user or getattr(user, "status", "active") == "disabled":
        return None
    if int(payload.get("ver") or 0) != int(getattr(user, "token_version", 0) or 0):
        return None
    return user


async def _send(websocket: WebSocket, payload: dict) -> None:
    try:
        await websocket.send_json(payload)
    except Exception:  # noqa: BLE001 - 浏览器可能已断开
        pass


def _record_usage(user_id: int, size: int) -> None:
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if user:
            record_audio_upload(
                db, user, size, max(0.0, size / BYTES_PER_SECOND),
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("实时语音用量记录失败(user=%s): %s", user_id, exc)
    finally:
        db.close()


async def relay_audio_stream(websocket: WebSocket, user: User) -> None:
    """建立 DashScope 任务并把识别结果实时转发给浏览器"""
    key = _api_key()
    if not key:
        await _send(websocket, {"type": "error", "message": "语音识别未配置"})
        await websocket.close()
        return

    task_id = str(uuid.uuid4())
    model = settings.ASR_REALTIME_MODEL or "qwen-audio-3.1-asr-flash-message"
    url = settings.ASR_REALTIME_URL or "wss://dashscope.aliyuncs.com/api-ws/v1/inference"
    run_message = {
        "header": {"action": "run-task", "task_id": task_id, "streaming": "duplex"},
        "payload": {
            "task_group": "audio",
            "task": "asr",
            "function": "recognition",
            "model": model,
            "parameters": {
                "format": "pcm",
                "sample_rate": 16000,
                "intermediate_result_enabled": True,
            },
            "input": {},
        },
    }
    finish_message = {
        "header": {"action": "finish-task", "task_id": task_id, "streaming": "duplex"},
        "payload": {"input": {}},
    }
    stats = {"bytes": 0, "started": False, "finished": False}

    try:
        async with websockets.connect(
            url,
            additional_headers={"Authorization": f"Bearer {key}"},
            open_timeout=15,
            close_timeout=5,
            max_size=2 * 1024 * 1024,
            ping_interval=20,
            ping_timeout=20,
        ) as ds:
            await ds.send(json.dumps(run_message, ensure_ascii=False))
            # 必须等 task-started 后才能发送音频
            while True:
                raw = await asyncio.wait_for(ds.recv(), timeout=12)
                if isinstance(raw, bytes):
                    continue
                data = json.loads(raw)
                event = (data.get("header") or {}).get("event")
                if event == "task-started":
                    stats["started"] = True
                    break
                if event == "task-failed":
                    message = (data.get("header") or {}).get("error_message") or "识别任务启动失败"
                    await _send(websocket, {"type": "error", "message": message})
                    return

            await _send(websocket, {"type": "started"})

            async def pump_client() -> None:
                while True:
                    message = await websocket.receive()
                    if message.get("type") == "websocket.disconnect":
                        return
                    data = message.get("bytes")
                    if data:
                        stats["bytes"] += len(data)
                        if stats["bytes"] > MAX_STREAM_BYTES:
                            await _send(
                                websocket,
                                {"type": "error", "message": "录音超过 300 秒上限，已自动结束"},
                            )
                            await ds.send(json.dumps(finish_message, ensure_ascii=False))
                            return
                        await ds.send(data)
                        continue
                    text = message.get("text")
                    if not text:
                        continue
                    try:
                        command = json.loads(text)
                    except ValueError:
                        continue
                    if command.get("type") == "stop":
                        await ds.send(json.dumps(finish_message, ensure_ascii=False))
                        return

            async def pump_dashscope() -> None:
                while True:
                    raw = await ds.recv()
                    if isinstance(raw, bytes):
                        continue
                    data = json.loads(raw)
                    event = (data.get("header") or {}).get("event")
                    if event == "result-generated":
                        output = ((data.get("payload") or {}).get("output") or {})
                        sentence = output.get("sentence") or {}
                        text = str(sentence.get("text") or "").strip()
                        if not text:
                            continue
                        if sentence.get("sentence_end"):
                            await _send(websocket, {"type": "sentence", "text": text})
                        else:
                            await _send(websocket, {"type": "partial", "text": text})
                    elif event == "task-finished":
                        stats["finished"] = True
                        await _send(websocket, {"type": "finished"})
                        return
                    elif event == "task-failed":
                        message = (data.get("header") or {}).get("error_message") or "语音识别失败"
                        await _send(websocket, {"type": "error", "message": message})
                        return

            client_task = asyncio.create_task(pump_client())
            ds_task = asyncio.create_task(pump_dashscope())
            done, pending = await asyncio.wait(
                {client_task, ds_task}, return_when=asyncio.FIRST_COMPLETED,
            )
            if ds_task not in done:
                # 客户端已点停止:等待最终结果,最多 6 秒
                try:
                    await asyncio.wait_for(asyncio.shield(ds_task), timeout=6)
                except Exception:  # noqa: BLE001
                    pass
            for task in pending:
                task.cancel()
            if not stats["finished"]:
                await _send(websocket, {"type": "finished"})
    except Exception as exc:  # noqa: BLE001
        logger.warning("实时语音识别中断(user=%s): %s", user.id, exc)
        await _send(websocket, {"type": "error", "message": "实时语音识别连接中断，请重试"})
    finally:
        if stats["bytes"]:
            _record_usage(user.id, stats["bytes"])
        try:
            await websocket.close()
        except Exception:  # noqa: BLE001
            pass
