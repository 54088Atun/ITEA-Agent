"""工作区工具:让助手读取当前用户的全部业务数据,并执行有权限的写操作

口径:
- 读操作只返回当前登录用户可见的课程/班级/任务,不跨用户
- 写操作全部落到具体资源上,逐项校验课程归属、班级角色与任务归属
- 写操作由工具层要求人工确认后才会执行(requires_confirmation)
"""
import json
import logging
import secrets
from datetime import datetime, timedelta

from app.db.session import SessionLocal
from app.models.assignment import Assignment, Submission
from app.models.classroom import (
    ClassAnnouncement, ClassMember, Classroom, CourseEnrollment,
)
from app.models.course import Course, KnowledgePoint
from app.models.exam import Exam, ExamQuestion
from app.models.question import Question
from app.models.user import User
from app.services import class_roles
from app.services.course_access import visible_course_ids
from app.services.notifications import notify_task_students

logger = logging.getLogger(__name__)

CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
WRITE_ACTIONS = (
    "course.create", "course.update",
    "class.create", "class.announce",
    "class.member_role", "class.member_remove",
    "assignment.create", "assignment.confirm_score",
    "question.create",
    "exam.publish", "exam.close",
    "assignment.submit",
)


def _now() -> datetime:
    return datetime.utcnow()


def _gen_invite_code(db) -> str:
    for _ in range(20):
        code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(8))
        if not db.query(Classroom).filter(Classroom.invite_code == code).first():
            return code
    raise RuntimeError("邀请码生成失败")


def _load_user(db, user_id: int) -> User:
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise ValueError("用户不存在")
    return user


def _course_for_teacher(db, course_id: int, user: User) -> Course:
    course = db.query(Course).filter(
        Course.id == course_id, Course.deleted_at.is_(None),
    ).first()
    if not course:
        raise ValueError("课程不存在")
    if user.role != "admin" and course.teacher_id != user.id:
        raise ValueError("只能操作自己创建的课程")
    return course


def _classroom_for_teacher(db, class_id: int, user: User) -> Classroom:
    classroom = db.query(Classroom).filter(Classroom.id == class_id).first()
    if not classroom:
        raise ValueError("班级不存在")
    if user.role == "admin" or classroom.teacher_id == user.id:
        return classroom
    member = class_roles.active_member(db, classroom.id, user.id)
    if member and member.role == "teacher":
        return classroom
    raise ValueError("你不是该班级成员")


def _assignment_for_teacher(db, assignment_id: int, user: User) -> Assignment:
    row = db.query(Assignment).filter(Assignment.id == assignment_id).first()
    if not row:
        raise ValueError("作业不存在")
    if user.role != "admin" and row.teacher_id != user.id:
        raise ValueError("只能操作自己发布的作业")
    return row


def _assignment_visible_to_student(db, row: Assignment, user: User) -> None:
    if row.status != "published":
        raise ValueError("作业尚未发布")
    if row.class_id:
        if not class_roles.active_member(db, row.class_id, user.id):
            raise ValueError("你不在该作业的发布班级中")
        return
    if row.course_id:
        enrolled = db.query(CourseEnrollment).filter(
            CourseEnrollment.course_id == row.course_id,
            CourseEnrollment.student_id == user.id,
        ).first()
        if not enrolled:
            raise ValueError("你未选修该课程")
        return
    raise ValueError("作业未设置发布范围")


def _class_counts(db, classroom: Classroom) -> dict:
    total = db.query(ClassMember).filter(
        ClassMember.class_id == classroom.id,
        ClassMember.status == "active",
        ClassMember.role.in_(class_roles.STUDENT_ROLES),
    ).count()
    return {"member_count": total, "max_students": classroom.max_students}


def _overview_courses(db, user: User) -> list[dict]:
    ids = visible_course_ids(user, db)
    if not ids:
        return []
    rows = db.query(Course).filter(Course.id.in_(ids)).order_by(Course.id.desc()).limit(30).all()
    return [
        {
            "id": c.id, "name": c.name, "code": c.code,
            "semester": c.semester, "audit_status": c.audit_status,
        }
        for c in rows
    ]


def _overview_classes(db, user: User) -> list[dict]:
    if user.role == "admin":
        rows = db.query(Classroom).order_by(Classroom.id.desc()).limit(30).all()
    else:
        member_ids = [
            cid for (cid,) in db.query(ClassMember.class_id).filter(
                ClassMember.student_id == user.id,
                ClassMember.status == "active",
            ).all()
        ]
        query = db.query(Classroom).filter(Classroom.id.in_(member_ids or [0]))
        if user.role == "teacher":
            query = db.query(Classroom).filter(
                (Classroom.teacher_id == user.id) | (Classroom.id.in_(member_ids or [0])),
            )
        rows = query.order_by(Classroom.id.desc()).limit(30).all()
    course_map = {
        c.id: c.name for c in db.query(Course).filter(
            Course.id.in_([row.course_id for row in rows if row.course_id] or [0]),
        ).all()
    }
    return [
        {
            "id": row.id, "name": row.name, "course_name": course_map.get(row.course_id),
            "semester": row.semester, "status": row.status,
            "my_role": class_roles.my_role(db, row, user),
            **_class_counts(db, row),
        }
        for row in rows
    ]


def _overview_assignments(db, user: User) -> list[dict]:
    if user.role in ("teacher", "admin"):
        query = db.query(Assignment)
        if user.role != "admin":
            query = query.filter(Assignment.teacher_id == user.id)
        rows = query.order_by(Assignment.id.desc()).limit(20).all()
        return [
            {
                "id": row.id, "title": row.title, "kind": row.kind,
                "course_id": row.course_id, "class_id": row.class_id,
                "status": row.status, "due_at": row.due_at,
                "allow_late": row.allow_late,
            }
            for row in rows
        ]

    class_ids = [
        cid for (cid,) in db.query(ClassMember.class_id).filter(
            ClassMember.student_id == user.id, ClassMember.status == "active",
        ).all()
    ]
    course_ids = [
        cid for (cid,) in db.query(CourseEnrollment.course_id).filter(
            CourseEnrollment.student_id == user.id,
        ).all()
    ]
    conditions = []
    if class_ids:
        conditions.append(Assignment.class_id.in_(class_ids))
    if course_ids:
        conditions.append(Assignment.course_id.in_(course_ids))
    if not conditions:
        return []
    from sqlalchemy import or_
    rows = db.query(Assignment).filter(
        Assignment.status == "published", or_(*conditions),
    ).order_by(Assignment.id.desc()).limit(20).all()
    submissions = {
        s.assignment_id: s for s in db.query(Submission).filter(
            Submission.student_id == user.id,
            Submission.assignment_id.in_([r.id for r in rows] or [0]),
        ).all()
    }
    return [
        {
            "id": row.id, "title": row.title, "kind": row.kind,
            "course_id": row.course_id, "class_id": row.class_id,
            "due_at": row.due_at,
            "my_status": getattr(submissions.get(row.id), "status", None),
            "my_score": getattr(submissions.get(row.id), "score", None),
        }
        for row in rows
    ]


def _overview_exams(db, user: User) -> list[dict]:
    if user.role in ("teacher", "admin"):
        query = db.query(Exam)
        if user.role != "admin":
            query = query.filter(Exam.teacher_id == user.id)
        rows = query.order_by(Exam.id.desc()).limit(20).all()
    else:
        from sqlalchemy import or_
        class_ids = [
            cid for (cid,) in db.query(ClassMember.class_id).filter(
                ClassMember.student_id == user.id, ClassMember.status == "active",
            ).all()
        ]
        course_ids = [
            cid for (cid,) in db.query(CourseEnrollment.course_id).filter(
                CourseEnrollment.student_id == user.id,
            ).all()
        ]
        conditions = []
        if class_ids:
            conditions.append(Exam.class_id.in_(class_ids))
        if course_ids:
            conditions.append(Exam.course_id.in_(course_ids))
        if not conditions:
            return []
        rows = db.query(Exam).filter(
            Exam.status == "published", or_(*conditions),
        ).order_by(Exam.id.desc()).limit(20).all()
    return [
        {
            "id": row.id, "title": row.title, "course_id": row.course_id,
            "class_id": row.class_id, "status": row.status,
            "total_score": row.total_score, "due_at": row.due_at,
        }
        for row in rows
    ]


def workspace_overview(
    user_id: int = 0, user_role: str = "student",
) -> dict:
    """读取当前用户的全部工作区数据(课程/班级/作业/考试)"""
    db = SessionLocal()
    try:
        user = _load_user(db, user_id)
        courses = _overview_courses(db, user)
        classes = _overview_classes(db, user)
        assignments = _overview_assignments(db, user)
        exams = _overview_exams(db, user)
        return {
            "role": user.role,
            "courses": courses,
            "classes": classes,
            "assignments": assignments,
            "exams": exams,
            "counts": {
                "courses": len(courses),
                "classes": len(classes),
                "assignments": len(assignments),
                "exams": len(exams),
            },
        }
    finally:
        db.close()


def workspace_action(
    action: str,
    params: dict | None = None,
    summary: str = "",
    user_id: int = 0,
    user_role: str = "student",
) -> dict:
    """执行当前用户有权限的写操作;返回 {message, id?, ...}"""
    db = SessionLocal()
    try:
        user = _load_user(db, user_id)
        data = params or {}
        if action not in WRITE_ACTIONS:
            raise ValueError(f"不支持的操作: {action}")

        if action == "course.create":
            name = str(data.get("name") or "").strip()
            code = str(data.get("code") or "").strip()
            if not name or not code:
                raise ValueError("课程名与课程代码不能为空")
            if user.role not in ("teacher", "admin"):
                raise ValueError("仅教师可创建课程")
            row = Course(
                teacher_id=user.id, name=name[:100], code=code[:20],
                semester=(data.get("semester") or None),
                syllabus=(data.get("syllabus") or None),
                audit_status="pending",
            )
            db.add(row)
            db.commit()
            db.refresh(row)
            return {"message": f"已创建课程《{row.name}》，等待平台审核", "id": row.id}

        if action == "course.update":
            row = _course_for_teacher(db, int(data.get("course_id") or 0), user)
            for key in ("name", "code", "semester", "syllabus"):
                if key in data:
                    setattr(row, key, data.get(key))
            db.commit()
            return {"message": f"已更新课程《{row.name}》", "id": row.id}

        if action == "class.create":
            name = str(data.get("name") or "").strip()
            if not name:
                raise ValueError("班级名称不能为空")
            if user.role not in ("teacher", "admin"):
                raise ValueError("仅教师可创建班级")
            course_id = data.get("course_id")
            if course_id:
                _course_for_teacher(db, int(course_id), user)
            row = Classroom(
                teacher_id=user.id,
                course_id=int(course_id) if course_id else None,
                name=name[:100],
                semester=(data.get("semester") or None),
                description=(data.get("description") or None),
                invite_code=_gen_invite_code(db),
                invite_expires_at=_now() + timedelta(days=7),
                invite_max_uses=50,
                max_students=100,
            )
            db.add(row)
            db.commit()
            db.refresh(row)
            return {
                "message": f"已创建班级《{row.name}》，课程码 {row.invite_code}",
                "id": row.id, "invite_code": row.invite_code,
            }

        if action == "class.announce":
            classroom = _classroom_for_teacher(db, int(data.get("class_id") or 0), user)
            class_roles.require_permission(db, classroom, user, "notice.post")
            content = str(data.get("content") or "").strip()
            if not content:
                raise ValueError("公告内容不能为空")
            row = ClassAnnouncement(
                class_id=classroom.id, author_id=user.id, content=content[:2000],
            )
            db.add(row)
            db.commit()
            db.refresh(row)
            return {"message": f"已在《{classroom.name}》发布公告", "id": row.id}

        if action == "class.member_role":
            classroom = _classroom_for_teacher(db, int(data.get("class_id") or 0), user)
            target_id = int(data.get("user_id") or 0)
            role = str(data.get("role") or "").strip()
            inviter_role = class_roles.my_role(db, classroom, user)
            if not class_roles.can_assign_role(inviter_role, role):
                raise ValueError("当前班级角色无权赋予该角色")
            member = class_roles.active_member(db, classroom.id, target_id)
            if not member:
                raise ValueError("该用户不在班级中")
            target = _load_user(db, target_id)
            class_roles.ensure_role_matches_user(target, role)
            title = data.get("title")
            if role == "representative" and not title:
                title = "课代表"
            member.role = role
            member.title = title
            db.commit()
            return {"message": f"已将 {target.name} 设为 {role}", "id": member.id}

        if action == "class.member_remove":
            classroom = db.query(Classroom).filter(
                Classroom.id == int(data.get("class_id") or 0),
            ).first()
            if not classroom:
                raise ValueError("班级不存在")
            if user.role != "admin" and classroom.teacher_id != user.id:
                raise ValueError("仅班主任或管理员可移出成员")
            member = class_roles.active_member(db, classroom.id, int(data.get("user_id") or 0))
            if not member:
                raise ValueError("该用户不在班级中")
            member.status = "left"
            from app.api.classroom import _revoke_course_if_alone
            _revoke_course_if_alone(db, member.student_id, classroom)
            db.commit()
            return {"message": "已将该成员移出班级", "id": member.id}

        if action == "assignment.create":
            if user.role not in ("teacher", "admin"):
                raise ValueError("仅教师可发布作业")
            course_id = int(data.get("course_id") or 0)
            _course_for_teacher(db, course_id, user)
            title = str(data.get("title") or "").strip()
            if not title:
                raise ValueError("作业标题不能为空")
            class_id = data.get("class_id")
            if class_id:
                classroom = db.query(Classroom).filter(Classroom.id == int(class_id)).first()
                if not classroom:
                    raise ValueError("班级不存在")
                if user.role != "admin" and classroom.teacher_id != user.id:
                    raise ValueError("只能向自己的班级发布作业")
            due_at = None
            if data.get("due_days"):
                due_at = _now() + timedelta(days=int(data["due_days"]))
            publish = bool(data.get("publish", True))
            row = Assignment(
                teacher_id=user.id, course_id=course_id,
                class_id=int(class_id) if class_id else None,
                title=title[:120], kind="homework",
                description=data.get("description"),
                reference_answer=data.get("reference_answer"),
                due_at=due_at, allow_late=bool(data.get("allow_late")),
                status="published" if publish else "draft",
            )
            db.add(row)
            db.flush()
            if publish:
                notify_task_students(
                    db, "assignment", row.id, row.title, row.course_id, row.class_id,
                    f"/student/assignments?assignment_id={row.id}",
                )
            db.commit()
            db.refresh(row)
            return {"message": f"已{'发布' if publish else '保存'}作业《{row.title}》", "id": row.id}

        if action == "assignment.confirm_score":
            row = _assignment_for_teacher(db, int(data.get("assignment_id") or 0), user)
            sub = db.query(Submission).filter(
                Submission.id == int(data.get("submission_id") or 0),
                Submission.assignment_id == row.id,
            ).first()
            if not sub:
                raise ValueError("提交记录不存在")
            score = max(0, min(100, int(data.get("score") or 0)))
            sub.score = score
            sub.feedback = data.get("feedback")
            sub.confirmed_at = _now()
            sub.confirmed_by = user.id
            db.commit()
            return {"message": f"已确认成绩 {score} 分", "id": sub.id}

        if action == "assignment.submit":
            if user.role != "student":
                raise ValueError("仅学生可提交作业")
            row = db.query(Assignment).filter(
                Assignment.id == int(data.get("assignment_id") or 0),
            ).first()
            if not row:
                raise ValueError("作业不存在")
            _assignment_visible_to_student(db, row, user)
            if row.due_at and row.due_at < _now() and not row.allow_late:
                raise ValueError("作业已截止，不能提交")
            content = str(data.get("content") or "").strip()
            if not content:
                raise ValueError("提交内容不能为空")
            sub = db.query(Submission).filter(
                Submission.assignment_id == row.id,
                Submission.student_id == user.id,
            ).first()
            if sub:
                sub.content = content
                sub.status = "submitted"
                sub.submitted_at = _now()
            else:
                sub = Submission(
                    assignment_id=row.id, student_id=user.id,
                    content=content, status="submitted", submitted_at=_now(),
                )
                db.add(sub)
            db.commit()
            db.refresh(sub)
            return {"message": f"已提交作业《{row.title}》", "id": sub.id}

        if action == "question.create":
            if user.role not in ("teacher", "admin"):
                raise ValueError("仅教师可新增题目")
            course_id = int(data.get("course_id") or 0)
            _course_for_teacher(db, course_id, user)
            kp_id = data.get("kp_id")
            if kp_id:
                kp = db.query(KnowledgePoint).filter(
                    KnowledgePoint.id == int(kp_id),
                    KnowledgePoint.course_id == course_id,
                ).first()
                if not kp:
                    raise ValueError("知识点不属于该课程")
            from app.api.exams import _normalize_question
            norm = _normalize_question(data)
            row = Question(
                teacher_id=user.id, course_id=course_id,
                kp_id=int(kp_id) if kp_id else None,
                type=norm["type"], stem=norm["stem"],
                options=json.dumps(norm["options"], ensure_ascii=False),
                answer=norm["answer"], analysis=norm["analysis"] or None,
                difficulty=norm["difficulty"], source="manual", status="active",
            )
            db.add(row)
            db.commit()
            db.refresh(row)
            return {"message": "题目已加入题库", "id": row.id}

        if action in ("exam.publish", "exam.close"):
            exam = db.query(Exam).filter(Exam.id == int(data.get("exam_id") or 0)).first()
            if not exam:
                raise ValueError("试卷不存在")
            if user.role != "admin" and exam.teacher_id != user.id:
                raise ValueError("只能操作自己的试卷")
            if action == "exam.publish":
                if not db.query(ExamQuestion).filter(ExamQuestion.exam_id == exam.id).first():
                    raise ValueError("试卷没有题目，无法发布")
                exam.status = "published"
                notify_task_students(
                    db, "exam", exam.id, exam.title, exam.course_id, exam.class_id,
                    f"/student/exams?exam_id={exam.id}",
                )
            else:
                exam.status = "closed"
            db.commit()
            return {"message": f"试卷《{exam.title}》已{('发布' if action == 'exam.publish' else '关闭')}", "id": exam.id}

        raise ValueError(f"不支持的操作: {action}")
    finally:
        db.close()
