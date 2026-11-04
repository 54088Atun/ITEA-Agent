"""课程结构复制:课程信息 + 知识点树 + 素材元数据

只复制结构与元数据,不复制选课关系、学情、班级、作业/考试与提交,
新课程归属复制者,审核状态按新建课程口径默认 approved。
"""
import secrets

from sqlalchemy.orm import Session

from app.models.course import Course, CourseMaterial, KnowledgePoint


def unique_course_code(db: Session, source_code: str) -> str:
    """基于源课程代码生成不冲突的副本代码"""
    base = (source_code or "COPY")[:14]
    for i in range(1, 100):
        candidate = f"{base}-C{i}"
        if not db.query(Course).filter(Course.code == candidate).first():
            return candidate
    return f"COPY-{secrets.token_hex(4)}"[:20]


def copy_course_structure(
    db: Session,
    source: Course,
    owner_id: int,
    *,
    name: str | None = None,
    code: str | None = None,
    semester: str | None = None,
    audit_status: str = "pending",
) -> tuple[Course, dict]:
    """复制课程结构并返回 (新课程, 统计)"""
    new_course = Course(
        teacher_id=owner_id,
        name=(name or f"{source.name}（副本）")[:100],
        code=code or unique_course_code(db, source.code),
        syllabus=source.syllabus,
        semester=semester if semester is not None else source.semester,
        audit_status=audit_status,
    )
    db.add(new_course)
    db.flush()

    # 知识点树:两遍写入保留父子关系
    kps = (
        db.query(KnowledgePoint)
        .filter(KnowledgePoint.course_id == source.id)
        .order_by(KnowledgePoint.id.asc())
        .all()
    )
    id_map = {}
    for kp in kps:
        new_kp = KnowledgePoint(
            course_id=new_course.id,
            name=kp.name,
            description=kp.description,
            parent_id=None,
        )
        db.add(new_kp)
        db.flush()
        id_map[kp.id] = new_kp
    for kp in kps:
        if kp.parent_id and kp.parent_id in id_map:
            id_map[kp.id].parent_id = id_map[kp.parent_id].id

    # 素材元数据:复用原文件路径,分块数归零提示需重新入库
    materials = (
        db.query(CourseMaterial)
        .filter(CourseMaterial.course_id == source.id)
        .all()
    )
    for m in materials:
        db.add(CourseMaterial(
            course_id=new_course.id,
            type=m.type,
            title=m.title,
            file_path=m.file_path,
            chunk_count=0,
        ))

    return new_course, {"knowledge_points": len(kps), "materials": len(materials)}
