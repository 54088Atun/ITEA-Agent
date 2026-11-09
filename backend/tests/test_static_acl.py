"""静态文件逐文件归属:上传图片/录音、课程素材与生成文档的访问控制"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.session import Base
from app.models.classroom import CourseCollaborator, CourseEnrollment
from app.models.course import Course
from app.models.user import User
from app.services.static_acl import is_static_allowed


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    session.add_all([
        User(id=1, role="teacher", name="授课教师", email="t1@example.com",
             password_hash="x", status="active"),
        User(id=2, role="teacher", name="协作教师", email="t2@example.com",
             password_hash="x", status="active"),
        User(id=3, role="student", name="选课学生", email="s1@example.com",
             password_hash="x", status="active"),
        User(id=4, role="student", name="其他学生", email="s2@example.com",
             password_hash="x", status="active"),
        User(id=5, role="admin", name="管理员", email="a@example.com",
             password_hash="x", status="active"),
        Course(id=10, teacher_id=1, name="软件测试", code="ST101",
               audit_status="approved"),
        Course(id=11, teacher_id=1, name="待审课程", code="ST102",
               audit_status="pending"),
    ])
    session.add_all([
        CourseCollaborator(course_id=10, teacher_id=2, added_by=1),
        CourseEnrollment(course_id=10, student_id=3, source="class"),
        CourseEnrollment(course_id=11, student_id=3, source="class"),
    ])
    session.commit()
    yield session
    session.close()
    engine.dispose()


def _user(db, uid):
    return db.get(User, uid)


def test_vision_and_audio_are_owner_only(db):
    path = "/uploads/vision/3/abc.png"
    assert is_static_allowed(path, _user(db, 3), db) is True
    assert is_static_allowed(path, _user(db, 4), db) is False
    assert is_static_allowed(path, _user(db, 1), db) is False
    # 管理员也不能浏览学生私有图片
    assert is_static_allowed(path, _user(db, 5), db) is False

    audio = "/uploads/audio/3/tmp.webm"
    assert is_static_allowed(audio, _user(db, 3), db) is True
    assert is_static_allowed(audio, _user(db, 4), db) is False


def test_avatar_readable_by_logged_in_users(db):
    path = "/uploads/avatar/3.png"
    for uid in (1, 2, 3, 4, 5):
        assert is_static_allowed(path, _user(db, uid), db) is True


def test_course_material_follows_course_visibility(db):
    path = "/uploads/10/slides.pdf"
    # 课程拥有者、协作者、管理员、选课学生
    for uid in (1, 2, 3, 5):
        assert is_static_allowed(path, _user(db, uid), db) is True
    # 未选课学生看不到
    assert is_static_allowed(path, _user(db, 4), db) is False

    # 未过审课程的素材对学生关闭
    pending = "/uploads/11/slides.pdf"
    assert is_static_allowed(pending, _user(db, 3), db) is False


def test_course_drafts_teacher_only(db):
    path = "/uploads/10/drafts/draft.docx"
    assert is_static_allowed(path, _user(db, 1), db) is True
    assert is_static_allowed(path, _user(db, 2), db) is True
    assert is_static_allowed(path, _user(db, 5), db) is True
    assert is_static_allowed(path, _user(db, 3), db) is False


def test_traversal_segments_are_rejected(db):
    assert is_static_allowed(
        "/uploads/vision/3/../../4/secret.png", _user(db, 3), db,
    ) is False
    assert is_static_allowed(
        "/static/generated/3/../4/x.docx", _user(db, 3), db,
    ) is False


def test_generated_documents_are_owner_only(db):
    assert is_static_allowed(
        "/static/generated/3/lesson_plan_a.docx", _user(db, 3), db,
    ) is True
    assert is_static_allowed(
        "/static/generated/3/lesson_plan_a.docx", _user(db, 4), db,
    ) is False
    assert is_static_allowed(
        "/generated/3/class_report_a.xlsx", _user(db, 4), db,
    ) is False
    # 历史无归属目录的旧文件保持登录可读
    assert is_static_allowed(
        "/static/generated/legacy_file.docx", _user(db, 4), db,
    ) is True


def test_unknown_upload_dir_stays_login_readable(db):
    assert is_static_allowed(
        "/uploads/legacy/notes.txt", _user(db, 4), db,
    ) is True
