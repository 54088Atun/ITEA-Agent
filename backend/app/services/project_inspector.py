"""项目自检服务:只读、路径沙箱、禁止任意 shell

边界:
- 只能访问仓库根目录内的文本文件,禁止绝对路径与 ../ 越界
- 跳过 .env、.git、依赖与构建产物目录
- git 只执行固定命令;测试只执行预置命令
"""
import os
import subprocess
import sys
import time
from pathlib import Path

from app.core.config import BASE_DIR, settings


class ProjectAccessError(Exception):
    """路径越界、敏感文件或参数非法"""


class ProjectExecError(Exception):
    """预置命令执行失败"""


TEXT_SUFFIXES = {
    ".py", ".vue", ".js", ".ts", ".json", ".md", ".yml", ".yaml",
    ".html", ".css", ".sql", ".toml", ".txt", ".ini", ".cfg",
    ".ps1", ".sh", ".bat", ".xml", ".env.example",
}
SKIP_DIRS = {
    ".git", "node_modules", "dist", "build", "__pycache__", ".venv",
    "venv", "uploads", "static", "coverage", ".pytest_cache", ".idea",
    ".vscode", "logs",
}
SENSITIVE_NAMES = {
    ".env", ".env.local", ".env.production", ".env.development",
    "id_rsa", "id_ed25519", "credentials.json", "secrets.json",
}
MAX_SCAN_FILES = 5000
MAX_MATCH_LINES = 50
MAX_DIFF_CHARS = 50_000
MAX_TEST_OUTPUT = 20_000
MAX_LOG_FILES = 20
MAX_LOG_MATCHES = 200

TEST_SUITES = {
    "all": ["-q"],
    "agent": [
        "tests/test_admin_agent.py", "tests/test_agent_evolution.py",
        "tests/test_agent_data_api.py", "-q",
    ],
    "api": [
        "tests/test_p2.py", "tests/test_assignments.py", "tests/test_exam.py", "-q",
    ],
    "security": [
        "tests/test_role_capabilities.py", "tests/test_security_levels.py",
        "tests/test_answer_guard.py", "-q",
    ],
}


def repo_root() -> Path:
    """仓库根目录:可由 PROJECT_ROOT 覆盖,默认取 backend 的上一级"""
    raw = (settings.PROJECT_ROOT or "").strip()
    root = Path(raw).expanduser() if raw else BASE_DIR.parent
    return root.resolve()


def _relative(path: Path, root: Path) -> str:
    return str(path.relative_to(root)).replace("\\", "/")


def _check_allowed(path: Path, root: Path) -> None:
    try:
        parts = path.relative_to(root).parts
    except ValueError:
        parts = path.parts
    if any(part in SKIP_DIRS for part in parts):
        raise ProjectAccessError("该目录不开放访问")
    if path.name in SENSITIVE_NAMES or path.name.startswith(".env"):
        raise ProjectAccessError("敏感文件不可读取")


def _resolve_dir(relative: str) -> tuple[Path, Path]:
    root = repo_root()
    target = root if not (relative or "").strip() else (root / relative).resolve()
    if target != root and root not in target.parents:
        raise ProjectAccessError("路径超出项目根目录")
    if not target.exists():
        raise ProjectAccessError("目录不存在")
    if not target.is_dir():
        raise ProjectAccessError("目标不是目录")
    _check_allowed(target, root)
    return target, root


def _resolve_file(relative: str) -> tuple[Path, Path]:
    text = (relative or "").strip()
    if not text:
        raise ProjectAccessError("缺少文件路径")
    if Path(text).is_absolute():
        raise ProjectAccessError("只接受项目内相对路径")
    root = repo_root()
    target = (root / text).resolve()
    if root not in target.parents:
        raise ProjectAccessError("路径超出项目根目录")
    if not target.exists() or not target.is_file():
        raise ProjectAccessError("文件不存在")
    _check_allowed(target, root)
    return target, root


def search_code(query: str, path: str = "", limit: int = 20) -> dict:
    """按字面量搜索项目文本文件,返回文件、行号与片段"""
    keyword = (query or "").strip()
    if not keyword:
        raise ProjectAccessError("缺少搜索关键词")
    if len(keyword) > 100:
        raise ProjectAccessError("搜索关键词过长")
    limit = min(max(1, int(limit)), MAX_MATCH_LINES)
    base, root = _resolve_dir(path)

    matches: list[dict] = []
    scanned = 0
    truncated = False
    needle = keyword.lower()

    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = [
            name for name in dirnames
            if name not in SKIP_DIRS and not name.startswith(".")
        ]
        for name in filenames:
            if name.startswith(".env"):
                continue
            suffix = Path(name).suffix.lower()
            if suffix not in TEXT_SUFFIXES:
                continue
            file_path = Path(dirpath) / name
            try:
                if file_path.stat().st_size > settings.PROJECT_MAX_FILE_BYTES:
                    continue
                text = file_path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue

            scanned += 1
            for lineno, line in enumerate(text.splitlines(), 1):
                if needle in line.lower():
                    matches.append({
                        "file": _relative(file_path, root),
                        "line": lineno,
                        "snippet": line.strip()[:200],
                    })
                    if len(matches) >= limit:
                        truncated = True
                        break
            if truncated:
                break
            if scanned >= MAX_SCAN_FILES:
                truncated = True
                break
        if truncated:
            break

    return {
        "query": keyword,
        "path": path or ".",
        "matches": matches,
        "scanned_files": scanned,
        "truncated": truncated,
    }


def read_file(path: str, start_line: int = 1, end_line: int | None = None) -> dict:
    """读取项目内文本文件,限制单次行数与文件大小"""
    target, root = _resolve_file(path)
    size = target.stat().st_size
    if size > settings.PROJECT_MAX_FILE_BYTES:
        raise ProjectAccessError(
            f"文件过大({size} 字节),上限 {settings.PROJECT_MAX_FILE_BYTES} 字节",
        )
    raw = target.read_bytes()
    if b"\x00" in raw:
        raise ProjectAccessError("二进制文件不可读取")

    lines = raw.decode("utf-8", errors="replace").splitlines()
    total = len(lines)
    start = max(1, int(start_line or 1))
    if start > total and total > 0:
        raise ProjectAccessError("起始行超出文件范围")
    max_lines = settings.PROJECT_MAX_READ_LINES
    requested_end = int(end_line) if end_line else start + max_lines - 1
    end = min(total, max(requested_end, start), start + max_lines - 1)
    content = "\n".join(lines[start - 1:end]) if total else ""

    return {
        "path": _relative(target, root),
        "start_line": start,
        "end_line": end,
        "total_lines": total,
        "truncated": end < total,
        "content": content,
    }


def git_diff(stat_only: bool = False) -> dict:
    """只执行固定 git diff 命令,不接受任意参数"""
    root = repo_root()
    command = ["git", "diff", "--no-color"]
    if stat_only:
        command.append("--stat")
    started = time.monotonic()
    try:
        completed = subprocess.run(
            command, cwd=str(root), capture_output=True, text=True,
            timeout=15, shell=False, encoding="utf-8", errors="replace",
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ProjectExecError(f"git diff 执行失败: {exc}") from exc

    output = completed.stdout or ""
    truncated = len(output) > MAX_DIFF_CHARS
    return {
        "command": " ".join(command),
        "exit_code": completed.returncode,
        "truncated": truncated,
        "output": output[:MAX_DIFF_CHARS],
        "error": (completed.stderr or "")[:2000],
        "duration_ms": int((time.monotonic() - started) * 1000),
    }


def search_logs(
    keyword: str = "", level: str = "", limit: int = 100,
) -> dict:
    """在项目 logs 目录内检索 .log 文件,不读取其他路径"""
    root = repo_root()
    log_dir = root / "logs"
    if not log_dir.exists():
        return {
            "keyword": keyword, "level": level, "files_scanned": 0,
            "matches": [], "truncated": False,
        }
    if log_dir.resolve() != root and root not in log_dir.resolve().parents:
        raise ProjectAccessError("日志目录超出项目根目录")

    limit = min(max(1, int(limit)), MAX_LOG_MATCHES)
    needle = (keyword or "").strip().lower()
    level_tag = (level or "").strip().lower()
    matches: list[dict] = []
    files_scanned = 0
    truncated = False

    for file_path in sorted(log_dir.rglob("*.log")):
        if files_scanned >= MAX_LOG_FILES:
            truncated = True
            break
        try:
            if file_path.stat().st_size > settings.PROJECT_MAX_FILE_BYTES:
                continue
            text = file_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        files_scanned += 1
        for lineno, line in enumerate(text.splitlines(), 1):
            lower = line.lower()
            if needle and needle not in lower:
                continue
            if level_tag and level_tag not in lower:
                continue
            matches.append({
                "file": _relative(file_path, root),
                "line": lineno,
                "content": line.strip()[:300],
            })
            if len(matches) >= limit:
                truncated = True
                break
        if truncated:
            break

    return {
        "keyword": keyword,
        "level": level,
        "files_scanned": files_scanned,
        "matches": matches,
        "truncated": truncated,
    }


def run_tests(suite: str = "all") -> dict:
    """执行预置测试命令,不接受任意 shell 参数"""
    name = (suite or "all").strip().lower()
    args = TEST_SUITES.get(name)
    if args is None:
        raise ProjectAccessError(f"未知测试集: {suite}")

    command = [sys.executable, "-m", "pytest", *args]
    started = time.monotonic()
    try:
        completed = subprocess.run(
            command, cwd=str(BASE_DIR), capture_output=True, text=True,
            timeout=settings.PROJECT_TEST_TIMEOUT, shell=False,
            encoding="utf-8", errors="replace",
        )
    except subprocess.TimeoutExpired as exc:
        raise ProjectExecError(
            f"测试超时({settings.PROJECT_TEST_TIMEOUT} 秒),请缩小测试集",
        ) from exc
    except OSError as exc:
        raise ProjectExecError(f"测试执行失败: {exc}") from exc

    output = (completed.stdout or "") + (completed.stderr or "")
    summary = ""
    for line in reversed(output.strip().splitlines()):
        if "passed" in line or "failed" in line or "error" in line:
            summary = line.strip()
            break

    return {
        "suite": name,
        "command": " ".join(command),
        "exit_code": completed.returncode,
        "summary": summary,
        "output": output[-MAX_TEST_OUTPUT:],
        "truncated": len(output) > MAX_TEST_OUTPUT,
        "duration_ms": int((time.monotonic() - started) * 1000),
    }


def db_schema() -> dict:
    """返回表与字段结构,不返回任何业务数据"""
    from app.db.session import Base
    from app.models import (  # noqa: F401  确保模型已注册
        user, course, profile, practice, interview, classroom, conversation,
        knowledge_draft, interview_assignment, assignment, question, exam,
        upload_event, log, notification, privacy, agent_memory,
    )

    tables = []
    for table_name, table in sorted(Base.metadata.tables.items()):
        tables.append({
            "table": table_name,
            "columns": [
                {
                    "name": column.name,
                    "type": str(column.type),
                    "nullable": bool(column.nullable),
                    "primary_key": bool(column.primary_key),
                }
                for column in table.columns
            ],
        })
    return {"total": len(tables), "tables": tables}
