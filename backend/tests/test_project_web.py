"""P2 项目自检与受控联网回归

覆盖:
- 代码搜索返回文件与行号,跳过依赖目录与敏感文件
- 读文件限制在项目根目录内,拒绝越界、敏感文件与二进制
- 日志检索只读 logs 目录
- 数据库结构只返回表与字段
- 联网检索未配置时明确失败;抓取拒绝非白名单域名
- 工具目录按角色下发 project/web 工具
"""
import pytest
from fastapi import HTTPException
from types import SimpleNamespace

import app.api.project as project_api
import app.api.web as web_api
from app.agent.tools.gateway import available_tools
from app.core.config import settings
from app.schemas.web import WebFetchRequest, WebSearchRequest
from app.services import project_inspector, web_access


@pytest.fixture()
def fake_project(tmp_path, monkeypatch):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "demo.py").write_text(
        "def hello():\n    return 'needle_token'\n", encoding="utf-8",
    )
    (tmp_path / "app" / "other.py").write_text("value = 1\n", encoding="utf-8")
    (tmp_path / ".env").write_text("SECRET_KEY=should-not-read\n", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "dep.js").write_text(
        "needle_token\n", encoding="utf-8",
    )
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "app.log").write_text(
        "2026-11-02 [ERROR] build failed at app/demo.py:2\n"
        "2026-11-02 [INFO] ok\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(settings, "PROJECT_ROOT", str(tmp_path))
    return tmp_path


def test_search_code_returns_file_and_line(fake_project):
    result = project_inspector.search_code("needle_token")
    assert result["scanned_files"] >= 1
    assert len(result["matches"]) == 1
    assert result["matches"][0]["file"] == "app/demo.py"
    assert result["matches"][0]["line"] == 2


def test_read_file_enforces_sandbox(fake_project):
    content = project_inspector.read_file("app/demo.py")
    assert "needle_token" in content["content"]
    assert content["total_lines"] == 2

    with pytest.raises(project_inspector.ProjectAccessError):
        project_inspector.read_file("../secret.txt")
    with pytest.raises(project_inspector.ProjectAccessError):
        project_inspector.read_file(".env")
    with pytest.raises(project_inspector.ProjectAccessError):
        project_inspector.read_file("node_modules/dep.js")


def test_search_skips_sensitive_and_dependency_dirs(fake_project):
    result = project_inspector.search_code("needle_token")
    files = {item["file"] for item in result["matches"]}
    assert "node_modules/dep.js" not in files
    assert ".env" not in files


def test_search_logs_reads_only_logs_dir(fake_project):
    result = project_inspector.search_logs("build failed", "error")
    assert result["files_scanned"] == 1
    assert len(result["matches"]) == 1
    assert result["matches"][0]["file"] == "logs/app.log"


def test_db_schema_returns_structure_only():
    result = project_inspector.db_schema()
    tables = {item["table"]: item for item in result["tables"]}
    assert "users" in tables
    assert any(column["name"] == "email" for column in tables["users"]["columns"])
    assert "content" not in result


def test_web_search_requires_configuration(monkeypatch):
    monkeypatch.setattr(settings, "WEB_SEARCH_PROVIDER", "none")
    monkeypatch.setattr(settings, "WEB_SEARCH_API_KEY", "")

    with pytest.raises(web_access.WebNotConfigured):
        web_access.search("最新政策")

    with pytest.raises(HTTPException) as exc:
        web_api.web_search(
            WebSearchRequest(query="最新政策"), _user=SimpleNamespace(id=1),
        )
    assert exc.value.status_code == 503


def test_web_fetch_rejects_non_whitelisted_domain(monkeypatch):
    monkeypatch.setattr(settings, "WEB_ALLOWED_DOMAINS", "edu.cn")

    with pytest.raises(web_access.WebAccessDenied):
        web_access.fetch("https://example.com/page")

    with pytest.raises(HTTPException) as exc:
        web_api.web_fetch(
            WebFetchRequest(url="https://example.com/page"),
            _user=SimpleNamespace(id=1),
        )
    assert exc.value.status_code == 403


def test_web_fetch_rejects_private_address_and_scheme(monkeypatch):
    monkeypatch.setattr(settings, "WEB_ALLOWED_DOMAINS", "127.0.0.1,example.com")

    with pytest.raises(web_access.WebAccessDenied):
        web_access.fetch("https://127.0.0.1/admin")
    with pytest.raises(web_access.WebAccessDenied):
        web_access.fetch("file:///etc/passwd")


def test_extract_text_skips_script_and_returns_title():
    html = (
        "<html><head><title>政策通知</title><script>alert(1)</script></head>"
        "<body><h1>正文标题</h1><p>正文内容</p><style>.x{}</style></body></html>"
    )
    result = web_access.extract_text(html)
    assert result["title"] == "政策通知"
    assert "正文内容" in result["text"]
    assert "alert" not in result["text"]
    assert ".x{}" not in result["text"]


def test_tools_are_exposed_by_role(monkeypatch):
    # 本用例验证角色矩阵,联网搜索按已配置处理
    monkeypatch.setattr(web_access, "web_search_enabled", lambda: True)
    admin_tools = {item["name"] for item in available_tools("admin")}
    teacher_tools = {item["name"] for item in available_tools("teacher")}
    student_tools = {item["name"] for item in available_tools("student")}

    assert {"project.search_code", "project.db_schema", "web.search"} <= admin_tools
    assert {"web.search", "web.fetch"} <= teacher_tools
    assert not {"project.search_code", "web.search"} & student_tools


def test_project_routes_require_admin_dependency():
    import inspect
    from app.core.deps import require_admin

    for endpoint in (
        project_api.search_project,
        project_api.read_project_file,
        project_api.project_git_diff,
        project_api.project_logs,
        project_api.project_run_tests,
        project_api.project_db_schema,
    ):
        params = inspect.signature(endpoint).parameters
        assert params["_admin"].default.dependency is require_admin
