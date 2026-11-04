"""只读 SQL 分析(P1-3)

安全口径:
- 只能执行单条 SELECT,禁止分号、注释、DDL/DML 与子查询数据源
- 只能引用白名单视图,视图只暴露聚合分析需要的字段
- 强制 LIMIT 上限,MySQL 会话级执行超时
- 视图查询统一按 course_id 收口,越权课程在工具层直接拒绝
"""
import re
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import text

MAX_ROWS = 200
MAX_SQL_CHARS = 4000
QUERY_TIMEOUT_MS = 4000
TABLE_PREVIEW_ROWS = 20

# 白名单视图:每项是一段不含用户输入的固定 SELECT,执行时再包一层课程过滤
VIEWS: dict[str, dict] = {
    "v_assignments": {
        "sql": (
            "SELECT a.id AS assignment_id, a.course_id, a.class_id, a.title, "
            "a.status, a.due_at, a.created_at FROM assignments a"
        ),
        "columns": (
            "assignment_id", "course_id", "class_id", "title",
            "status", "due_at", "created_at",
        ),
    },
    "v_submissions": {
        "sql": (
            "SELECT s.id AS submission_id, s.assignment_id, a.course_id, "
            "a.class_id, s.student_id, s.status, s.score, s.submitted_at "
            "FROM submissions s JOIN assignments a ON a.id = s.assignment_id"
        ),
        "columns": (
            "submission_id", "assignment_id", "course_id", "class_id",
            "student_id", "status", "score", "submitted_at",
        ),
    },
    "v_classes": {
        "sql": (
            "SELECT c.id AS class_id, c.course_id, c.name, c.status, "
            "c.created_at FROM classes c"
        ),
        "columns": ("class_id", "course_id", "name", "status", "created_at"),
    },
    "v_class_members": {
        "sql": (
            "SELECT cm.class_id, c.course_id, cm.student_id, cm.role, cm.status "
            "FROM class_members cm JOIN classes c ON c.id = cm.class_id"
        ),
        "columns": ("class_id", "course_id", "student_id", "role", "status"),
    },
    "v_profiles": {
        "sql": (
            "SELECT sp.course_id, sp.user_id AS student_id, "
            "sp.overall_progress, sp.updated_at FROM student_profiles sp"
        ),
        "columns": ("course_id", "student_id", "overall_progress", "updated_at"),
    },
    "v_mastery": {
        "sql": (
            "SELECT sp.course_id, sp.user_id AS student_id, m.kp_id, "
            "m.mastery_level FROM mastery_records m "
            "JOIN student_profiles sp ON sp.id = m.profile_id"
        ),
        "columns": ("course_id", "student_id", "kp_id", "mastery_level"),
    },
    "v_wrong_questions": {
        "sql": (
            "SELECT sp.course_id, sp.user_id AS student_id, w.kp_id, "
            "w.error_type, w.created_at FROM wrong_questions w "
            "JOIN student_profiles sp ON sp.id = w.profile_id"
        ),
        "columns": ("course_id", "student_id", "kp_id", "error_type", "created_at"),
    },
    "v_review_plans": {
        "sql": (
            "SELECT sp.course_id, sp.user_id AS student_id, r.status, "
            "r.next_review_at FROM review_plans r "
            "JOIN wrong_questions w ON w.id = r.wrong_question_id "
            "JOIN student_profiles sp ON sp.id = w.profile_id"
        ),
        "columns": ("course_id", "student_id", "status", "next_review_at"),
    },
    "v_exam_records": {
        "sql": (
            "SELECT e.course_id, er.exam_id, er.student_id, er.total_score, "
            "er.submitted_at FROM exam_records er JOIN exams e ON e.id = er.exam_id"
        ),
        "columns": ("course_id", "exam_id", "student_id", "total_score", "submitted_at"),
    },
    "v_interview_records": {
        "sql": (
            "SELECT sp.course_id, sp.user_id AS student_id, ir.score, "
            "ir.created_at FROM interview_records ir "
            "JOIN student_profiles sp ON sp.id = ir.profile_id"
        ),
        "columns": ("course_id", "student_id", "score", "created_at"),
    },
}

_BANNED = re.compile(
    r"\b(insert|update|delete|drop|alter|create|truncate|replace|grant|revoke|"
    r"merge|call|exec|execute|attach|detach|pragma|vacuum|load_file|outfile|dumpfile|into)\b",
    re.I,
)
_FROM = re.compile(r"\b(?:from|join)\s+[`\"\[]?([A-Za-z_][\w]*)[`\"\]]?", re.I)
_COMMENT = re.compile(r"(--|/\*|\*/|#)")
_LIMIT = re.compile(r"\blimit\s+(\d+)", re.I)


class SqlSafetyError(ValueError):
    """SQL 未通过安全校验"""


def view_catalog_text() -> str:
    """给模型看的视图目录"""
    return "\n".join(
        f"- {name}({', '.join(spec['columns'])})"
        for name, spec in VIEWS.items()
    )


def extract_sql(raw: str) -> str:
    """从模型输出中提取 SQL,兼容 markdown 代码块与前后说明"""
    value = (raw or "").strip()
    value = re.sub(r"^```[a-zA-Z]*\s*|```$", "", value, flags=re.M).strip()
    index = value.upper().find("SELECT")
    return value[index:].strip() if index >= 0 else value


def validate_sql(sql: str, max_rows: int = MAX_ROWS) -> str:
    """校验并补全 LIMIT;返回可执行 SQL,不通过则抛 SqlSafetyError"""
    value = (sql or "").strip()
    if not value:
        raise SqlSafetyError("SQL 为空")
    if len(value) > MAX_SQL_CHARS:
        raise SqlSafetyError(f"SQL 过长(上限 {MAX_SQL_CHARS} 字符)")
    if ";" in value:
        raise SqlSafetyError("只允许单条语句,禁止分号")
    if _COMMENT.search(value):
        raise SqlSafetyError("禁止 SQL 注释")
    if not re.match(r"^select\b", value, re.I):
        raise SqlSafetyError("只允许 SELECT 查询")
    banned = _BANNED.search(value)
    if banned:
        raise SqlSafetyError(f"禁止关键字: {banned.group(1)}")
    if re.search(r"\bfrom\s*\(", value, re.I):
        raise SqlSafetyError("禁止以子查询作为数据源")

    tables = {name.strip("`\"[]") for name in _FROM.findall(value)}
    unknown = tables - set(VIEWS)
    if unknown:
        raise SqlSafetyError(f"未授权的数据表: {', '.join(sorted(unknown))}")
    if not tables:
        raise SqlSafetyError("查询必须引用白名单视图")

    match = _LIMIT.search(value)
    if match:
        if int(match.group(1)) > max_rows:
            value = _LIMIT.sub(f"LIMIT {max_rows}", value, count=1)
    else:
        value = f"{value} LIMIT {max_rows}"
    return value


def _scoped_sql(sql: str, course_id: int | None) -> str:
    """把白名单视图替换为按课程收口的子查询

    只替换 FROM / JOIN 后的表引用,不能用词替换,否则会破坏
    `v_x.col` 这类列限定。
    """
    scoped = sql
    for name, spec in VIEWS.items():
        inner = spec["sql"]
        if course_id is not None:
            inner = f"{inner} WHERE course_id = :scope_course_id"
        pattern = re.compile(
            rf"\b(from|join)(\s+)[`\"\[]?{name}[`\"\]]?(?!\s*\.)", re.I,
        )

        def _replace(match: re.Match, inner_sql: str = inner, view: str = name) -> str:
            return f"{match.group(1)}{match.group(2)}({inner_sql}) AS {view}"

        scoped = pattern.sub(_replace, scoped)
    return scoped


def _apply_timeout(db) -> None:
    """MySQL 会话级超时;其他方言依赖 LIMIT 与调用方超时控制"""
    try:
        if db.bind is not None and db.bind.dialect.name == "mysql":
            db.execute(text(f"SET SESSION MAX_EXECUTION_TIME={QUERY_TIMEOUT_MS}"))
    except Exception:  # noqa: BLE001
        pass


def _serialize(value):
    if isinstance(value, datetime):
        return value.isoformat(sep=" ", timespec="seconds")
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (bytes, bytearray)):
        return value.decode("utf-8", "ignore")
    return value


def run_query(
    db, sql: str, course_id: int | None = None, max_rows: int = MAX_ROWS,
) -> dict:
    """执行一条已校验的只读查询,返回列名与行数据"""
    safe_sql = validate_sql(sql, max_rows)
    scoped = _scoped_sql(safe_sql, course_id)
    _apply_timeout(db)
    result = db.execute(text(scoped), {
        "scope_course_id": course_id,
        "since_7d": datetime.utcnow() - timedelta(days=7),
        "since_28d": datetime.utcnow() - timedelta(days=28),
    })
    rows = [
        {key: _serialize(value) for key, value in row._mapping.items()}
        for row in result.fetchmany(max_rows)
    ]
    return {"columns": list(result.keys()), "rows": rows, "row_count": len(rows)}


def render_table(result: dict, max_rows: int = TABLE_PREVIEW_ROWS) -> str:
    """把查询结果渲染为 Markdown 表格,注入教师端 prompt"""
    columns = result.get("columns") or []
    rows = result.get("rows") or []
    if not columns:
        return ""
    lines = [
        "| " + " | ".join(str(column) for column in columns) + " |",
        "| " + " | ".join("---" for _ in columns) + " |",
    ]
    for row in rows[:max_rows]:
        lines.append("| " + " | ".join(str(row.get(column, "")) for column in columns) + " |")
    if len(rows) > max_rows:
        lines.append(f"\n（仅展示前 {max_rows} 行，共 {len(rows)} 行）")
    return "\n".join(lines)
