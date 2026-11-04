"""课程相关表:课程、课件素材、知识点、素材解析任务"""
from sqlalchemy import Column, BigInteger, String, Text, Enum, Integer, DateTime, ForeignKey, func
from app.db.session import Base

# SQLite 仅支持 INTEGER PRIMARY KEY 自增,测试库用变体兼容;MySQL 仍为 BIGINT
BigIntPK = BigInteger().with_variant(Integer, "sqlite")


class Course(Base):
    __tablename__ = "courses"

    id = Column(BigIntPK, primary_key=True, autoincrement=True)
    teacher_id = Column(BigInteger, ForeignKey("users.id"), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    code = Column(String(20), nullable=False)
    syllabus = Column(Text, comment="课程大纲")
    semester = Column(String(20), comment="学期,如 2026春")
    audit_status = Column(
        Enum("pending", "approved", "rejected", name="course_audit_status"),
        nullable=False, default="pending", server_default="pending",
        comment="审核状态",
    )
    archived_at = Column(DateTime, nullable=True, comment="归档时间")
    deleted_at = Column(DateTime, nullable=True, comment="软删除时间")
    created_at = Column(DateTime, server_default=func.now())


class CourseMaterial(Base):
    __tablename__ = "course_materials"

    id = Column(BigIntPK, primary_key=True, autoincrement=True)
    course_id = Column(BigInteger, ForeignKey("courses.id"), nullable=False, index=True)
    type = Column(
        Enum("courseware", "syllabus", "exercise", "interview", name="material_type"),
        nullable=False, comment="课件/考纲/习题/面试资料",
    )
    title = Column(String(200), nullable=False)
    file_path = Column(String(500), nullable=False)
    chunk_count = Column(Integer, default=0, comment="向量分块数")
    moderation_status = Column(
        String(20), nullable=False, default="approved", server_default="approved",
        comment="内容审核:pending/approved/rejected",
    )
    uploaded_at = Column(DateTime, server_default=func.now())


class MaterialParseJob(Base):
    """教材解析任务(NF-04):上传后异步解析并做内容审核

    - 每个素材保留一条任务记录,重试时复用并累加 attempts
    - status: pending / processing / done / rejected / failed
    - 审核不通过时 status=rejected,素材 moderation_status=rejected,不可用于检索与预览
    """
    __tablename__ = "material_parse_jobs"

    id = Column(BigIntPK, primary_key=True, autoincrement=True)
    material_id = Column(
        BigInteger, ForeignKey("course_materials.id"), nullable=False, unique=True,
        index=True, comment="一个素材对应一条解析任务",
    )
    course_id = Column(BigInteger, ForeignKey("courses.id"), nullable=False, index=True)
    status = Column(
        String(20), nullable=False, default="pending", server_default="pending",
        comment="pending/processing/done/rejected/failed",
    )
    progress = Column(Integer, nullable=False, default=0, server_default="0",
                      comment="解析进度 0-100")
    attempts = Column(Integer, nullable=False, default=0, server_default="0")
    error = Column(Text, comment="失败或拒绝原因")
    result_text = Column(Text, comment="解析出的文本(截断后)")
    moderation_hits = Column(Text, comment="审核命中 JSON")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    finished_at = Column(DateTime)


class KnowledgePoint(Base):
    __tablename__ = "knowledge_points"

    id = Column(BigIntPK, primary_key=True, autoincrement=True)
    course_id = Column(BigInteger, ForeignKey("courses.id"), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    description = Column(Text)
    parent_id = Column(BigInteger, ForeignKey("knowledge_points.id"), comment="父知识点,树形结构")