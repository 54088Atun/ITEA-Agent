"""试卷与考试作答

- 试卷归属教师与课程,可面向班级或课程发布
- 组卷仅支持客观题(单选/多选/判断),提交后自动判分
- 学生提交记录按 (exam_id, student_id) 唯一,不允许重复提交
"""
from sqlalchemy import (
    Column, BigInteger, String, Text, Integer, DateTime, ForeignKey,
    UniqueConstraint, func,
)
from app.db.session import Base

BigIntPK = BigInteger().with_variant(Integer, "sqlite")


class Exam(Base):
    __tablename__ = "exams"

    id = Column(BigIntPK, primary_key=True, autoincrement=True)
    teacher_id = Column(BigInteger, ForeignKey("users.id"), nullable=False, index=True)
    course_id = Column(BigInteger, ForeignKey("courses.id"), nullable=False, index=True)
    class_id = Column(BigInteger, ForeignKey("classes.id"), nullable=True, index=True)
    title = Column(String(120), nullable=False)
    description = Column(Text)
    duration_minutes = Column(Integer, nullable=False, default=60, server_default="60")
    start_at = Column(DateTime, nullable=True)
    due_at = Column(DateTime, nullable=True)
    total_score = Column(Integer, nullable=False, default=0, server_default="0")
    status = Column(String(20), nullable=False, default="draft", server_default="draft",
                    comment="draft/published/closed")
    created_at = Column(DateTime, server_default=func.now())


class ExamQuestion(Base):
    __tablename__ = "exam_questions"
    __table_args__ = (
        UniqueConstraint("exam_id", "question_id", name="uq_exam_question"),
    )

    id = Column(BigIntPK, primary_key=True, autoincrement=True)
    exam_id = Column(BigInteger, ForeignKey("exams.id"), nullable=False, index=True)
    question_id = Column(BigInteger, ForeignKey("questions.id"), nullable=False, index=True)
    score = Column(Integer, nullable=False, default=5, server_default="5")
    sort = Column(Integer, nullable=False, default=0, server_default="0")


class ExamRecord(Base):
    __tablename__ = "exam_records"
    __table_args__ = (
        UniqueConstraint("exam_id", "student_id", name="uq_exam_student"),
    )

    id = Column(BigIntPK, primary_key=True, autoincrement=True)
    exam_id = Column(BigInteger, ForeignKey("exams.id"), nullable=False, index=True)
    student_id = Column(BigInteger, ForeignKey("users.id"), nullable=False, index=True)
    answers = Column(Text, nullable=False, comment="作答 JSON:{question_id: answer}")
    total_score = Column(Integer, nullable=False, default=0, server_default="0")
    correct_count = Column(Integer, nullable=False, default=0, server_default="0")
    question_count = Column(Integer, nullable=False, default=0, server_default="0")
    short_scores = Column(Text, comment="简答题得分 JSON:{question_id: score}")
    ai_suggestions = Column(Text, comment="AI 简答评分建议 JSON(未确认前不生效)")
    graded_at = Column(DateTime, nullable=True, comment="简答批改时间")
    graded_by = Column(BigInteger, ForeignKey("users.id"), nullable=True)
    violations = Column(Integer, nullable=False, default=0, server_default="0",
                        comment="切屏/离开页面次数")
    client_id = Column(String(128), nullable=True, comment="提交答卷的考试客户端")
    copy_count = Column(Integer, nullable=False, default=0, server_default="0")
    paste_count = Column(Integer, nullable=False, default=0, server_default="0")
    timed_out = Column(Integer, nullable=False, default=0, server_default="0",
                       comment="是否在宽限期提交(1=超时提交)")
    submitted_at = Column(DateTime, server_default=func.now())


class ExamSession(Base):
    """考试作答会话:服务端计时与防作弊计数"""
    __tablename__ = "exam_sessions"
    __table_args__ = (
        UniqueConstraint("exam_id", "student_id", name="uq_exam_session_student"),
    )

    id = Column(BigIntPK, primary_key=True, autoincrement=True)
    exam_id = Column(BigInteger, ForeignKey("exams.id"), nullable=False, index=True)
    student_id = Column(BigInteger, ForeignKey("users.id"), nullable=False, index=True)
    started_at = Column(DateTime, server_default=func.now())
    deadline_at = Column(DateTime, nullable=True, comment="开始时间+时长,并与试卷截止取较早")
    last_seen_at = Column(DateTime, server_default=func.now())
    violations = Column(Integer, nullable=False, default=0, server_default="0")
    client_id = Column(String(128), nullable=True, comment="绑定的浏览器/设备客户端")
    copy_count = Column(Integer, nullable=False, default=0, server_default="0")
    paste_count = Column(Integer, nullable=False, default=0, server_default="0")
    submitted_at = Column(DateTime, nullable=True)
