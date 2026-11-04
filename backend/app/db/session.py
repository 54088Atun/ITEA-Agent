"""SQLAlchemy 数据库连接与会话管理"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from app.core.config import settings

engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    echo=False,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """FastAPI 依赖注入:获取数据库会话,请求结束自动关闭"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """建表(开发环境用,生产环境用 alembic 迁移)"""
    from app.models import (  # noqa: F401
        user, course, profile, practice, interview, classroom, conversation,
        knowledge_draft, interview_assignment, assignment, question, exam,
        upload_event, log, notification, agent_memory,
    )
    Base.metadata.create_all(bind=engine)
    _migrate_exam_record_columns()
    _seed_legacy_enrollments()
    _seed_feature_configs()


def _migrate_sqlite_columns():
    """SQLite 开发库补字段(create_all 不会修改已存在的表)"""
    from sqlalchemy import text

    try:
        with engine.begin() as conn:
            rows = conn.execute(text("PRAGMA table_info(course_materials)")).fetchall()
            if rows and "moderation_status" not in {row[1] for row in rows}:
                conn.execute(text(
                    "ALTER TABLE course_materials ADD COLUMN moderation_status "
                    "VARCHAR(20) NOT NULL DEFAULT 'approved'"
                ))
            rows = conn.execute(text("PRAGMA table_info(courses)")).fetchall()
            course_columns = {row[1] for row in rows}
            for name in ("archived_at", "deleted_at"):
                if rows and name not in course_columns:
                    conn.execute(text(f"ALTER TABLE courses ADD COLUMN {name} DATETIME NULL"))
            rows = conn.execute(text("PRAGMA table_info(assignments)")).fetchall()
            if rows and "allow_late" not in {row[1] for row in rows}:
                conn.execute(text(
                    "ALTER TABLE assignments ADD COLUMN allow_late "
                    "BOOLEAN NOT NULL DEFAULT 0"
                ))
            rows = conn.execute(text("PRAGMA table_info(submissions)")).fetchall()
            submission_columns = {row[1] for row in rows}
            if rows and "status" not in submission_columns:
                conn.execute(text(
                    "ALTER TABLE submissions ADD COLUMN status "
                    "VARCHAR(20) NOT NULL DEFAULT 'submitted'"
                ))
            if rows and "submitted_at" not in submission_columns:
                conn.execute(text(
                    "ALTER TABLE submissions ADD COLUMN submitted_at DATETIME NULL"
                ))
            rows = conn.execute(text("PRAGMA table_info(interview_assignments)")).fetchall()
            if rows and "duration_minutes" not in {row[1] for row in rows}:
                conn.execute(text(
                    "ALTER TABLE interview_assignments ADD COLUMN duration_minutes "
                    "INTEGER NOT NULL DEFAULT 30"
                ))
            rows = conn.execute(text("PRAGMA table_info(interview_records)")).fetchall()
            interview_columns = {row[1] for row in rows}
            interview_ddl = {
                "assignment_id": "BIGINT NULL",
                "score_dimensions": "TEXT NULL",
                "visibility": "VARCHAR(20) NOT NULL DEFAULT 'private'",
            }
            for name, ddl in interview_ddl.items():
                if rows and name not in interview_columns:
                    conn.execute(text(f"ALTER TABLE interview_records ADD COLUMN {name} {ddl}"))
            rows = conn.execute(text("PRAGMA table_info(conversations)")).fetchall()
            if rows and "security_level" not in {row[1] for row in rows}:
                conn.execute(text(
                    "ALTER TABLE conversations ADD COLUMN security_level VARCHAR(20) NULL"
                ))
            rows = conn.execute(text("PRAGMA table_info(chat_messages)")).fetchall()
            if rows and "request_id" not in {row[1] for row in rows}:
                conn.execute(text(
                    "ALTER TABLE chat_messages ADD COLUMN request_id VARCHAR(64) NULL"
                ))
    except Exception:  # 迁移失败不阻断启动
        pass


def _seed_legacy_enrollments():
    """把既有学情档案迁移为选课关系,保证老学生仍能看到原课程(幂等)"""
    from app.models.profile import StudentProfile
    from app.models.classroom import CourseEnrollment

    db = SessionLocal()
    try:
        existing = {
            (cid, uid)
            for cid, uid in db.query(
                CourseEnrollment.course_id, CourseEnrollment.student_id
            ).all()
        }
        rows = db.query(StudentProfile.user_id, StudentProfile.course_id).all()
        added = 0
        for user_id, course_id in rows:
            if (course_id, user_id) in existing:
                continue
            db.add(CourseEnrollment(
                course_id=course_id, student_id=user_id, source="legacy",
            ))
            added += 1
        if added:
            db.commit()
    except Exception:  # 迁移失败不阻断启动
        db.rollback()
    finally:
        db.close()


def _seed_feature_configs():
    """写入灰度开关与配额缺省配置(幂等,已存在则跳过)"""
    from app.services.feature_flags import seed_defaults

    db = SessionLocal()
    try:
        seed_defaults(db)
    except Exception:  # 配置写入失败不阻断启动
        db.rollback()
    finally:
        db.close()


def _migrate_exam_record_columns():
    """为既有 MySQL 库补齐考试、错题来源字段与唯一索引(幂等)"""
    if engine.dialect.name == "sqlite":
        _migrate_sqlite_columns()
        return
    if engine.dialect.name != "mysql":
        return
    table_columns = {
        "exam_records": {
            "short_scores": "TEXT NULL COMMENT '简答得分 JSON'",
            "ai_suggestions": "TEXT NULL COMMENT 'AI 简答评分建议 JSON'",
            "graded_at": "DATETIME NULL COMMENT '简答批改时间'",
            "graded_by": "BIGINT NULL COMMENT '批改教师'",
            "violations": "INT NOT NULL DEFAULT 0 COMMENT '切屏次数'",
            "timed_out": "TINYINT(1) NOT NULL DEFAULT 0 COMMENT '超时提交'",
            "client_id": "VARCHAR(128) NULL COMMENT '提交答卷的考试客户端'",
            "copy_count": "INT NOT NULL DEFAULT 0 COMMENT '复制次数'",
            "paste_count": "INT NOT NULL DEFAULT 0 COMMENT '粘贴次数'",
        },
        "exam_sessions": {
            "client_id": "VARCHAR(128) NULL COMMENT '绑定的考试客户端'",
            "copy_count": "INT NOT NULL DEFAULT 0 COMMENT '复制次数'",
            "paste_count": "INT NOT NULL DEFAULT 0 COMMENT '粘贴次数'",
        },
        "wrong_questions": {
            "source_type": "VARCHAR(30) NULL COMMENT 'manual/exam_record 等来源'",
            "source_id": "VARCHAR(100) NULL COMMENT '来源内唯一标识'",
        },
        "users": {
            "token_version": "INT NOT NULL DEFAULT 0 COMMENT '令牌版本号'",
            "avatar_url": "VARCHAR(255) NULL COMMENT '头像相对路径'",
        },
        "interaction_logs": {
            "security_level": "VARCHAR(20) NULL COMMENT '信息分级结果'",
        },
        "conversations": {
            "is_favorite": "TINYINT(1) NOT NULL DEFAULT 0 COMMENT '是否收藏'",
            "summary": "TEXT NULL COMMENT '会话摘要缓存'",
            "summarized_at": "DATETIME NULL COMMENT '摘要生成时间'",
            "security_level": "VARCHAR(20) NULL COMMENT '人工信息分级覆盖'",
        },
        "chat_messages": {
            "request_id": "VARCHAR(64) NULL COMMENT '前端幂等键，用于断线续答/重试去重'",
        },
        "class_members": {
            "role": "VARCHAR(20) NOT NULL DEFAULT 'student' COMMENT 'teacher/student/monitor/representative/custom'",
            "title": "VARCHAR(50) NULL COMMENT '班级内头衔'",
            "permissions": "TEXT NULL COMMENT '自定义角色权限 JSON'",
            "invited_by": "BIGINT NULL COMMENT '邀请人'",
        },
        "classes": {
            "max_students": "INT NOT NULL DEFAULT 100 COMMENT '班级学生容量上限'",
        },
        "upload_events": {
            "duration_seconds": "DOUBLE NOT NULL DEFAULT 0 COMMENT '音频时长(秒)'",
        },
        "course_materials": {
            "moderation_status": "VARCHAR(20) NOT NULL DEFAULT 'approved' COMMENT '内容审核:pending/approved/rejected'",
        },
        "courses": {
            "archived_at": "DATETIME NULL COMMENT '归档时间'",
            "deleted_at": "DATETIME NULL COMMENT '软删除时间'",
        },
        "assignments": {
            "allow_late": "TINYINT(1) NOT NULL DEFAULT 0 COMMENT '截止后允许正式补交'",
        },
        "submissions": {
            "status": "VARCHAR(20) NOT NULL DEFAULT 'submitted' COMMENT 'draft/submitted'",
            "submitted_at": "DATETIME NULL COMMENT '正式提交时间'",
        },
        "interview_assignments": {
            "duration_minutes": "INT NOT NULL DEFAULT 30 COMMENT '面试时长(分钟)'",
        },
        "interview_records": {
            "assignment_id": "BIGINT NULL COMMENT '来源面试作业'",
            "score_dimensions": "TEXT NULL COMMENT '四维评分 JSON'",
            "visibility": "VARCHAR(20) NOT NULL DEFAULT 'private' COMMENT 'private/teacher'",
        },
    }
    from sqlalchemy import text

    try:
        with engine.begin() as conn:
            for table, columns in table_columns.items():
                existing = {
                    row[0] for row in conn.execute(text(f"SHOW COLUMNS FROM {table}"))
                }
                for name, ddl in columns.items():
                    if name not in existing:
                        conn.execute(text(
                            f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"
                        ))
            indexes = {
                row[2] for row in conn.execute(text("SHOW INDEX FROM wrong_questions"))
            }
            if "uq_wrong_question_source" not in indexes:
                conn.execute(text(
                    "CREATE UNIQUE INDEX uq_wrong_question_source "
                    "ON wrong_questions (profile_id, source_type, source_id)"
                ))
            # 新课程默认待审核(仅改默认值,不影响存量课程状态)
            conn.execute(text(
                "ALTER TABLE courses ALTER COLUMN audit_status SET DEFAULT 'pending'"
            ))
    except Exception:  # 迁移失败不阻断启动
        pass
