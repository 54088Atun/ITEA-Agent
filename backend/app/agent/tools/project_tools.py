"""项目自检与受控联网工具:供 Agent 以工具形式调用

权限由调用方(capabilities)先校验;这里只做参数转发与异常收敛。
"""
from app.services import project_inspector, web_access


def project_search_code(query: str, path: str = "", limit: int = 20) -> dict:
    return project_inspector.search_code(query, path, limit)


def project_read_file(
    path: str, start_line: int = 1, end_line: int | None = None,
) -> dict:
    return project_inspector.read_file(path, start_line, end_line)


def project_git_diff(stat_only: bool = False) -> dict:
    return project_inspector.git_diff(stat_only)


def project_search_logs(
    keyword: str = "", level: str = "", limit: int = 100,
) -> dict:
    return project_inspector.search_logs(keyword, level, limit)


def project_run_tests(suite: str = "all") -> dict:
    return project_inspector.run_tests(suite)


def project_db_schema() -> dict:
    return project_inspector.db_schema()


def web_search(query: str, top_k: int = 5) -> dict:
    return web_access.search(query, top_k)


def web_fetch(url: str) -> dict:
    return web_access.fetch(url)
