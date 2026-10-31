"""课程相关表:课程、课件素材、知识点"""
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
        nullable=False, default="approved", server_default="approved",
        comment="审核状态",
    )
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
    uploaded_at = Column(DateTime, server_default=func.now())


class KnowledgePoint(Base):
    __tablename__ = "knowledge_points"

    id = Column(BigIntPK, primary_key=True, autoincrement=True)
    course_id = Column(BigInteger, ForeignKey("courses.id"), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    description = Column(Text)
    parent_id = Column(BigInteger, ForeignKey("knowledge_points.id"), comment="父知识点,树形结构")