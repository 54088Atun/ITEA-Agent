"""CL-08 班级角色与权限测试

覆盖:
- 班主任/任课教师在班级内的不同权限
- 任课教师可邀请成员、授予课代表、设置自己头衔;不能踢人/授予班长
- 班主任可邀请教师/学生,赋予班长/课代表/自定义权限
- 角色切换同步课程可见性
- 成员列表返回角色、头衔、权限
"""
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.classroom import (
    assign_member_role, create_announcement, create_class, invite_member,
    list_announcements, list_classes, list_members, permission_catalog,
    remove_member, set_my_title,
)
from app.db.session import Base
from app.models.classroom import ClassMember, Classroom, CourseEnrollment
from app.models.course import Course
from app.models.user import User
from app.schemas.classroom import (
    AnnouncementCreate, ClassCreate, ClassInviteRequest, ClassMemberRoleUpdate,
    ClassSelfTitleUpdate,
)
from app.services import class_roles


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    seed(session)
    yield session
    session.close()
    engine.dispose()


def seed(db):
    db.add_all([
        User(id=1, role="teacher", name="班主任", email="head@example.com",
             password_hash="x", status="active"),
        User(id=2, role="teacher", name="任课老师", email="teacher2@example.com",
             password_hash="x", status="active"),
        User(id=3, role="teacher", name="其他老师", email="teacher3@example.com",
             password_hash="x", status="active"),
        User(id=4, role="student", name="学生甲", email="s1@example.com",
             password_hash="x", status="active"),
        User(id=5, role="student", name="学生乙", email="s2@example.com",
             password_hash="x", status="active"),
        Course(id=10, teacher_id=1, name="软件测试", code="ST101",
               audit_status="approved"),
    ])
    db.commit()


def _class(db):
    return create_class(ClassCreate(name="测试班", course_id=10), db.get(User, 1), db)


def test_head_can_invite_teacher_and_students(db):
    classroom = _class(db)
    head = db.get(User, 1)

    teacher_member = invite_member(
        classroom.id,
        ClassInviteRequest(email="teacher2@example.com", role="teacher", title="数据结构教师"),
        head, db,
    )
    assert teacher_member.role == "teacher"
    assert teacher_member.title == "数据结构教师"
    assert teacher_member.member_type == "teacher"
    # 教师成员不获得课程选课关系
    assert db.query(CourseEnrollment).filter_by(
        course_id=10, student_id=2).first() is None

    monitor = invite_member(
        classroom.id,
        ClassInviteRequest(email="s1@example.com", role="monitor", title="班长"),
        head, db,
    )
    assert monitor.role == "monitor"
    assert db.query(CourseEnrollment).filter_by(course_id=10, student_id=4).first()


def test_teacher_member_permissions(db):
    classroom = _class(db)
    head = db.get(User, 1)
    teacher2 = db.get(User, 2)
    invite_member(
        classroom.id,
        ClassInviteRequest(email="teacher2@example.com", role="teacher"),
        head, db,
    )
    invite_member(
        classroom.id,
        ClassInviteRequest(email="s1@example.com", role="student"),
        head, db,
    )

    # 可查看班级/成员、邀请学生、授予课代表
    assert [c.id for c in list_classes(teacher2, db)] == [classroom.id]
    members = list_members(classroom.id, teacher2, db)
    assert {m.student_id for m in members.items} == {2, 4}
    view = invite_member(
        classroom.id,
        ClassInviteRequest(email="s2@example.com", role="student"),
        teacher2, db,
    )
    assert view.role == "student"

    rep = assign_member_role(
        classroom.id, 4, ClassMemberRoleUpdate(role="representative"), teacher2, db,
    )
    assert rep.role == "representative"
    assert rep.title == "课代表"

    # 重复邀请不应隐式降级角色
    again = invite_member(
        classroom.id,
        ClassInviteRequest(email="s1@example.com", role="student"),
        teacher2, db,
    )
    assert again.role == "representative"

    own = set_my_title(
        classroom.id, ClassSelfTitleUpdate(title="软件测试教师"), teacher2, db,
    )
    assert own.title == "软件测试教师"

    # 不能授予班长/自定义,不能踢人
    with pytest.raises(HTTPException) as exc:
        assign_member_role(
            classroom.id, 4, ClassMemberRoleUpdate(role="monitor"), teacher2, db,
        )
    assert exc.value.status_code == 403
    with pytest.raises(HTTPException) as exc:
        invite_member(
            classroom.id,
            ClassInviteRequest(email="s2@example.com", role="monitor"),
            teacher2, db,
        )
    assert exc.value.status_code == 403
    with pytest.raises(HTTPException) as exc:
        remove_member(classroom.id, 4, teacher2, db)
    assert exc.value.status_code == 403


def test_custom_permissions_and_validation(db):
    classroom = _class(db)
    head = db.get(User, 1)
    invite_member(
        classroom.id,
        ClassInviteRequest(
            email="s2@example.com", role="custom", title="学习委员",
            permissions=["member.view", "notice.post"],
        ),
        head, db,
    )
    student = db.get(User, 5)
    perms = class_roles.permissions_of(db, db.get(Classroom, classroom.id), student)
    assert perms == {"member.view", "notice.post"}

    with pytest.raises(HTTPException) as exc:
        assign_member_role(
            classroom.id, 5,
            ClassMemberRoleUpdate(role="custom", permissions=["hack.all"]),
            head, db,
        )
    assert exc.value.status_code == 400


def test_role_switch_syncs_course_visibility(db):
    classroom = _class(db)
    head = db.get(User, 1)
    invite_member(
        classroom.id,
        ClassInviteRequest(email="s1@example.com", role="student"),
        head, db,
    )
    assert db.query(CourseEnrollment).filter_by(course_id=10, student_id=4).first()

    # 学生角色之间切换保留课程关系
    assign_member_role(
        classroom.id, 4, ClassMemberRoleUpdate(role="monitor"), head, db,
    )
    assert db.query(CourseEnrollment).filter_by(course_id=10, student_id=4).first()

    # 普通学生不能被设为任课教师
    with pytest.raises(HTTPException) as exc:
        assign_member_role(
            classroom.id, 4, ClassMemberRoleUpdate(role="teacher"), head, db,
        )
    assert exc.value.status_code == 400

    # 移出后收回课程关系
    remove_member(classroom.id, 4, head, db)
    assert db.query(CourseEnrollment).filter_by(course_id=10, student_id=4).first() is None


def test_only_head_can_remove_member(db):
    classroom = _class(db)
    head = db.get(User, 1)
    invite_member(
        classroom.id,
        ClassInviteRequest(email="s1@example.com", role="student"),
        head, db,
    )
    result = remove_member(classroom.id, 4, head, db)
    assert result["status"] == "left"
    member = db.query(ClassMember).filter_by(class_id=classroom.id, student_id=4).first()
    assert member.status == "left"


def test_permission_catalog(db):
    data = permission_catalog(db.get(User, 2))
    keys = {item["key"] for item in data["permissions"]}
    assert {"member.invite", "role.assign_representative", "notice.post"} <= keys
    assert data["roles"]["head_teacher"] == "班主任"


def test_announcements(db):
    classroom = _class(db)
    head = db.get(User, 1)
    teacher2 = db.get(User, 2)
    s1 = db.get(User, 4)
    s2 = db.get(User, 5)
    other_teacher = db.get(User, 3)

    invite_member(classroom.id, ClassInviteRequest(email="teacher2@example.com", role="teacher"),
                  head, db)
    invite_member(classroom.id, ClassInviteRequest(email="s1@example.com", role="student"),
                  head, db)
    invite_member(
        classroom.id,
        ClassInviteRequest(email="s2@example.com", role="custom",
                           permissions=["notice.post"]),
        head, db,
    )

    ann = create_announcement(
        classroom.id, AnnouncementCreate(content="  明天停课  "), head, db,
    )
    assert ann.content == "明天停课"
    assert ann.author_name == "班主任"

    # 任课教师无 notice.post,不能发公告
    with pytest.raises(HTTPException) as exc:
        create_announcement(
            classroom.id, AnnouncementCreate(content="越权公告"), teacher2, db,
        )
    assert exc.value.status_code == 403

    # 普通学生可查看
    items = list_announcements(classroom.id, s1, db)
    assert [a.content for a in items] == ["明天停课"]

    # 自定义角色被授予 notice.post 后可发布
    ann2 = create_announcement(
        classroom.id, AnnouncementCreate(content="学习委员通知"), s2, db,
    )
    assert ann2.author_id == 5

    # 非本班教师不可查看
    with pytest.raises(HTTPException) as exc:
        list_announcements(classroom.id, other_teacher, db)
    assert exc.value.status_code == 403
