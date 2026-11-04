"""班级维度学情与作业/考试统计(CL-05)

口径:
- 学生范围 = 班级 active 成员
- 学情范围 = 成员在班级绑定课程下的学情档案;未绑定课程时聚合成员全部档案
- 作业/考试范围 = 直接面向该班级发布的任务
"""
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.assignment import Assignment, Submission
from app.models.classroom import ClassMember, Classroom
from app.models.course import Course, KnowledgePoint
from app.models.exam import Exam, ExamQuestion, ExamRecord
from app.models.profile import MasteryRecord, StudentProfile, WrongQuestion
from app.models.question import Question
from app.models.user import User
from app.services import privacy as privacy_service


def _student_ids(db: Session, class_id: int) -> list[int]:
    return [
        row[0] for row in db.query(ClassMember.student_id).filter(
            ClassMember.class_id == class_id,
            ClassMember.status == "active",
            ClassMember.role.in_(("student", "monitor", "representative", "custom")),
        ).all()
    ]


def _profiles(db: Session, student_ids: list[int], course_id: Optional[int]):
    if not student_ids:
        return []
    query = db.query(StudentProfile).filter(
        StudentProfile.user_id.in_(student_ids),
    )
    if course_id:
        query = query.filter(StudentProfile.course_id == course_id)
    return query.all()


def _weak_points(db: Session, profile_ids: list[int]) -> list[dict]:
    if not profile_ids:
        return []
    rows = (
        db.query(
            KnowledgePoint.id, KnowledgePoint.name,
            func.avg(MasteryRecord.mastery_level).label("avg_mastery"),
        )
        .join(MasteryRecord, MasteryRecord.kp_id == KnowledgePoint.id)
        .filter(MasteryRecord.profile_id.in_(profile_ids))
        .group_by(KnowledgePoint.id, KnowledgePoint.name)
        .order_by(func.avg(MasteryRecord.mastery_level).asc())
        .limit(10)
        .all()
    )
    result = []
    for kp_id, kp_name, avg_mastery in rows:
        wrong_count = (
            db.query(func.count(WrongQuestion.id))
            .filter(
                WrongQuestion.kp_id == kp_id,
                WrongQuestion.profile_id.in_(profile_ids),
            )
            .scalar() or 0
        )
        result.append({
            "kp_id": kp_id,
            "kp_name": kp_name,
            "avg_mastery": round(float(avg_mastery or 0), 1),
            "wrong_count": wrong_count,
        })
    return result


def _assignment_stats(db: Session, classroom: Classroom, student_ids: list[int]) -> list[dict]:
    rows = (
        db.query(Assignment)
        .filter(Assignment.class_id == classroom.id)
        .order_by(Assignment.id.desc())
        .limit(20)
        .all()
    )
    result = []
    for row in rows:
        base = db.query(Submission).filter(
            Submission.assignment_id == row.id,
            Submission.student_id.in_(student_ids or [0]),
            Submission.status == "submitted",
        )
        submitted = base.count()
        confirmed = base.filter(Submission.confirmed_at.isnot(None)).count()
        avg_score = base.filter(
            Submission.confirmed_at.isnot(None), Submission.score.isnot(None),
        ).with_entities(func.avg(Submission.score)).scalar()
        result.append({
            "assignment_id": row.id,
            "title": row.title,
            "due_at": row.due_at,
            "submitted": submitted,
            "confirmed": confirmed,
            "pending": submitted - confirmed,
            "avg_score": round(float(avg_score), 1) if avg_score is not None else None,
        })
    return result


def _exam_stats(db: Session, classroom: Classroom, student_ids: list[int]) -> list[dict]:
    exams = (
        db.query(Exam)
        .filter(Exam.class_id == classroom.id)
        .order_by(Exam.id.desc())
        .limit(20)
        .all()
    )
    if not exams:
        return []
    exam_ids = [e.id for e in exams]
    short_exam_ids = {
        row[0] for row in (
            db.query(ExamQuestion.exam_id)
            .join(Question, ExamQuestion.question_id == Question.id)
            .filter(ExamQuestion.exam_id.in_(exam_ids), Question.type == "short")
            .all()
        )
    }
    result = []
    for exam in exams:
        base = db.query(ExamRecord).filter(
            ExamRecord.exam_id == exam.id,
            ExamRecord.student_id.in_(student_ids or [0]),
        )
        submitted = base.count()
        avg_score = base.with_entities(func.avg(ExamRecord.total_score)).scalar()
        pending = 0
        if exam.id in short_exam_ids:
            pending = base.filter(ExamRecord.graded_at.is_(None)).count()
        result.append({
            "exam_id": exam.id,
            "title": exam.title,
            "submitted": submitted,
            "pending_manual": pending,
            "avg_score": round(float(avg_score), 1) if avg_score is not None else None,
        })
    return result


def build_class_stats(db: Session, classroom: Classroom) -> dict:
    student_ids = _student_ids(db, classroom.id)
    prefs = privacy_service.get_map(db, student_ids)
    # 学习记录设为「仅自己」的学生不进入教师报表明细与聚合
    visible_ids = [
        sid for sid in student_ids
        if privacy_service.learning_visible(prefs.get(sid), "teacher")
    ]
    profiles = _profiles(db, visible_ids, classroom.course_id)
    profile_ids = [p.id for p in profiles]

    progress_by_user: dict[int, list[float]] = {}
    profile_ids_by_user: dict[int, list[int]] = {}
    for profile in profiles:
        progress_by_user.setdefault(profile.user_id, []).append(
            float(profile.overall_progress or 0)
        )
        profile_ids_by_user.setdefault(profile.user_id, []).append(profile.id)

    users = {
        u.id: u for u in db.query(User).filter(User.id.in_(student_ids or [0])).all()
    }
    weak_mastery = {
        row[0]: row[1] for row in (
            db.query(MasteryRecord.profile_id, func.count(MasteryRecord.id))
            .filter(
                MasteryRecord.profile_id.in_(profile_ids or [0]),
                MasteryRecord.mastery_level < 60,
            )
            .group_by(MasteryRecord.profile_id)
            .all()
        )
    }

    students = []
    for user_id in visible_ids:
        user = users.get(user_id)
        values = progress_by_user.get(user_id, [])
        progress = round(sum(values) / len(values), 1) if values else 0.0
        weak_count = sum(
            int(weak_mastery.get(pid, 0))
            for pid in profile_ids_by_user.get(user_id, [])
        )
        students.append({
            "user_id": user_id,
            "name": privacy_service.name_of(
                user, prefs.get(user_id), "teacher",
            ) if user else f"用户 {user_id}",
            "overall_progress": progress,
            "weak_count": weak_count,
        })
    students.sort(key=lambda item: (item["overall_progress"], item["name"]))

    avg_progress = (
        round(sum(item["overall_progress"] for item in students) / len(students), 1)
        if students else 0.0
    )
    course = (
        db.query(Course).filter(Course.id == classroom.course_id).first()
        if classroom.course_id else None
    )

    return {
        "class_id": classroom.id,
        "class_name": classroom.name,
        "course_id": classroom.course_id,
        "course_name": course.name if course else None,
        "student_count": len(student_ids),
        "avg_progress": avg_progress,
        "weak_points": _weak_points(db, profile_ids),
        "students": students,
        "assignments": _assignment_stats(db, classroom, student_ids),
        "exams": _exam_stats(db, classroom, student_ids),
    }
