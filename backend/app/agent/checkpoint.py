"""基于业务库的 LangGraph 检查点存储

LangGraph 自带的 SqliteSaver 需要额外依赖,这里直接复用业务库:
每个超级步写入一条 agent_checkpoints 记录,进程重启后可按 thread 恢复。
写入失败只记日志,不影响主对话链路。
"""
import asyncio
import base64
import json
import logging
from collections.abc import AsyncIterator, Iterator, Sequence
from typing import Any, Optional

from langgraph.checkpoint.base import (
    BaseCheckpointSaver,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
)

from app.db.session import SessionLocal
from app.models.log import AgentCheckpoint

logger = logging.getLogger(__name__)

# 运行时字段:属于当前进程的内存对象,落盘时剔除,恢复时由调用方重建
DROPPED_CHANNELS = {"stream_queue"}


def thread_id_of(session_id: str) -> str:
    """会话到 LangGraph 线程的映射"""
    return f"session:{session_id}"


def graph_config(session_id: str, run_id: Optional[int] = None) -> dict:
    """构建图调用配置:thread_id 绑定会话,run_id 用于关联运行记录"""
    configurable: dict[str, Any] = {
        "thread_id": thread_id_of(session_id),
        "checkpoint_ns": "",
    }
    if run_id:
        configurable["run_id"] = run_id
    return {"configurable": configurable}


class DBCheckpointSaver(BaseCheckpointSaver):
    """把检查点写入 agent_checkpoints 表"""

    def __init__(self, session_factory=SessionLocal) -> None:
        super().__init__()
        self._session_factory = session_factory

    # ---------- 序列化 ----------

    def _dump(self, value: Any) -> str:
        kind, data = self.serde.dumps_typed(value)
        return json.dumps({"t": kind, "d": base64.b64encode(data).decode()})

    def _load(self, raw: Optional[str]) -> Any:
        if not raw:
            return None
        payload = json.loads(raw)
        return self.serde.loads_typed((payload["t"], base64.b64decode(payload["d"])))

    def _strip(self, checkpoint: Checkpoint) -> Checkpoint:
        """去掉当前进程专属的运行时通道,避免序列化失败"""
        values = dict(checkpoint.get("channel_values") or {})
        for key in DROPPED_CHANNELS:
            values.pop(key, None)
        return {**checkpoint, "channel_values": values}

    def load_state(self, raw: Optional[str]) -> Optional[Checkpoint]:
        """解析落盘的检查点快照(供恢复流程复用)"""
        return self._load(raw)

    # ---------- 写入 ----------

    def put(
        self,
        config: dict,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: dict,
    ) -> dict:
        configurable = config.get("configurable") or {}
        thread_id = configurable.get("thread_id") or ""
        namespace = configurable.get("checkpoint_ns") or ""
        checkpoint_id = checkpoint.get("id") or ""
        parent_id = configurable.get("checkpoint_id")
        result = {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": namespace,
                "checkpoint_id": checkpoint_id,
            }
        }
        db = self._session_factory()
        try:
            db.add(AgentCheckpoint(
                thread_id=thread_id,
                checkpoint_ns=namespace,
                checkpoint_id=checkpoint_id,
                parent_checkpoint_id=parent_id,
                run_id=configurable.get("run_id"),
                session_id=thread_id.partition(":")[2] or None,
                node=str((metadata or {}).get("source") or ""),
                seq=int((metadata or {}).get("step") or 0),
                state=self._dump(self._strip(checkpoint)),
                checkpoint_meta=self._dump(metadata or {}),
            ))
            db.commit()
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            logger.warning("检查点写入失败 thread=%s: %s", thread_id, exc)
        finally:
            db.close()
        return result

    def put_writes(
        self,
        config: dict,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        configurable = config.get("configurable") or {}
        thread_id = configurable.get("thread_id") or ""
        namespace = configurable.get("checkpoint_ns") or ""
        checkpoint_id = configurable.get("checkpoint_id") or ""
        if not thread_id or not checkpoint_id:
            return
        db = self._session_factory()
        try:
            row = (
                db.query(AgentCheckpoint)
                .filter(
                    AgentCheckpoint.thread_id == thread_id,
                    AgentCheckpoint.checkpoint_ns == namespace,
                    AgentCheckpoint.checkpoint_id == checkpoint_id,
                )
                .order_by(AgentCheckpoint.id.desc())
                .first()
            )
            if row is None:
                return
            existing = json.loads(row.writes) if row.writes else []
            for channel, value in writes:
                existing.append([
                    task_id, task_path, channel, self._dump(value),
                ])
            row.writes = json.dumps(existing, ensure_ascii=False)
            db.commit()
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            logger.warning("检查点中间写入失败 thread=%s: %s", thread_id, exc)
        finally:
            db.close()

    # ---------- 读取 ----------

    def _to_tuple(self, row: AgentCheckpoint, config: Optional[dict] = None) -> Optional[CheckpointTuple]:
        try:
            checkpoint = self._strip(self._load(row.state))
            # 兼容跨版本检查点:0.2.x 的 Pregel 直接下标读取 pending_sends,
            # 旧版/新版落盘快照可能没有该字段,补齐避免恢复时 KeyError
            if isinstance(checkpoint, dict):
                checkpoint.setdefault("pending_sends", [])
            metadata = self._load(row.checkpoint_meta) or {}
        except Exception as exc:  # noqa: BLE001
            logger.warning("检查点解析失败 id=%s: %s", row.id, exc)
            return None
        pending = []
        if row.writes:
            try:
                pending = [
                    (item[0], item[2], self._load(item[3]))
                    for item in json.loads(row.writes)
                ]
            except Exception:  # noqa: BLE001
                pending = []
        thread_id = row.thread_id
        namespace = row.checkpoint_ns or ""
        return CheckpointTuple(
            config=config or {
                "configurable": {
                    "thread_id": thread_id,
                    "checkpoint_ns": namespace,
                    "checkpoint_id": row.checkpoint_id,
                }
            },
            checkpoint=checkpoint,
            metadata=metadata,
            parent_config=(
                {
                    "configurable": {
                        "thread_id": thread_id,
                        "checkpoint_ns": namespace,
                        "checkpoint_id": row.parent_checkpoint_id,
                    }
                }
                if row.parent_checkpoint_id
                else None
            ),
            pending_writes=pending,
        )

    def get_tuple(self, config: dict) -> Optional[CheckpointTuple]:
        configurable = config.get("configurable") or {}
        thread_id = configurable.get("thread_id") or ""
        namespace = configurable.get("checkpoint_ns") or ""
        checkpoint_id = configurable.get("checkpoint_id")
        db = self._session_factory()
        try:
            query = db.query(AgentCheckpoint).filter(
                AgentCheckpoint.thread_id == thread_id,
                AgentCheckpoint.checkpoint_ns == namespace,
            )
            if checkpoint_id:
                query = query.filter(AgentCheckpoint.checkpoint_id == checkpoint_id)
            row = query.order_by(AgentCheckpoint.id.desc()).first()
            return self._to_tuple(row) if row else None
        finally:
            db.close()

    def list(
        self,
        config: Optional[dict],
        *,
        filter: Optional[dict[str, Any]] = None,
        before: Optional[dict] = None,
        limit: Optional[int] = None,
    ) -> Iterator[CheckpointTuple]:
        configurable = (config or {}).get("configurable") or {}
        before_cfg = (before or {}).get("configurable") or {}
        db = self._session_factory()
        try:
            query = db.query(AgentCheckpoint)
            if configurable.get("thread_id"):
                query = query.filter(AgentCheckpoint.thread_id == configurable["thread_id"])
            if configurable.get("checkpoint_ns") is not None and configurable.get("thread_id"):
                query = query.filter(
                    AgentCheckpoint.checkpoint_ns == (configurable.get("checkpoint_ns") or "")
                )
            before_id = before_cfg.get("checkpoint_id")
            if before_id:
                query = query.filter(AgentCheckpoint.checkpoint_id < before_id)
            rows = query.order_by(AgentCheckpoint.checkpoint_id.asc()).all()
        finally:
            db.close()

        count = 0
        for row in rows:
            item = self._to_tuple(row)
            if item is None:
                continue
            if filter and not all(
                value == (item.metadata or {}).get(key)
                for key, value in filter.items()
            ):
                continue
            if limit is not None and count >= limit:
                break
            count += 1
            yield item

    def delete_thread(self, thread_id: str) -> None:
        db = self._session_factory()
        try:
            db.query(AgentCheckpoint).filter(
                AgentCheckpoint.thread_id == thread_id
            ).delete(synchronize_session=False)
            db.commit()
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            logger.warning("检查点清理失败 thread=%s: %s", thread_id, exc)
        finally:
            db.close()

    # ---------- 异步包装(LangGraph astream 走这些入口) ----------

    async def aget_tuple(self, config: dict) -> Optional[CheckpointTuple]:
        return await asyncio.to_thread(self.get_tuple, config)

    async def alist(
        self,
        config: Optional[dict],
        *,
        filter: Optional[dict[str, Any]] = None,
        before: Optional[dict] = None,
        limit: Optional[int] = None,
    ) -> AsyncIterator[CheckpointTuple]:
        items = await asyncio.to_thread(
            lambda: list(self.list(
                config, filter=filter, before=before, limit=limit,
            ))
        )
        for item in items:
            yield item

    async def aput(
        self,
        config: dict,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: dict,
    ) -> dict:
        return await asyncio.to_thread(
            self.put, config, checkpoint, metadata, new_versions,
        )

    async def aput_writes(
        self,
        config: dict,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        await asyncio.to_thread(
            self.put_writes, config, writes, task_id, task_path,
        )

    async def adelete_thread(self, thread_id: str) -> None:
        await asyncio.to_thread(self.delete_thread, thread_id)


# 全局单例:避免每次建图都新建连接工厂
_checkpointer_instance: Optional[DBCheckpointSaver] = None


def get_checkpointer() -> DBCheckpointSaver:
    global _checkpointer_instance
    if _checkpointer_instance is None:
        _checkpointer_instance = DBCheckpointSaver()
    return _checkpointer_instance


def load_latest_state(
    session_id: str, run_id: Optional[int] = None, db=None,
) -> Optional[dict]:
    """读取指定运行(或线程)最近一次检查点的状态快照

    db 传入时复用调用方会话(便于接口层与测试共用一个连接),否则自建会话。
    """
    own_session = db is None
    session = SessionLocal() if own_session else db
    try:
        query = session.query(AgentCheckpoint).filter(
            AgentCheckpoint.thread_id == thread_id_of(session_id),
        )
        if run_id:
            query = query.filter(AgentCheckpoint.run_id == run_id)
        row = query.order_by(AgentCheckpoint.id.desc()).first()
        if row is None:
            return None
        return get_checkpointer().load_state(row.state)
    except Exception as exc:  # noqa: BLE001
        logger.warning("检查点读取失败 session=%s: %s", session_id, exc)
        return None
    finally:
        if own_session:
            session.close()
