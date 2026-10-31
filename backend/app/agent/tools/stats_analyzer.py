"""stats_analyzer:学情统计聚合

实现要点:
- 聚合 mastery_records 与 wrong_questions(经 student_profiles 关联课程)
- 输出班级薄弱知识点 TOP-N 及分布
- 支持三种 metric:weakness/progress/distribution
- mastery_level 为 0-100 整数,分布阈值 80/60/40
"""
import logging
from datetime import datetime, timedelta

from sqlalchemy import select, func

from app.db.session import SessionLocal
from app.models.profile import MasteryRecord, WrongQuestion, ReviewPlan, StudentProfile
from app.models.course import KnowledgePoint
from app.models.practice import PracticeRecord

logger = logging.getLogger(__name__)


def _analyze_weakness(course_id: int, top_n: int = 10) -> dict:
    """班级薄弱知识点 TOP-N"""
    db = SessionLocal()
    try:
        # 按知识点聚合平均掌握度(profile→课程过滤,kp→取知识点名)
        rows = db.execute(
            select(
                KnowledgePoint.name,
                func.avg(MasteryRecord.mastery_level).label("avg_mastery"),
                func.count(MasteryRecord.id).label("student_count"),
            )
            .join(StudentProfile, MasteryRecord.profile_id == StudentProfile.id)
            .join(KnowledgePoint, MasteryRecord.kp_id == KnowledgePoint.id)
            .where(StudentProfile.course_id == course_id)
            .group_by(KnowledgePoint.name)
            .order_by(func.avg(MasteryRecord.mastery_level).asc())
            .limit(top_n)
        ).all()

        weak_points = [
            {
                "point": r.name,
                "avg_mastery": round(float(r.avg_mastery), 2),
                "student_count": r.student_count,
            }
            for r in rows
        ]

        # 错题类型分布
        error_rows = db.execute(
            select(
                WrongQuestion.error_type,
                func.count(WrongQuestion.id).label("cnt"),
            )
            .join(StudentProfile, WrongQuestion.profile_id == StudentProfile.id)
            .where(StudentProfile.course_id == course_id)
            .group_by(WrongQuestion.error_type)
        ).all()
        error_distribution = {r.error_type: r.cnt for r in error_rows}

        return {
            "weak_points": weak_points,
            "error_distribution": error_distribution,
        }
    finally:
        db.close()


def _analyze_progress(course_id: int, days: int = 30) -> dict:
    """学习进度趋势(近 N 天练习量与掌握度变化)"""
    db = SessionLocal()
    try:
        since = datetime.utcnow() - timedelta(days=days)

        # 每日练习量
        practice_rows = db.execute(
            select(
                func.date(PracticeRecord.created_at).label("day"),
                func.count(PracticeRecord.id).label("cnt"),
            )
            .join(StudentProfile, PracticeRecord.profile_id == StudentProfile.id)
            .where(
                StudentProfile.course_id == course_id,
                PracticeRecord.created_at >= since,
            )
            .group_by(func.date(PracticeRecord.created_at))
            .order_by(func.date(PracticeRecord.created_at))
        ).all()
        daily_practice = [
            {"date": str(r.day), "count": r.cnt} for r in practice_rows
        ]

        # 掌握度均值
        avg_row = db.execute(
            select(func.avg(MasteryRecord.mastery_level))
            .join(StudentProfile, MasteryRecord.profile_id == StudentProfile.id)
            .where(StudentProfile.course_id == course_id)
        ).scalar()
        avg_mastery = round(float(avg_row), 2) if avg_row else 0

        # 待复习人数(复习计划→错题→档案→用户)
        pending = db.execute(
            select(func.count(func.distinct(StudentProfile.user_id)))
            .select_from(ReviewPlan)
            .join(WrongQuestion, ReviewPlan.wrong_question_id == WrongQuestion.id)
            .join(StudentProfile, WrongQuestion.profile_id == StudentProfile.id)
            .where(
                StudentProfile.course_id == course_id,
                ReviewPlan.status == "pending",
            )
        ).scalar() or 0

        return {
            "daily_practice": daily_practice,
            "avg_mastery": avg_mastery,
            "pending_review_students": pending,
        }
    finally:
        db.close()


def _analyze_distribution(course_id: int) -> dict:
    """学生掌握度分布(优秀/良好/及格/薄弱)"""
    db = SessionLocal()
    try:
        rows = db.execute(
            select(
                StudentProfile.user_id,
                func.avg(MasteryRecord.mastery_level).label("avg"),
            )
            .join(StudentProfile, MasteryRecord.profile_id == StudentProfile.id)
            .where(StudentProfile.course_id == course_id)
            .group_by(StudentProfile.user_id)
        ).all()

        buckets = {"优秀(≥80)": 0, "良好(60-80)": 0, "及格(40-60)": 0, "薄弱(<40)": 0}
        for r in rows:
            avg = float(r.avg)
            if avg >= 80:
                buckets["优秀(≥80)"] += 1
            elif avg >= 60:
                buckets["良好(60-80)"] += 1
            elif avg >= 40:
                buckets["及格(40-60)"] += 1
            else:
                buckets["薄弱(<40)"] += 1

        return {"distribution": buckets, "total_students": len(rows)}
    finally:
        db.close()


def stats_analyzer(
    course_id: int,
    metric: str = "weakness",
    top_n: int = 10,
) -> dict:
    """学情统计工具

    Args:
        course_id: 课程 ID
        metric: 统计维度(weakness/progress/distribution)
        top_n: TOP-N 条数

    Returns:
        统计结果 JSON
    """
    analyzers = {
        "weakness": lambda: _analyze_weakness(course_id, top_n),
        "progress": lambda: _analyze_progress(course_id),
        "distribution": lambda: _analyze_distribution(course_id),
    }
    analyzer = analyzers.get(metric)
    if not analyzer:
        return {"error": f"不支持的统计维度: {metric}"}

    try:
        result = analyzer()
        result["metric"] = metric
        result["course_id"] = course_id
        logger.info("学情统计完成(course=%s, metric=%s)", course_id, metric)
        return result
    except Exception as e:
        logger.error("学情统计失败(course=%s, metric=%s): %s", course_id, metric, e)
        return {"error": str(e)}