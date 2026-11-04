"""未截止作业/考试答案保护(AS-10,决策 12)

口径(2026-10-31 拍板):
- 学生提问命中未截止作业/考试题干,或显式索要作业/考试答案 → 交 risk_guard 拦截转引导
- 学生已提交但未截止仍拦截;截止/关闭后才放行(与接口层“截止后下发参考答案”一致)
- 判定为确定性规则,先于模型风控执行,命中写风险日志
"""
import logging
import re
from datetime import datetime

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.models.assignment import Assignment
from app.models.classroom import Classroom, ClassMember
from app.models.exam import Exam, ExamQuestion
from app.models.question import Question
from app.models.user import User
from app.services.course_access import visible_course_ids

logger = logging.getLogger(__name__)

RISK_TYPE = "未截止作业答案保护"
# 题干/要求与提问的最短公共片段:中文 16 字以上基本可判定为同一道题
MIN_MATCH_CHARS = 16
MAX_ASSIGNMENTS = 50
MAX_EXAMS = 20
MAX_QUESTIONS = 200

EXPLICIT_PATTERNS = (
    re.compile(
        r"(作业|考试|试卷|测验|这套题|这份题)[^。！？!?\n]{0,12}"
        r"(答案|解答|怎么做|怎么答|帮我做|帮我写|选什么|选哪个)"
    ),
    re.compile(r"第\s*\d+\s*题[^。！？!?\n]{0,8}(答案|怎么|选什么|选哪个|解答)"),
    re.compile(r"(标准答案|正确答案|参考答案)"),
)


def _normalize(text: str) -> str:
    """去空白与标点并转小写,降低粘贴格式差异"""
    return re.sub(r"[\W_]+", "", (text or "").lower())


def _matches(message_norm: str, candidate_norm: str) -> bool:
    """题干与提问存在足够长的公共片段即视为命中"""
    if len(candidate_norm) < MIN_MATCH_CHARS or len(message_norm) < MIN_MATCH_CHARS:
        return False
    if candidate_norm in message_norm or message_norm in candidate_norm:
        return True
    return any(
        candidate_norm[i:i + MIN_MATCH_CHARS] in message_norm
        for i in range(len(candidate_norm) - MIN_MATCH_CHARS + 1)
    )


def _visible_class_ids(db: Session, student_id: int) -> list[int]:
    return [
        cid for (cid,) in db.query(ClassMember.class_id).filter(
            ClassMember.student_id == student_id,
            ClassMember.status == "active",
        ).all()
    ]


def _active_assignments(
    db: Session, course_ids: list[int], class_ids: list[int],
) -> list[Assignment]:
    """未截止且已发布、对学生可见的作业/考试(共用 assignments 表)"""
    conds = []
    if class_ids:
        conds.append(Assignment.class_id.in_(class_ids))
    if course_ids:
        conds.append(and_(
            Assignment.class_id.is_(None),
            Assignment.course_id.in_(course_ids),
        ))
    if not conds:
        return []
    now = datetime.utcnow()
    return (
        db.query(Assignment)
        .filter(
            Assignment.status == "published",
            or_(Assignment.due_at.is_(None), Assignment.due_at > now),
            or_(*conds),
        )
        .order_by(Assignment.id.desc())
        .limit(MAX_ASSIGNMENTS)
        .all()
    )


def _active_exams(
    db: Session, course_ids: list[int], class_ids: list[int],
) -> list[Exam]:
    """未截止且已发布、对学生可见的在线考试"""
    if not course_ids:
        return []
    now = datetime.utcnow()
    return (
        db.query(Exam)
        .filter(
            Exam.status == "published",
            or_(Exam.due_at.is_(None), Exam.due_at > now),
            Exam.course_id.in_(course_ids),
            or_(Exam.class_id.is_(None), Exam.class_id.in_(class_ids or [0])),
        )
        .order_by(Exam.id.desc())
        .limit(MAX_EXAMS)
        .all()
    )


def _exam_stems(db: Session, exam_ids: list[int]) -> dict[int, list[str]]:
    rows = (
        db.query(ExamQuestion.exam_id, Question.stem)
        .join(Question, Question.id == ExamQuestion.question_id)
        .filter(ExamQuestion.exam_id.in_(exam_ids))
        .limit(MAX_QUESTIONS)
        .all()
    )
    grouped: dict[int, list[str]] = {}
    for exam_id, stem in rows:
        grouped.setdefault(exam_id, []).append(stem or "")
    return grouped


def _hit(kind: str, row_id: int, title: str, reason: str) -> dict:
    return {
        "risk_type": RISK_TYPE,
        "kind": kind,
        "id": row_id,
        "title": title or "",
        "reason": reason,
    }


def check_answer_protection(
    db: Session, user: User, message: str, course_id: int | None = None,
) -> dict | None:
    """判定是否需要拦截:返回命中信息,未命中返回 None"""
    if getattr(user, "role", "") != "student":
        return None
    message_norm = _normalize(message)
    if not message_norm:
        return None

    course_ids = visible_course_ids(user, db)
    if course_id:
        if course_id not in course_ids:
            return None
        course_ids = [course_id]

    class_ids = _visible_class_ids(db, user.id)
    if course_id and class_ids:
        class_ids = [
            cid for (cid,) in db.query(Classroom.id).filter(
                Classroom.id.in_(class_ids),
                Classroom.course_id == course_id,
            ).all()
        ]

    assignments = _active_assignments(db, course_ids, class_ids)
    exams = _active_exams(db, course_ids, class_ids)
    if not assignments and not exams:
        return None

    for row in assignments:
        if _matches(message_norm, _normalize(row.description)):
            kind = "考试" if (row.kind or "") == "exam" else "作业"
            return _hit(kind, row.id, row.title, f"命中未截止{kind}题干")

    stems = _exam_stems(db, [exam.id for exam in exams]) if exams else {}
    for exam in exams:
        for stem in stems.get(exam.id, []):
            if _matches(message_norm, _normalize(stem)):
                return _hit("考试", exam.id, exam.title, "命中未截止考试题干")

    if any(pattern.search(message) for pattern in EXPLICIT_PATTERNS):
        if assignments:
            row = assignments[0]
            kind = "考试" if (row.kind or "") == "exam" else "作业"
            return _hit(kind, row.id, row.title, f"显式索要未截止{kind}答案")
        exam = exams[0]
        return _hit("考试", exam.id, exam.title, "显式索要未截止考试答案")
    return None


def check_answer_request(
    user_id: int, user_role: str, message: str, course_id: int | None = None,
) -> dict | None:
    """Agent 路由入口:按用户读取可见作业/考试并判定;异常时放行不阻断对话"""
    if user_role != "student":
        return None
    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            return None
        return check_answer_protection(db, user, message, course_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("未截止作业答案保护判定失败(user=%s): %s", user_id, exc)
        return None
    finally:
        db.close()
