"""sql_query 工具:在只读白名单视图上执行教师/管理员的分析查询"""
import logging

from app.db.session import SessionLocal
from app.services.course_access import agent_course_scope_error
from app.services.sql_analytics import SqlSafetyError, run_query

logger = logging.getLogger(__name__)


def sql_query(
    sql: str, course_id: int | None = None, user_id: int | None = None,
) -> dict:
    """执行单条 SELECT;越权课程与不安全 SQL 统一返回 error"""
    if not sql or not str(sql).strip():
        return {"error": "缺少 SQL 语句"}
    if course_id is not None:
        denial = agent_course_scope_error(user_id, course_id)
        if denial:
            return {"error": denial}

    db = SessionLocal()
    try:
        result = run_query(db, sql, course_id)
        return {"ok": True, "sql": sql, **result}
    except SqlSafetyError as exc:
        logger.warning("SQL 校验未通过: %s", exc)
        return {"error": f"SQL 校验未通过: {exc}"}
    except Exception as exc:  # noqa: BLE001
        logger.warning("SQL 执行失败: %s", exc)
        return {"error": f"SQL 执行失败: {exc}"}
    finally:
        db.close()
