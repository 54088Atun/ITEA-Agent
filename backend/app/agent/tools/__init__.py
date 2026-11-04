"""Agent 全局工具池(Function Calling)"""
from app.agent.tools.rag_search import rag_search, RAGManager
from app.agent.tools.course_evidence import course_evidence
from app.agent.tools.profile_query import profile_query
from app.agent.tools.code_executor import code_executor
from app.agent.tools.doc_generator import doc_generator
from app.agent.tools.stats_analyzer import stats_analyzer
from app.agent.tools.reminder_scheduler import reminder_scheduler
from app.agent.tools.sql_query import sql_query
from app.agent.tools.admin_tools import (
    admin_course_list, admin_material_stats, admin_user_lookup,
    admin_risk_summary, admin_config_get,
)
from app.agent.tools.project_tools import (
    project_search_code, project_read_file, project_git_diff,
    project_search_logs, project_run_tests, project_db_schema,
    web_search, web_fetch,
)

# 工具注册表:供 tool_executor 与 LLM bind_tools 使用
TOOL_REGISTRY = {
    "rag_search": rag_search,
    "course_evidence": course_evidence,
    "profile_query": profile_query,
    "code_executor": code_executor,
    "doc_generator": doc_generator,
    "stats_analyzer": stats_analyzer,
    "reminder_scheduler": reminder_scheduler,
    "sql_query": sql_query,
    "admin.course_list": admin_course_list,
    "admin.material_stats": admin_material_stats,
    "admin.user_lookup": admin_user_lookup,
    "admin.risk_summary": admin_risk_summary,
    "admin.config_get": admin_config_get,
    "project.search_code": project_search_code,
    "project.read_file": project_read_file,
    "project.git_diff": project_git_diff,
    "project.search_logs": project_search_logs,
    "project.run_tests": project_run_tests,
    "project.db_schema": project_db_schema,
    "web.search": web_search,
    "web.fetch": web_fetch,
}

__all__ = [
    "rag_search", "RAGManager", "course_evidence", "profile_query",
    "code_executor", "doc_generator",
    "stats_analyzer", "reminder_scheduler", "sql_query", "TOOL_REGISTRY",
    "admin_course_list", "admin_material_stats", "admin_user_lookup",
    "admin_risk_summary", "admin_config_get",
    "project_search_code", "project_read_file", "project_git_diff",
    "project_search_logs", "project_run_tests", "project_db_schema",
    "web_search", "web_fetch",
]
