"""上传读取:按实际写入字节限量,不信任客户端声明的长度

Content-Length / UploadFile.size 都可能被伪造或缺失,只以分块读到的真实
字节数作为安全依据。超限时清理临时文件,不覆盖既有正式文件。
"""
import logging
import os
import uuid
from pathlib import Path

from fastapi import UploadFile

logger = logging.getLogger(__name__)

CHUNK_SIZE = 1024 * 1024


class UploadTooLarge(Exception):
    """上传内容超过允许的实际字节数"""

    def __init__(self, limit_bytes: int):
        self.limit_bytes = int(limit_bytes)
        super().__init__(f"上传内容超过 {self.limit_mb}MB 上限")

    @property
    def limit_mb(self) -> str:
        value = self.limit_bytes / (1024 * 1024)
        return f"{value:g}"


def save_upload_limited(file: UploadFile, dest: Path, limit_bytes: int,
                        chunk_size: int = CHUNK_SIZE) -> int:
    """分块写入目标文件并返回实际字节数;超限抛 UploadTooLarge

    先写同目录临时文件,成功后再原子替换目标文件,因此超限不会留下
    半截文件,也不会破坏同名旧文件。
    """
    total = 0
    temp_path = dest.with_name(f"{dest.name}.{uuid.uuid4().hex}.part")
    try:
        with temp_path.open("wb") as out:
            while True:
                chunk = file.file.read(chunk_size)
                if not chunk:
                    break
                total += len(chunk)
                if total > limit_bytes:
                    logger.warning(
                        "上传拒绝(413): actual_bytes=%s limit_bytes=%s",
                        total, limit_bytes,
                    )
                    raise UploadTooLarge(limit_bytes)
                out.write(chunk)
        os.replace(temp_path, dest)
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise
    return total


async def read_upload_limited(file: UploadFile, limit_bytes: int,
                              chunk_size: int = CHUNK_SIZE) -> bytes:
    """分块读取并返回全部内容;超限抛 UploadTooLarge 且不返回部分内容"""
    total = 0
    chunks: list[bytes] = []
    while True:
        chunk = await file.read(chunk_size)
        if not chunk:
            break
        total += len(chunk)
        if total > limit_bytes:
            logger.warning(
                "上传拒绝(413): actual_bytes=%s limit_bytes=%s",
                total, limit_bytes,
            )
            raise UploadTooLarge(limit_bytes)
        chunks.append(chunk)
    return b"".join(chunks)
