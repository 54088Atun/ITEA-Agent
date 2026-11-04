"""课程访问控制:统一判定课程可见性

课程私有化口径:
- admin:全部课程
- teacher:自己创建或被授权协作的课程(分享得到的是副本,归属副本创建者)
- student:仅 course_enrollments 中存在的课程(来源:班级/自助/分享/历史迁移)

课程审核口径(TC-09):
- 私有课程保留平台审核字段与管理员审核入口,新建课程默认 approved(免人工审核)
- 只有 approved 的课程对学生开放;pending/rejected 时学生列表不出现、详情/知识点/
  素材/学情/RAG 一律不可访问,已加入的选课关系保留,重新通过后自动恢复
- 教师始终可见自己拥有或协作的课程(含 pending/rejected),便于修改后重新提交

所有课程详情、知识点、素材、RAG 查询必须走本模块,避免直连接口越权。
"""
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.course import Course, CourseMaterial, KnowledgePoint
from app.models.classroom import CourseCollaborator, CourseEnrollment
from app.models.user import User


def _course_or_404(db: Session, course_id: int) -> Course:
    course = db.query(Course).filter(Course.id == course_id).first()
    if not course:
        raise HTTPException(status_code=404, detail="课程不存在")
    return course


def is_open_to_students(course: Course) -> bool:
    """未删除且已通过平台审核的课程可对学生开放"""
    return course.deleted_at is None and course.audit_status == "approved"


def can_view_course(user: User, course: Course, db: Session) -> bool:
    if course.deleted_at is not None:
        return False
    if user.role == "admin":
        return True
    if user.role == "teacher":
        if course.teacher_id == user.id:
            return True
        return db.query(CourseCollaborator).filter(
            CourseCollaborator.course_id == course.id,
            CourseCollaborator.teacher_id == user.id,
        ).first() is not None
    if user.role == "student":
        if not is_open_to_students(course):
            return False
        return db.query(CourseEnrollment).filter(
            CourseEnrollment.course_id == course.id,
            CourseEnrollment.student_id == user.id,
        ).first() is not None
    return False


def assert_course_visible(user: User, course_id: int, db: Session) -> Course:
    """校验课程可见性:不存在 404,无权限 403"""
    course = _course_or_404(db, course_id)
    if not can_view_course(user, course, db):
        raise HTTPException(status_code=403, detail="无权访问该课程")
    return course


def visible_course_ids(user: User, db: Session) -> list[int]:
    if user.role == "admin":
        return [cid for (cid,) in db.query(Course.id).filter(
            Course.deleted_at.is_(None)
        ).all()]
    if user.role == "teacher":
        ids = {cid for (cid,) in db.query(Course.id).filter(
            Course.teacher_id == user.id,
            Course.deleted_at.is_(None),
        ).all()}
        ids.update(cid for (cid,) in db.query(Course.id).join(
            CourseCollaborator, CourseCollaborator.course_id == Course.id,
        ).filter(
            CourseCollaborator.teacher_id == user.id,
            Course.deleted_at.is_(None),
        ).all())
        return list(ids)
    return [cid for (cid,) in (
        db.query(CourseEnrollment.course_id)
        .join(Course, Course.id == CourseEnrollment.course_id)
        .filter(
            CourseEnrollment.student_id == user.id,
            Course.audit_status == "approved",
            Course.deleted_at.is_(None),
        )
    ).all()]


def require_material_visible(user: User, material_id: int, db: Session) -> CourseMaterial:
    material = db.query(CourseMaterial).filter(CourseMaterial.id == material_id).first()
    if not material:
        raise HTTPException(status_code=404, detail="素材不存在")
    assert_course_visible(user, material.course_id, db)
    return material


def require_knowledge_point_visible(user: User, kp_id: int, db: Session) -> KnowledgePoint:
    kp = db.query(KnowledgePoint).filter(KnowledgePoint.id == kp_id).first()
    if not kp:
        raise HTTPException(status_code=404, detail="知识点不存在")
    assert_course_visible(user, kp.course_id, db)
    return kp


def agent_course_scope_error(user_id: int | None, course_id: int) -> str | None:
    """Agent 工具调用前的课程范围校验(决策 #1)

    返回 None 表示通过,否则返回可读的拒绝原因。工具层必须调用本函数,
    不能依赖调用方自行保证 course_id 合法。
    """
    if not user_id:
        return "缺少用户上下文，无法校验课程范围"
    db = SessionLocal()
    try:
        user = db.get(User, user_id)
        if not user:
            return "用户不存在"
        course = db.query(Course).filter(Course.id == course_id).first()
        if not course:
            return "课程不存在"
        if not can_view_course(user, course, db):
            return "无权访问该课程"
        return None
    finally:
        db.close()
