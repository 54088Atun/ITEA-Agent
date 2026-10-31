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
        upload_event, log, notification,
    )
    Base.metadata.create_all(bind=engine)
    _migrate_exam_record_columns()
    _seed_legacy_enrollments()
    _seed_feature_configs()


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
    except Exception:  # 迁移失败不阻断启动
        pass
