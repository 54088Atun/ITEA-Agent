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
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.agent.state import AgentState
from app.core.time import normalize_seconds, utcnow
from app.db.session import SessionLocal
from app.models.profile import (
    StudentProfile, MasteryRecord, WrongQuestion, ReviewPlan,
)
from app.models.course import KnowledgePoint
from app.models.interview import InterviewRecord
from app.services.prompt_guard import scan_untrusted
from app.services import agent_memory as mem_svc

logger = logging.getLogger(__name__)

# 遗忘曲线复习间隔(天):1→2→4→7→15→30
FORGETTING_INTERVALS = [1, 2, 4, 7, 15, 30]

# 情景记忆保留 90 天、语义偏好保留 365 天(写入时带 TTL)
EPISODIC_TTL_DAYS = 90
SEMANTIC_TTL_DAYS = 365

# 用户显式表达偏好的触发词:命中才写语义记忆
PREFERENCE_HINTS = ("记住", "以后都", "我的偏好", "我喜欢", "我习惯")

# 单轮回写条数上限:避免一次对话批量污染学情档案
MAX_ITEMS_PER_TURN = {
    "wrong_questions": 5,
    "mastery_updates": 10,
    "review_plans": 5,
    "interview_records": 1,
}


def _safe_memory_text(value, limit: int) -> str:
    """记忆内容按不可信数据处理:命中指令覆盖等高危项则放弃该条"""
    scanned = scan_untrusted(str(value or ""))
    if scanned["blocked"]:
        logger.warning("记忆写入被拦截(labels=%s)", ",".join(scanned["labels"]))
        return ""
    return scanned["sanitized"][:limit]


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


def _normalize_review_at(value: datetime) -> datetime:
    """复习时间统一到秒精度,与 MySQL DATETIME(0) 保持一致"""
    return normalize_seconds(value)


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
            ReviewPlan.next_review_at <= utcnow(),
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


def load_profile_snapshot(
    user_id: int, course_id: int | None, role: str = "student",
) -> dict:
    """按需读取学情快照(供 Agent 运行时直接调用,不再由 prepare 预加载)"""
    if role != "student" or not course_id:
        return {}

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

        # 三层记忆:跨会话情景记忆(带来源会话)与语义偏好,服务层内部已兜底
        episodic = mem_svc.list_recent_episodic(
            user_id, course_id, days=mem_svc.DEFAULT_RECALL_DAYS, limit=5,
        )
        if episodic:
            snapshot["episodic_memories"] = episodic
        semantic = mem_svc.search_memory(
            user_id, course_id, query="", memory_type="semantic", limit=3,
        )
        if semantic:
            snapshot["semantic_memories"] = semantic
    except Exception as e:
        logger.warning("学情快照读取失败(user=%s): %s", user_id, e)
    finally:
        db.close()

    logger.info("学情数据已读取(user=%s, keys=%s)", user_id, list(snapshot.keys()))
    return snapshot


# 说明:不再提供 memory_load 图节点。个性化入口(tutor/review/interview/collab)
# 在运行时通过 app.agent.data_api.fetch_profile 读取学情,避免预加载死数据;
# load_profile_snapshot 保留给离线评估/诊断等直接调用场景。


# ---------- 写:档案回写 ----------

def _latest_user_text(state: AgentState, limit: int = 300) -> str:
    """取本轮用户原话(倒序找最后一条 user 消息)"""
    for message in reversed(state.get("messages") or []):
        if isinstance(message, dict) and message.get("role") == "user":
            return str(message.get("content") or "").strip()[:limit]
    return ""


def _episodic_summary(updates: dict, state: AgentState) -> tuple[str, int]:
    """把本轮学情更新压缩成一句情景记忆摘要,并给出重要度"""
    parts: list[str] = []
    for m in (updates.get("mastery_updates") or [])[:5]:
        point = str(m.get("knowledge_point") or "").strip()
        if point:
            parts.append(f"掌握度更新:{point}")
    for wq in (updates.get("wrong_questions") or [])[:5]:
        point = str(wq.get("knowledge_point") or "").strip()
        question = str(wq.get("question_summary") or "").strip()[:60]
        if point or question:
            parts.append(f"错题:{point or question}")
    interviews = updates.get("interview_records") or []
    for iv in interviews[:1]:
        weakness = str(iv.get("weakness_summary") or iv.get("feedback") or "").strip()[:60]
        score = iv.get("overall_score")
        detail = weakness or (f"评分{score}" if score is not None else "")
        if detail:
            parts.append(f"模拟面试:{detail}")
    if not parts:
        return "", 1
    summary = "；".join(parts)[: mem_svc.MAX_SUMMARY_CHARS]
    importance = 3 if (updates.get("wrong_questions") or interviews) else 2
    return summary, importance


def _write_agent_memories(
    user_id: int, course_id: int | None, updates: dict, state: AgentState,
) -> None:
    """写情景/语义记忆:user 级,无 course_id 也可写;失败静默降级不影响主流程"""
    session_id = str(state.get("session_id") or "").strip()
    if not session_id:
        return

    summary, importance = _episodic_summary(updates, state)
    if summary:
        try:
            mem_svc.write_memory(
                user_id=user_id,
                course_id=course_id,
                memory_type="episodic",
                content=summary,
                source_type="conversation",
                source_id=session_id,
                session_id=session_id,
                summary=summary,
                ttl_days=EPISODIC_TTL_DAYS,
                importance=importance,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("情景记忆写入跳过(user=%s): %s", user_id, exc)

    utterance = _latest_user_text(state)
    if utterance and any(hint in utterance for hint in PREFERENCE_HINTS):
        try:
            mem_svc.write_memory(
                user_id=user_id,
                course_id=course_id,
                memory_type="semantic",
                content=utterance,
                source_type="conversation",
                source_id=session_id,
                session_id=session_id,
                summary=utterance[: mem_svc.MAX_SUMMARY_CHARS],
                ttl_days=SEMANTIC_TTL_DAYS,
                importance=4,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("语义记忆写入跳过(user=%s): %s", user_id, exc)


def memory_write_node(state: AgentState) -> dict:
    """回写学情档案,并沉淀情景/语义记忆"""
    updates = state.get("profile_updates") or {}
    user_id = state["user_id"]
    course_id = state.get("course_id")

    # 三层记忆:情景/语义记忆为 user 级,无课程也能写(带来源会话与 TTL)
    _write_agent_memories(user_id, course_id, updates, state)

    if not updates:
        return {"profile_updates": {}, "profile_write_result": {
            "written": [], "skipped_review_plans": [], "reason": "no_updates",
        }}
    if not course_id:
        return {"profile_updates": {}, "profile_write_result": {
            "written": [], "skipped_review_plans": [], "reason": "missing_course_id",
        }}

    db = SessionLocal()
    written: list[str] = []
    # 同轮新错题 id:显式计划若指向这些错题,说明首轮复习计划已自动生成
    new_wq_ids: set[int] = set()
    skipped_review_plans: list[dict] = []
    try:
        profile = _get_or_create_profile(db, user_id, course_id)
        if not profile:
            return {"profile_updates": {}, "profile_write_result": {
                "written": [], "skipped_review_plans": [], "reason": "profile_unavailable",
            }}

        # 1. 错题录入 + 自动生成首轮复习计划(遗忘曲线)
        for wq in (updates.get("wrong_questions") or [])[:MAX_ITEMS_PER_TURN["wrong_questions"]]:
            content = _safe_memory_text(wq.get("question_summary"), 2000)
            if not content:
                continue
            kp_id = _resolve_kp_id(db, course_id, wq.get("knowledge_point", ""))
            new_wq = WrongQuestion(
                profile_id=profile.id,
                kp_id=kp_id,  # 未匹配到知识点时为 None(字段可空)
                question_content=content,
                error_type=_safe_memory_text(wq.get("error_type") or "概念不清", 50),
            )
            db.add(new_wq)
            db.flush()
            new_wq_ids.add(new_wq.id)
            db.add(ReviewPlan(
                wrong_question_id=new_wq.id,
                next_review_at=_normalize_review_at(
                    utcnow() + timedelta(days=FORGETTING_INTERVALS[0])
                ),
                review_count=0,
                interval_days=FORGETTING_INTERVALS[0],
                status="pending",
            ))
            written.append("wrong_question")

        # 2. 掌握度更新(upsert)
        for m in (updates.get("mastery_updates") or [])[:MAX_ITEMS_PER_TURN["mastery_updates"]]:
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
                existing.last_assessed_at = utcnow()
            else:
                db.add(MasteryRecord(
                    profile_id=profile.id,
                    kp_id=kp_id,
                    mastery_level=level,
                ))
            written.append("mastery")

        # 3. 显式复习计划:只能绑定当前 profile 的有效错题;None 不重复建计划
        for rp in (updates.get("review_plans") or [])[:MAX_ITEMS_PER_TURN["review_plans"]]:
            raw_id = rp.get("wrong_question_id")
            if raw_id is None or raw_id == "":
                # review.py 默认输出 None,首轮计划已随错题录入自动生成
                skipped_review_plans.append({
                    "wrong_question_id": None,
                    "reason": "missing_wrong_question_id",
                })
                continue
            try:
                wq_id = int(raw_id)
            except (TypeError, ValueError):
                skipped_review_plans.append({
                    "wrong_question_id": str(raw_id),
                    "reason": "invalid_wrong_question_id",
                })
                continue
            if wq_id in new_wq_ids:
                skipped_review_plans.append({
                    "wrong_question_id": wq_id,
                    "reason": "same_turn_auto_plan_satisfied",
                })
                continue
            owned = db.execute(
                select(WrongQuestion.id).where(
                    WrongQuestion.id == wq_id,
                    WrongQuestion.profile_id == profile.id,
                )
            ).scalars().first()
            if not owned:
                skipped_review_plans.append({
                    "wrong_question_id": wq_id,
                    "reason": "wrong_question_not_found_or_foreign",
                })
                continue
            existing_plan = db.execute(
                select(ReviewPlan.id).where(
                    ReviewPlan.wrong_question_id == wq_id,
                    ReviewPlan.status == "pending",
                )
            ).scalars().first()
            if existing_plan:
                # 重试同一请求时不重复插入
                skipped_review_plans.append({
                    "wrong_question_id": wq_id,
                    "reason": "existing_pending_plan",
                })
                continue
            next_review_at = _normalize_review_at(
                utcnow() + timedelta(days=FORGETTING_INTERVALS[0])
            )
            try:
                # 唯一约束 (wrong_question_id, next_review_at) 兜底并发重复写入
                with db.begin_nested():
                    db.add(ReviewPlan(
                        wrong_question_id=wq_id,
                        next_review_at=next_review_at,
                        review_count=0,
                        interval_days=FORGETTING_INTERVALS[0],
                        status="pending",
                    ))
            except IntegrityError:
                existing_id = db.execute(
                    select(ReviewPlan.id).where(
                        ReviewPlan.wrong_question_id == wq_id,
                        ReviewPlan.next_review_at == next_review_at,
                    )
                ).scalars().first()
                skipped_review_plans.append({
                    "wrong_question_id": wq_id,
                    "reason": "existing_plan_conflict",
                    "existing_plan_id": existing_id,
                })
            else:
                written.append("review_plan")

        # 4. 面试记录(round 自增,question 存对话历史)
        for iv in (updates.get("interview_records") or [])[:MAX_ITEMS_PER_TURN["interview_records"]]:
            round_num = db.execute(
                select(func.count(InterviewRecord.id))
                .where(InterviewRecord.profile_id == profile.id)
            ).scalar() or 0
            assignment_id = iv.get("assignment_id", state.get("interview_assignment_id"))
            feedback = _safe_memory_text(
                iv.get("feedback") or iv.get("weakness_summary"), 2000,
            )
            db.add(InterviewRecord(
                profile_id=profile.id,
                assignment_id=assignment_id,
                round=round_num + 1,
                question=_safe_memory_text(
                    iv.get("question_history") or "模拟面试记录", 4000,
                ),
                answer="",
                score=iv.get("overall_score"),
                score_dimensions=iv.get("score_dimensions"),
                feedback=feedback,
                visibility="teacher" if assignment_id is not None else "private",
            ))
            written.append("interview")

        db.commit()
        logger.info("档案回写完成(user=%s, items=%s)", user_id, written)
        if skipped_review_plans:
            logger.info(
                "显式复习计划未写入(user=%s, reasons=%s)",
                user_id,
                [item["reason"] for item in skipped_review_plans],
            )
    except Exception as e:
        db.rollback()
        logger.error("档案回写失败(user=%s): %s", user_id, e)
    finally:
        db.close()

    return {"profile_updates": {}, "profile_write_result": {
        "written": written,
        "skipped_review_plans": skipped_review_plans,
    }}