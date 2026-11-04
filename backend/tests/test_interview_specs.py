import asyncio
import json
from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.agent.nodes.interview as interview_module
import app.agent.nodes.memory as memory_module
import app.api.chat as chat_api
import app.api.student as student_api
import app.api.teacher as teacher_api
import app.db.session as db_session
from app.db.session import Base
from app.models.classroom import ClassMember, Classroom, CourseEnrollment
from app.models.course import Course
from app.models.interview import InterviewRecord
from app.models.interview_assignment import InterviewAssignment
from app.models.profile import StudentProfile
from app.models.user import User
from app.schemas.agent import ChatRequest
from app.schemas.student import InterviewStartRequest
from app.schemas.teacher import InterviewAssignmentCreate
from app.services.feature_flags import seed_defaults


@pytest.fixture()
def db(monkeypatch):
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine)
    session = TestingSession()
    seed(session)
    seed_defaults(session)
    monkeypatch.setattr(chat_api, "SessionLocal", TestingSession)
    monkeypatch.setattr(memory_module, "SessionLocal", TestingSession)
    monkeypatch.setattr(chat_api, "_sessions", {})
    monkeypatch.setattr(chat_api, "_session_owner", {})
    monkeypatch.setattr(chat_api, "_answers", {})
    yield session
    session.close()
    engine.dispose()


def seed(db):
    db.add_all([
        User(id=1, role="teacher", name="张老师", email="t1@example.com",
             password_hash="x", status="active"),
        User(id=2, role="teacher", name="李老师", email="t2@example.com",
             password_hash="x", status="active"),
        User(id=3, role="student", name="小明", email="s1@example.com",
             password_hash="x", status="active"),
        User(id=4, role="student", name="小红", email="s2@example.com",
             password_hash="x", status="active"),
        Course(id=10, teacher_id=1, name="软件测试", code="ST101", audit_status="approved"),
        Course(id=11, teacher_id=2, name="数据结构", code="DS101", audit_status="approved"),
        Classroom(id=20, teacher_id=1, course_id=10, name="测试一班", invite_code="ABCD1234"),
        StudentProfile(id=50, user_id=3, course_id=10),
        StudentProfile(id=51, user_id=4, course_id=10),
        StudentProfile(id=52, user_id=4, course_id=11),
        InterviewAssignment(id=60, teacher_id=1, course_id=10, title="测试面试"),
        InterviewAssignment(id=61, teacher_id=2, course_id=11, title="数据结构面试"),
    ])
    db.add_all([
        ClassMember(class_id=20, student_id=3, status="active"),
        ClassMember(class_id=20, student_id=4, status="active"),
        CourseEnrollment(course_id=10, student_id=3, source="class", class_id=20),
        CourseEnrollment(course_id=10, student_id=4, source="class", class_id=20),
        CourseEnrollment(course_id=11, student_id=4, source="self"),
    ])
    db.commit()


def _events(frames):
    return [json.loads(frame[6:]) for frame in frames]


async def _collect_response(response):
    return [frame async for frame in response.body_iterator]


async def _collect_stream(stream):
    return [frame async for frame in stream]


class FakeGraph:
    def __init__(self):
        self.calls = 0
        self.states = []

    async def astream(self, state, stream_mode, config=None):
        self.calls += 1
        self.states.append(state)
        yield {"interview": {"final_output": "面试回复"}}


def test_interview_assignment_duration_default_custom_and_range(db):
    teacher = db.get(User, 1)
    default = teacher_api.create_interview_assignment(
        InterviewAssignmentCreate(title="默认时长", course_id=10), teacher, db,
    )
    assert default["duration_minutes"] == 30

    custom = teacher_api.create_interview_assignment(
        InterviewAssignmentCreate(title="四十五分钟", course_id=10, duration_minutes=45),
        teacher, db,
    )
    assert custom["duration_minutes"] == 45
    assert db.get(InterviewAssignment, custom["id"]).duration_minutes == 45

    for value in (0, 121):
        with pytest.raises(ValidationError):
            InterviewAssignmentCreate(title="非法时长", course_id=10, duration_minutes=value)


def test_start_interview_rejects_assignment_not_visible_to_student(db):
    req = InterviewStartRequest(course_id=10, assignment_id=61)
    with pytest.raises(HTTPException) as exc:
        student_api.start_interview(req, None, db.get(User, 3), db)
    assert exc.value.status_code == 403


@pytest.mark.parametrize("from_assignment,duration,elapsed", [(False, 30, 31), (True, 45, 46)])
def test_interview_time_limit_blocks_answers_but_allows_summary(
    db, monkeypatch, from_assignment, duration, elapsed,
):
    assignment_id = None
    if from_assignment:
        created = teacher_api.create_interview_assignment(
            InterviewAssignmentCreate(title="限时面试", course_id=10, duration_minutes=duration),
            db.get(User, 1), db,
        )
        assignment_id = created["id"]

    graph = FakeGraph()
    monkeypatch.setattr(chat_api, "get_graph", lambda: graph)

    async def fake_log(*args, **kwargs):
        return None

    monkeypatch.setattr(chat_api, "_log_interaction", fake_log)
    now = {"value": datetime(2026, 1, 1, 12, 0, 0)}

    class Clock:
        @classmethod
        def utcnow(cls):
            return now["value"]

    monkeypatch.setattr(chat_api, "datetime", Clock)
    student = db.get(User, 3)
    response = student_api.start_interview(
        InterviewStartRequest(course_id=10, assignment_id=assignment_id), None, student, db,
    )
    events = _events(asyncio.run(_collect_response(response)))
    session_id = events[-1]["data"]["session_id"]
    assert graph.states[0]["interview_assignment_id"] == assignment_id

    now["value"] += timedelta(minutes=elapsed)
    calls_before_answer = graph.calls
    answer_req = ChatRequest(
        session_id=session_id, course_id=10, message="我继续回答",
        interview_assignment_id=assignment_id,
    )
    answer_events = _events(asyncio.run(_collect_stream(
        chat_api.stream_agent_response(answer_req, student, db),
    )))
    assert graph.calls == calls_before_answer
    assert answer_events[0]["type"] == "error"
    assert "时长" in answer_events[0]["data"]["message"]
    assert answer_events[-1]["data"]["session_id"] == session_id

    summary_req = ChatRequest(
        session_id=session_id, course_id=10, message="结束面试，请总结",
        interview_assignment_id=assignment_id,
    )
    summary_events = _events(asyncio.run(_collect_stream(
        chat_api.stream_agent_response(summary_req, student, db),
    )))
    assert graph.calls == calls_before_answer + 1
    assert any(event["type"] == "token" for event in summary_events)


def _mock_interview_dependencies(monkeypatch, output):
    async def fake_llm(messages, sink=None):
        return output

    monkeypatch.setattr(interview_module, "llm_invoke", fake_llm)
    monkeypatch.setattr(interview_module, "fetch_profile", lambda *args: {"mastery": []})
    monkeypatch.setattr(
        interview_module, "fetch_course_evidence",
        lambda *args: {"context": "", "fragments": []},
    )


def _agent_state(assignment_id=None):
    return {
        "user_id": 3,
        "user_role": "student",
        "course_id": 10,
        "messages": [{"role": "user", "content": "结束面试，请总结"}],
        "stream_queue": None,
        "interview_assignment_id": assignment_id,
    }


def test_four_dimensional_scores_and_full_feedback_are_persisted(db, monkeypatch):
    output = """专业知识：88分
逻辑表达：82分
岗位匹配：91分
沟通应答：86分
综合评分：87分
完整反馈：基础扎实，但应加强场景分析。"""
    _mock_interview_dependencies(monkeypatch, output)
    state = _agent_state(assignment_id=60)

    result = asyncio.run(interview_module.interview_node(state))
    state["profile_updates"] = result["profile_updates"]
    memory_module.memory_write_node(state)

    record = db.query(InterviewRecord).filter_by(profile_id=50).one()
    assert record.assignment_id == 60
    assert record.score == 87
    assert json.loads(record.score_dimensions) == {
        "专业知识": 88, "逻辑表达": 82, "岗位匹配": 91, "沟通应答": 86,
    }
    assert output in record.feedback
    assert record.visibility == "teacher"


def test_unparseable_scores_stay_empty_and_self_interview_is_private(db, monkeypatch):
    output = "整体表现不错，建议继续复习，但未给出可解析分数。"
    _mock_interview_dependencies(monkeypatch, output)
    state = _agent_state()

    result = asyncio.run(interview_module.interview_node(state))
    state["profile_updates"] = result["profile_updates"]
    memory_module.memory_write_node(state)

    record = db.query(InterviewRecord).filter_by(profile_id=50).one()
    assert record.assignment_id is None
    assert record.score is None
    assert json.loads(record.score_dimensions) == {
        "专业知识": None, "逻辑表达": None, "岗位匹配": None, "沟通应答": None,
    }
    assert output in record.feedback
    assert record.visibility == "private"


def test_student_visibility_toggle_and_teacher_read_scope(db):
    from app.schemas import student as student_schemas

    rows = [
        InterviewRecord(id=1, profile_id=50, round=1, question="授权课程记录",
                        assignment_id=60, visibility="teacher", score=80),
        InterviewRecord(id=2, profile_id=50, round=2, question="私有自选记录",
                        visibility="private", score=70),
        InterviewRecord(id=3, profile_id=52, round=1, question="其他教师课程记录",
                        assignment_id=61, visibility="teacher", score=90),
        InterviewRecord(id=4, profile_id=50, round=3, question="授权作业记录",
                        assignment_id=61, visibility="teacher", score=85),
    ]
    db.add_all(rows)
    db.commit()

    teacher1_ids = {
        row["id"] for row in teacher_api.list_shared_interview_records(
            teacher=db.get(User, 1), db=db,
        )
    }
    assert teacher1_ids == {1, 4}
    teacher2_ids = {
        row["id"] for row in teacher_api.list_shared_interview_records(
            teacher=db.get(User, 2), db=db,
        )
    }
    assert teacher2_ids == {3, 4}

    updated = student_api.update_interview_visibility(
        2, student_schemas.InterviewVisibilityUpdate(visibility="teacher"),
        db.get(User, 3), db,
    )
    assert updated.visibility == "teacher"
    assert 2 in {
        row["id"] for row in teacher_api.list_shared_interview_records(
            teacher=db.get(User, 1), db=db,
        )
    }

    with pytest.raises(HTTPException) as exc:
        student_api.update_interview_visibility(
            2, student_schemas.InterviewVisibilityUpdate(visibility="private"),
            db.get(User, 4), db,
        )
    assert exc.value.status_code == 404
    assert db.get(InterviewRecord, 2).visibility == "teacher"

    student_api.update_interview_visibility(
        2, student_schemas.InterviewVisibilityUpdate(visibility="private"),
        db.get(User, 3), db,
    )
    assert 2 not in {
        row["id"] for row in teacher_api.list_shared_interview_records(
            teacher=db.get(User, 1), db=db,
        )
    }


def test_sqlite_interview_migration_is_idempotent(monkeypatch):
    engine = create_engine("sqlite:///:memory:", poolclass=StaticPool)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE interview_assignments (id INTEGER PRIMARY KEY)"))
        conn.execute(text(
            "CREATE TABLE interview_records (id INTEGER PRIMARY KEY, "
            "profile_id INTEGER NOT NULL, round INTEGER NOT NULL, question TEXT NOT NULL)"
        ))
    monkeypatch.setattr(db_session, "engine", engine)

    db_session._migrate_sqlite_columns()
    db_session._migrate_sqlite_columns()

    with engine.begin() as conn:
        assignment_columns = {
            row[1] for row in conn.execute(text("PRAGMA table_info(interview_assignments)"))
        }
        record_columns = {
            row[1] for row in conn.execute(text("PRAGMA table_info(interview_records)"))
        }
    assert "duration_minutes" in assignment_columns
    assert {"assignment_id", "score_dimensions", "visibility"} <= record_columns
    engine.dispose()
