"""项目自检路由:代码搜索 / 读文件 / git diff / 日志 / 测试 / 库结构

仅管理员可用;所有能力走只读或预置命令,不接受任意 shell。
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.deps import require_admin
from app.models.user import User
from app.services import project_inspector as inspector

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/project", tags=["项目自检"])


def _handle(exc: Exception) -> HTTPException:
    if isinstance(exc, inspector.ProjectAccessError):
        return HTTPException(status_code=400, detail=str(exc))
    return HTTPException(status_code=500, detail=f"项目自检失败: {exc}")


@router.get("/search")
def search_project(
    q: str = Query(..., min_length=1, description="字面量关键词"),
    path: str = Query("", description="相对项目根目录的子目录"),
    limit: int = Query(20, ge=1, le=50),
    _admin: User = Depends(require_admin),
):
    """代码搜索:返回文件、行号与片段,路径受限于项目根目录"""
    try:
        return inspector.search_code(q, path, limit)
    except inspector.ProjectAccessError as exc:
        raise _handle(exc)


@router.get("/file")
def read_project_file(
    path: str = Query(..., description="相对项目根目录的文件路径"),
    start_line: int = Query(1, ge=1),
    end_line: int | None = Query(None, ge=1),
    _admin: User = Depends(require_admin),
):
    """读取单个文本文件,限制文件大小与单次行数"""
    try:
        return inspector.read_file(path, start_line, end_line)
    except inspector.ProjectAccessError as exc:
        raise _handle(exc)


@router.get("/git/diff")
def project_git_diff(
    stat_only: bool = Query(False, description="只返回统计信息"),
    _admin: User = Depends(require_admin),
):
    """查看当前工作区 diff;只执行固定 git 命令"""
    try:
        return inspector.git_diff(stat_only)
    except inspector.ProjectExecError as exc:
        raise _handle(exc)


@router.get("/logs")
def project_logs(
    keyword: str = Query("", description="关键词过滤"),
    level: str = Query("", description="级别过滤,如 error"),
    limit: int = Query(100, ge=1, le=200),
    _admin: User = Depends(require_admin),
):
    """检索项目 logs 目录下的 .log 文件"""
    try:
        return inspector.search_logs(keyword, level, limit)
    except inspector.ProjectAccessError as exc:
        raise _handle(exc)


@router.post("/tests/run")
def project_run_tests(
    suite: str = Query("all", description="预置测试集: all/agent/api/security"),
    _admin: User = Depends(require_admin),
):
    """执行预置测试命令,不接受任意 shell 参数"""
    try:
        return inspector.run_tests(suite)
    except (inspector.ProjectAccessError, inspector.ProjectExecError) as exc:
        raise _handle(exc)


@router.get("/db/schema")
def project_db_schema(_admin: User = Depends(require_admin)):
    """返回表与字段结构,不包含任何业务数据"""
    try:
        return inspector.db_schema()
    except Exception as exc:  # noqa: BLE001
        raise _handle(exc)
