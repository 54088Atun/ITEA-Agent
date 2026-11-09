"""静态文件归属校验:上传文件与生成文件按目录约定做逐文件 ACL

只做"文件路径 → 归属"的判定,不处理登录态;调用方(入口中间件)负责先解析用户。

约定:
- `/uploads/vision/{uid}/...`、`/uploads/audio/{uid}/...` 仅本人可读
- `/uploads/avatar/...` 站内登录用户可读(头像需在列表/聊天中互相展示)
- `/uploads/{course_id}/...` 按课程可见性判定(教师/协作者/选课学生/管理员),
  其中 `drafts` 子目录只允许教师与管理员
- `/static/generated/{uid}/...`、`/generated/{uid}/...` 仅生成者本人可读
- 其余历史路径保持"登录可读",避免破坏旧链接

任何包含 `.`、`..` 或反斜杠的路径段一律拒绝,防止用相对路径绕过归属判断。
"""
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.user import User
from app.services.course_access import assert_course_visible

UPLOAD_PREFIX = "/uploads/"
GENERATED_PREFIXES = ("/static/generated/", "/generated/")
# 检索索引只供后端读取,任何用户都不通过静态路由下载
INDEX_PREFIX = "/static/faiss_indexes/"
PRIVATE_UPLOAD_DIRS = ("vision", "audio")


def _segments(path: str) -> list[str]:
    return [seg for seg in path.split("/") if seg]


def _safe_segments(parts: list[str]) -> bool:
    return all(seg not in (".", "..") and "\\" not in seg for seg in parts)


def _int(text: str) -> int | None:
    try:
        return int(text)
    except (TypeError, ValueError):
        return None


def _upload_allowed(parts: list[str], user: User, db: Session) -> bool:
    if not parts:
        return False
    head = parts[0].lower()
    if head in PRIVATE_UPLOAD_DIRS:
        return len(parts) >= 2 and _int(parts[1]) == int(user.id)
    if head == "avatar":
        return True

    course_id = _int(head)
    if course_id is not None:
        try:
            assert_course_visible(user, course_id, db)
        except HTTPException:
            return False
        if "drafts" in [seg.lower() for seg in parts[1:]]:
            return user.role in ("teacher", "admin")
        return True
    return True


def _generated_allowed(parts: list[str], user: User) -> bool:
    owner_id = _int(parts[0]) if parts else None
    if owner_id is not None:
        return owner_id == int(user.id)
    # 旧文件没有归属目录,保持登录可读
    return True


def is_static_allowed(path: str, user: User, db: Session) -> bool:
    """判断当前登录用户能否读取该静态文件路径"""
    if path.startswith(INDEX_PREFIX):
        return False

    if path.startswith(UPLOAD_PREFIX):
        parts = _segments(path[len(UPLOAD_PREFIX):])
        return _safe_segments(parts) and _upload_allowed(parts, user, db)

    for prefix in GENERATED_PREFIXES:
        if path.startswith(prefix):
            parts = _segments(path[len(prefix):])
            return _safe_segments(parts) and _generated_allowed(parts, user)

    return True
