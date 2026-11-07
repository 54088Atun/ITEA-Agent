"""三级角色的工具、协作专家与课程数据范围能力矩阵"""
from app.agent.nodes.collab import ROLE_ALLOWED_AGENTS


ROLE_CAPABILITIES = {
    "student": {
        "tools": [
            "rag_search", "course_evidence", "profile_query",
            "reminder_scheduler",
        ],
        "agents": ROLE_ALLOWED_AGENTS["student"],
        "course_data_scope": "enrolled_approved_courses",
    },
    "teacher": {
        "tools": [
            "rag_search", "course_evidence", "profile_query",
            "doc_generator", "stats_analyzer", "sql_query",
            "reminder_scheduler", "web.search", "web.fetch",
        ],
        "agents": ROLE_ALLOWED_AGENTS["teacher"],
        "course_data_scope": "owned_courses",
    },
    "admin": {
        "tools": [
            "rag_search", "course_evidence", "profile_query",
            "doc_generator", "stats_analyzer",
            "sql_query", "reminder_scheduler",
            "admin.course_list", "admin.material_stats", "admin.user_lookup",
            "admin.risk_summary", "admin.config_get",
            "web.search", "web.fetch",
            "project.search_code", "project.read_file", "project.git_diff",
            "project.search_logs", "project.run_tests", "project.db_schema",
        ],
        "agents": ROLE_ALLOWED_AGENTS["admin"],
        "course_data_scope": "all_courses",
    },
}


def role_capabilities(role: str) -> dict:
    return {"role": role, **ROLE_CAPABILITIES[role]}


def tool_denied_reason(role: str, name: str) -> str | None:
    """按角色判断工具是否可执行;返回拒绝原因,None 表示允许

    决策 #1:可执行边界即角色能力矩阵。矩阵内放开,矩阵外一律拒绝,
    节点直调与 tool_executor 共用本函数,避免绕过。
    """
    if name == "code_executor":
        return "code_executor 不可用:宿主机代码执行已关闭"

    caps = ROLE_CAPABILITIES.get(role)
    if not caps:
        return f"未知角色: {role}"
    if name not in caps["tools"]:
        return f"角色 {role} 无权执行工具: {name}"
    return None
