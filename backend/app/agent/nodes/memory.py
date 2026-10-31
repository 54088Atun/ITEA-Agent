"""记忆管理节点:读学情档案快照 / 回写档案更新

数据契约(与 app/models/profile.py 对齐):
- StudentProfile: user_id + course_id 唯一,overall_progress(0-100)
- MasteryRecord: profile_id + kp_id 唯一,mastery_level(0-100 整数)
- WrongQuestion: profile_id,kp_id(可空),question_content,error_type
- ReviewPlan: wrong_question_id,next_review_at,review_count,interval_days,status
- InterviewRecord: profile_id,round,question,answer,score,feedback

快照格式(供 review/interview 节点消费):
- mastery: [{"point": kp名, "level": 0-1浮点}]  ← interview.py 按 level<0.6 判薄弱
- recent_wrong: [{"question": ..., "error_type": ...}]
- pending_reviews: [{"wrong_question_id": ..., "next_review_at": "YYYY-MM-DD"}]
- interview: {"total_sessions": n, "latest_score": n, "latest_weakness": str}
"""
import logging
from datetime import datetime, timedelta

from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.agent.state import AgentState
from app.db.session import SessionLocal
from app.models.profile import (
    StudentProfile, MasteryRecord, WrongQuestion, ReviewPlan,
)
from app.models.course import KnowledgePoint
from app.models.interview import InterviewRecord

logger = logging.getLogger(__name__)

# 遗忘曲线复习间隔(天):1→2→4→7→15→30
FORGETTING_INTERVALS = [1, 2, 4, 7, 15, 30]


# ---------- 内部工具 ----------

def _get_or_create_profile(db: Session, user_id: int, course_id: int | None) -> StudentProfile | None:
    """按 (user_id, course_id) 获取学情档案,不存在则创建"""
    if not course_id:
        return None
    profile = db.execute(
        select(StudentProfile).where(
            StudentProfile.user_id == user_id,
            StudentProfile.course_id == course_id,
        )
    ).scalars().first()
    if not profile:
        profile = StudentProfile(user_id=user_id, course_id=course_id)
        db.add(profile)
        db.flush()  # 取自增 id
        logger.info("学情档案已创建(user=%s, course=%s)", user_id, course_id)
    return profile


def _resolve_kp_id(db: Session, course_id: int | None, kp_name: str) -> int | None:
    """按名称在课程下查找知识点 id(模糊匹配,取第一条)"""
    if not kp_name or not course_id:
        return None
    kp = db.execute(
        select(KnowledgePoint).where(
            KnowledgePoint.course_id == course_id,
            KnowledgePoint.name.like(f"%{kp_name}%"),
        )
    ).scalars().first()
    if not kp:
        logger.warning("知识点未匹配(course=%s, kp=%s)", course_id, kp_name)
    return kp.id if kp else None


def _mastery_to_int(level) -> int:
    """掌握度统一为 0-100 整数(兼容 0-1 浮点输入)"""
    try:
        val = float(level)
    except (TypeError, ValueError):
        return 0
    if val <= 1.0:
        return int(round(val * 100))
    return int(round(min(val, 100)))


# ---------- 读:学情快照 ----------

def _load_mastery_summary(db: Session, profile_id: int) -> list[dict]:
    """掌握度后 5 弱 + 前 5 强,level 归一化为 0-1 浮点"""
    rows = db.execute(
        select(MasteryRecord, KnowledgePoint)
        .join(KnowledgePoint, MasteryRecord.kp_id == KnowledgePoint.id)
        .where(MasteryRecord.profile_id == profile_id)
    ).all()
    if not rows:
        return []
    items = [
        {"point": kp.name, "level": round(rec.mastery_level / 100, 2)}
        for rec, kp in rows
    ]
    items.sort(key=lambda x: x["level"])
    weak = items[:5]
    strong = list(reversed(items[-5:]))
    return weak + strong


def _load_recent_wrong(db: Session, profile_id: int, limit: int = 5) -> list[dict]:
    """最近错题(按创建时间倒序)"""
    rows = db.execute(
        select(WrongQuestion)
        .where(WrongQuestion.profile_id == profile_id)
        .order_by(WrongQuestion.created_at.desc())
        .limit(limit)
    ).scalars().all()
    return [
        {
            "question": (r.question_content or "")[:80],
            "error_type": r.error_type,
        }
        for r in rows
    ]


def _load_pending_reviews(db: Session, profile_id: int) -> list[dict]:
    """已到期待复习计划(最多 5 条)"""
    rows = db.execute(
        select(ReviewPlan)
        .join(WrongQuestion, ReviewPlan.wrong_question_id == WrongQuestion.id)
        .where(
            WrongQuestion.profile_id == profile_id,
            ReviewPlan.status == "pending",
            ReviewPlan.next_review_at <= datetime.utcnow(),
        )
        .order_by(ReviewPlan.next_review_at)
        .limit(5)
    ).scalars().all()
    return [
        {
            "wrong_question_id": r.wrong_question_id,
            "next_review_at": r.next_review_at.strftime("%Y-%m-%d"),
        }
        for r in rows
    ]


def _load_interview_summary(db: Session, profile_id: int) -> dict:
    """面试记录摘要:总轮次 + 最近一次评分/薄弱点"""
    total = db.execute(
        select(func.count(InterviewRecord.id))
        .where(InterviewRecord.profile_id == profile_id)
    ).scalar() or 0
    if not total:
        return {}
    latest = db.execute(
        select(InterviewRecord)
        .where(InterviewRecord.profile_id == profile_id)
        .order_by(InterviewRecord.created_at.desc())
        .limit(1)
    ).scalars().first()
    return {
        "total_sessions": total,
        "latest_score": latest.score if latest else None,
        "latest_weakness": (latest.feedback or "")[:100] if latest else "",
    }


def memory_load_node(state: AgentState) -> dict:
    """读取学情档案快照,注入 profile_snapshot"""
    user_id = state["user_id"]
    role = state.get("user_role", "student")
    course_id = state.get("course_id")

    if role != "student" or not course_id:
        return {"profile_snapshot": {}}

    snapshot: dict = {}
    db = SessionLocal()
    try:
        profile = db.execute(
            select(StudentProfile).where(
                StudentProfile.user_id == user_id,
                StudentProfile.course_id == course_id,
            )
        ).scalars().first()
        if profile:
            snapshot["overall_progress"] = float(profile.overall_progress or 0)
            snapshot["mastery"] = _load_mastery_summary(db, profile.id)
            snapshot["recent_wrong"] = _load_recent_wrong(db, profile.id)
            snapshot["pending_reviews"] = _load_pending_reviews(db, profile.id)
            snapshot["interview"] = _load_interview_summary(db, profile.id)
    except Exception as e:
        logger.warning("学情快照读取失败(user=%s): %s", user_id, e)
    finally:
        db.close()

    logger.info("学情快照已加载(user=%s, keys=%s)", user_id, list(snapshot.keys()))
    return {"profile_snapshot": snapshot}


# ---------- 写:档案回写 ----------

def memory_write_node(state: AgentState) -> dict:
    """将 profile_updates 回写数据库(错题/掌握度/复习计划/面试)"""
    updates = state.get("profile_updates") or {}
    user_id = state["user_id"]
    course_id = state.get("course_id")
    if not updates or not course_id:
        return {"profile_updates": {}}

    db = SessionLocal()
    written: list[str] = []
    try:
        profile = _get_or_create_profile(db, user_id, course_id)
        if not profile:
            return {"profile_updates": {}}

        # 1. 错题录入 + 自动生成首轮复习计划(遗忘曲线)
        for wq in updates.get("wrong_questions", []):
            kp_id = _resolve_kp_id(db, course_id, wq.get("knowledge_point", ""))
            new_wq = WrongQuestion(
                profile_id=profile.id,
                kp_id=kp_id,  # 未匹配到知识点时为 None(字段可空)
                question_content=wq.get("question_summary", "")[:2000],
                error_type=wq.get("error_type", "概念不清"),
            )
            db.add(new_wq)
            db.flush()
            db.add(ReviewPlan(
                wrong_question_id=new_wq.id,
                next_review_at=datetime.utcnow() + timedelta(days=FORGETTING_INTERVALS[0]),
                review_count=0,
                interval_days=FORGETTING_INTERVALS[0],
                status="pending",
            ))
            written.append("wrong_question")

        # 2. 掌握度更新(upsert)
        for m in updates.get("mastery_updates", []):
            kp_id = _resolve_kp_id(db, course_id, m.get("knowledge_point", ""))
            if not kp_id:
                continue  # 掌握度必须绑定知识点,未匹配则跳过
            existing = db.execute(
                select(MasteryRecord).where(
                    MasteryRecord.profile_id == profile.id,
                    MasteryRecord.kp_id == kp_id,
                )
            ).scalars().first()
            level = _mastery_to_int(m.get("mastery_level", 0))
            if existing:
                existing.mastery_level = level
                existing.last_assessed_at = datetime.utcnow()
            else:
                db.add(MasteryRecord(
                    profile_id=profile.id,
                    kp_id=kp_id,
                    mastery_level=level,
                ))
            written.append("mastery")

        # 3. 显式复习计划(带 wrong_question_id 时追加;None 已在错题录入时自动生成)
        for rp in updates.get("review_plans", []):
            wq_id = rp.get("wrong_question_id")
            if not wq_id:
                continue
            db.add(ReviewPlan(
                wrong_question_id=wq_id,
                next_review_at=datetime.utcnow() + timedelta(days=FORGETTING_INTERVALS[0]),
                review_count=0,
                interval_days=FORGETTING_INTERVALS[0],
                status="pending",
            ))
            written.append("review_plan")

        # 4. 面试记录(round 自增,question 存对话历史)
        for iv in updates.get("interview_records", []):
            round_num = db.execute(
                select(func.count(InterviewRecord.id))
                .where(InterviewRecord.profile_id == profile.id)
            ).scalar() or 0
            db.add(InterviewRecord(
                profile_id=profile.id,
                round=round_num + 1,
                question=iv.get("question_history", "") or "模拟面试记录",
                answer="",
                score=iv.get("overall_score"),
                feedback=iv.get("weakness_summary", ""),
            ))
            written.append("interview")

        db.commit()
        logger.info("档案回写完成(user=%s, items=%s)", user_id, written)
    except Exception as e:
        db.rollback()
        logger.error("档案回写失败(user=%s): %s", user_id, e)
    finally:
        db.close()

    return {"profile_updates": {}}