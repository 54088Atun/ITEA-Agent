"""项目内部 API 客户端

Agent 运行时通过复用项目内已有的路由层函数读取数据,而不是直接查询业务表。
选择直接调用路由函数而非 HTTP 自调用,避免单进程 uvicorn 下的自请求死锁,
同时保留路由层已有的权限校验与响应组装逻辑。
"""
import logging

from app.db.session import SessionLocal
from app.models.user import User

logger = logging.getLogger(__name__)


def _load_user(db, user_id: int) -> User | None:
    return db.query(User).filter(User.id == user_id).first()


def fetch_profile_via_api(
    user_id: int, course_id: int | None, role: str = "student",
) -> dict:
    """复用学生端 API:进度、错题、复习计划、面试记录"""
    if role != "student" or not course_id:
        return {}

    db = SessionLocal()
    try:
        from app.api.student import (
            get_progress_by_path,
            list_interview_records,
            list_review_plans,
            list_wrong_questions,
        )

        user = _load_user(db, user_id)
        if not user:
            return {}

        progress = get_progress_by_path(course_id, user, db)
        wrongs = list_wrong_questions(course_id=course_id, limit=5, student=user, db=db)
        reviews = list_review_plans(
            course_id=course_id, status="pending", student=user, db=db,
        )
        records = list_interview_records(course_id=course_id, student=user, db=db)

        snapshot = {
            "overall_progress": float(progress.overall_progress or 0),
            "mastery": [
                {
                    "point": item.kp_name,
                    "level": round(max(0.0, min(1.0, (item.mastery_level or 0) / 100)), 2),
                }
                for item in progress.mastery
            ],
            "recent_wrong": [
                {
                    "question": (item.question_content or "")[:80],
                    "error_type": item.error_type,
                }
                for item in wrongs
            ],
            "pending_reviews": [
                {
                    "wrong_question_id": item.wrong_question_id,
                    "next_review_at": (
                        item.next_review_at.strftime("%Y-%m-%d")
                        if item.next_review_at else ""
                    ),
                }
                for item in reviews
            ],
        }
        if records:
            latest = records[-1]
            snapshot["interview"] = {
                "total_sessions": len(records),
                "latest_score": latest.score,
                "latest_weakness": (latest.feedback or "")[:100],
            }
        return snapshot
    except Exception as exc:  # noqa: BLE001
        logger.warning("内部 API 学情读取失败(user=%s, course=%s): %s", user_id, course_id, exc)
        return {}
    finally:
        db.close()


def fetch_course_evidence_via_api(
    query: str, course_id: int | None, user_id: int,
    role: str = "student", top_k: int = 5,
) -> dict:
    """复用课程检索内部接口,返回上下文与片段元数据(素材 ID/页码,供来源定位)"""
    if not query or not course_id:
        return {}

    db = SessionLocal()
    try:
        from app.api.course import search_course_materials

        user = _load_user(db, user_id)
        if not user:
            return {}
        result = search_course_materials(
            course_id, q=query, top_k=top_k, user=user, db=db,
        )
        return {
            "course_id": result.get("course_id") or course_id,
            "context": result.get("context", "") or "",
            "fragments": result.get("fragments", []) or [],
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("内部 API 课程检索失败(course=%s): %s", course_id, exc)
        return {}
    finally:
        db.close()


def fetch_course_context_via_api(
    query: str, course_id: int | None, user_id: int,
    role: str = "student", top_k: int = 5,
) -> str:
    """复用课程检索内部接口,仅返回拼接上下文"""
    return fetch_course_evidence_via_api(
        query, course_id, user_id, role, top_k,
    ).get("context", "")


def fetch_syllabus_via_api(
    course_id: int | None, user_id: int, role: str = "teacher",
) -> str:
    """复用课程检索内部接口获取大纲"""
    if not course_id:
        return "(暂无课程大纲,请教师上传教学大纲后使用)"
    context = fetch_course_context_via_api(
        "教学大纲 课程目标 章节安排", course_id, user_id, role, top_k=5,
    )
    return context or "(暂无课程大纲,请教师上传教学大纲后使用)"


def fetch_class_stats_via_api(
    course_id: int | None, user_id: int, role: str = "teacher",
    metric: str = "weakness", top_n: int = 10,
) -> dict:
    """复用班级 API:找到课程对应班级后读取班级统计"""
    if not course_id or role not in ("teacher", "admin"):
        return {}

    db = SessionLocal()
    try:
        from app.api.classroom import get_class_report, list_classes

        user = _load_user(db, user_id)
        if not user:
            return {}
        classes = list_classes(user, db)
        target = next((item for item in classes if item.course_id == course_id), None)
        if not target:
            return {}
        stats = get_class_report(target.id, user, db)
        return stats.model_dump() if hasattr(stats, "model_dump") else stats
    except Exception as exc:  # noqa: BLE001
        logger.warning("内部 API 班级统计失败(course=%s): %s", course_id, exc)
        return {}
    finally:
        db.close()
