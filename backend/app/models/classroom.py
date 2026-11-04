"""班级与选课关系表:班级、班级成员、课程选课关系、课程分享码

设计口径:
- 教师课程默认私有,学生可见范围由 course_enrollments 决定
- 学生加入班级时自动为该班级课程写入 source='class' 的选课关系
- 旧数据迁移写入 source='legacy',避免既有学情断裂
- 教师课程分享码与班级邀请码分离,防止学生用分享码绕过班级取课
"""
from sqlalchemy import (
    Column, BigInteger, String, Text, Enum, Integer, DateTime,
    ForeignKey, UniqueConstraint, func,
)
from app.db.session import Base

# SQLite 仅支持 INTEGER PRIMARY KEY 自增,测试库用变体兼容;MySQL 仍为 BIGINT
BigIntPK = BigInteger().with_variant(Integer, "sqlite")


class Classroom(Base):
    """班级:教师创建,可关联一门课程,通过邀请码招募学生"""
    __tablename__ = "classes"

    id = Column(BigIntPK, primary_key=True, autoincrement=True)
    teacher_id = Column(BigInteger, ForeignKey("users.id"), nullable=False, index=True)
    course_id = Column(BigInteger, ForeignKey("courses.id"), nullable=True, index=True)
    name = Column(String(100), nullable=False)
    semester = Column(String(20), comment="学期,如 2026秋")
    invite_code = Column(String(16), nullable=False, unique=True, index=True)
    invite_expires_at = Column(DateTime, nullable=True, comment="邀请码过期时间")
    invite_max_uses = Column(Integer, nullable=False, default=50, server_default="50")
    invite_used = Column(Integer, nullable=False, default=0, server_default="0")
    max_students = Column(Integer, nullable=False, default=100, server_default="100",
                          comment="班级学生容量上限")
    status = Column(
        Enum("active", "archived", name="class_status"),
        nullable=False, default="active", server_default="active",
    )
    description = Column(Text)
    created_at = Column(DateTime, server_default=func.now())


class ClassMember(Base):
    """班级成员:学生或任课教师;角色仅在班级内生效"""
    __tablename__ = "class_members"
    __table_args__ = (
        UniqueConstraint("class_id", "student_id", name="uq_class_member"),
    )

    id = Column(BigIntPK, primary_key=True, autoincrement=True)
    class_id = Column(BigInteger, ForeignKey("classes.id"), nullable=False, index=True)
    # 字段名沿用 student_id,实际存成员用户 ID(学生或教师)
    student_id = Column(BigInteger, ForeignKey("users.id"), nullable=False, index=True)
    role = Column(
        Enum("teacher", "student", "monitor", "representative", "custom",
             name="class_member_role"),
        nullable=False, default="student", server_default="student",
        comment="班级内角色",
    )
    title = Column(String(50), nullable=True, comment="班级内头衔,如某课教师/课代表")
    permissions = Column(Text, nullable=True, comment="自定义角色权限 JSON 数组")
    invited_by = Column(BigInteger, ForeignKey("users.id"), nullable=True, comment="邀请人")
    status = Column(
        Enum("active", "left", name="class_member_status"),
        nullable=False, default="active", server_default="active",
    )
    joined_at = Column(DateTime, server_default=func.now())


class CourseEnrollment(Base):
    """课程选课关系:学生可见课程的唯一依据"""
    __tablename__ = "course_enrollments"
    __table_args__ = (
        UniqueConstraint("course_id", "student_id", name="uq_course_enrollment"),
    )

    id = Column(BigIntPK, primary_key=True, autoincrement=True)
    course_id = Column(BigInteger, ForeignKey("courses.id"), nullable=False, index=True)
    student_id = Column(BigInteger, ForeignKey("users.id"), nullable=False, index=True)
    source = Column(
        Enum("class", "self", "share", "legacy", name="enrollment_source"),
        nullable=False, default="self", server_default="self",
        comment="来源:班级/自助/分享/历史迁移",
    )
    class_id = Column(BigInteger, ForeignKey("classes.id"), nullable=True)
    created_at = Column(DateTime, server_default=func.now())


class CourseCollaborator(Base):
    """课程协作者:获得原课程的联合教学权限,不复制课程或学生数据"""
    __tablename__ = "course_collaborators"
    __table_args__ = (
        UniqueConstraint("course_id", "teacher_id", name="uq_course_collaborator"),
    )

    id = Column(BigIntPK, primary_key=True, autoincrement=True)
    course_id = Column(BigInteger, ForeignKey("courses.id"), nullable=False, index=True)
    teacher_id = Column(BigInteger, ForeignKey("users.id"), nullable=False, index=True)
    added_by = Column(BigInteger, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, server_default=func.now())


class CourseShare(Base):
    """课程分享码:仅教师之间使用,被分享方获得课程快照副本"""
    __tablename__ = "course_shares"

    id = Column(BigIntPK, primary_key=True, autoincrement=True)
    course_id = Column(BigInteger, ForeignKey("courses.id"), nullable=False, index=True)
    owner_id = Column(BigInteger, ForeignKey("users.id"), nullable=False, index=True)
    code = Column(String(16), nullable=False, unique=True, index=True)
    expires_at = Column(DateTime, nullable=True)
    max_uses = Column(Integer, nullable=False, default=1, server_default="1")
    used_count = Column(Integer, nullable=False, default=0, server_default="0")
    revoked_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now())


class ClassAnnouncement(Base):
    """班级公告:班主任/获授权的自定义角色发布,班级成员可查看"""
    __tablename__ = "class_announcements"

    id = Column(BigIntPK, primary_key=True, autoincrement=True)
    class_id = Column(BigInteger, ForeignKey("classes.id"), nullable=False, index=True)
    author_id = Column(BigInteger, ForeignKey("users.id"), nullable=False, index=True)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, server_default=func.now())


class CodeRedemption(Base):
    """统一课程码使用审计:教师复制课程 / 学生加入班级"""
    __tablename__ = "code_redemptions"

    id = Column(BigIntPK, primary_key=True, autoincrement=True)
    code = Column(String(16), nullable=False, index=True)
    scope = Column(String(20), nullable=False, comment="course/class")
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False, index=True)
    role = Column(String(20), nullable=False, comment="teacher/admin/student")
    action = Column(String(30), nullable=False, comment="course_copy/class_join")
    target_id = Column(BigInteger, comment="复制后的课程ID或班级ID")
    created_at = Column(DateTime, server_default=func.now())

