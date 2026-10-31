"""课程访问控制:统一判定课程可见性

课程私有化口径:
- admin:全部课程
- teacher:仅自己创建的课程(分享得到的是副本,归属副本创建者)
- student:仅 course_enrollments 中存在的课程(来源:班级/自助/分享/历史迁移)

所有课程详情、知识点、素材、RAG 查询必须走本模块,避免直连接口越权。
"""
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.course import Course, CourseMaterial, KnowledgePoint
from app.models.classroom import CourseEnrollment
from app.models.user import User


def _course_or_404(db: Session, course_id: int) -> Course:
    course = db.query(Course).filter(Course.id == course_id).first()
    if not course:
        raise HTTPException(status_code=404, detail="课程不存在")
    return course


def can_view_course(user: User, course: Course, db: Session) -> bool:
    if user.role == "admin":
        return True
    if user.role == "teacher":
        return course.teacher_id == user.id
    if user.role == "student":
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
        return [cid for (cid,) in db.query(Course.id).all()]
    if user.role == "teacher":
        return [cid for (cid,) in db.query(Course.id).filter(
            Course.teacher_id == user.id
        ).all()]
    return [cid for (cid,) in db.query(CourseEnrollment.course_id).filter(
        CourseEnrollment.student_id == user.id
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
