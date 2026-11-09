"""AG-12 收尾:RAG 片段携带素材 ID/页码,来源可点击定位到原文"""
import importlib

import pytest
from fastapi import HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.agent.sources import build_sources, render_footer

# 包内同名导出会遮蔽子模块,这里显式取模块本身
rag_module = importlib.import_module("app.agent.tools.rag_search")
from app.api.course import preview_material
from app.db.session import Base
from app.models.classroom import CourseEnrollment
from app.models.course import Course, CourseMaterial
from app.models.user import User
from app.services.material_parser import extract_text_with_pages


def test_chunk_spans_match_chunk_text():
    text = "a" * 1200
    spans = rag_module.RAGManager.chunk_spans(text)
    chunks = rag_module.RAGManager.chunk_text(text)

    assert [text[start:end] for start, end in spans] == chunks
    assert spans[0] == (0, 500)
    # 与原有切片语义一致:重叠 50 字
    assert spans[1][0] == 450


def test_page_of_offset_maps_page():
    spans = [
        {"page": 1, "start": 0, "end": 100},
        {"page": 2, "start": 101, "end": 200},
    ]
    assert rag_module.RAGManager.page_of_offset(spans, 0) == 1
    assert rag_module.RAGManager.page_of_offset(spans, 150) == 2
    assert rag_module.RAGManager.page_of_offset([], 10) is None


def test_extract_text_with_pages_non_pdf_uses_first_page(tmp_path):
    path = tmp_path / "note.md"
    path.write_text("课程知识", encoding="utf-8")

    text, spans = extract_text_with_pages(path, "note.md")

    assert text == "课程知识"
    assert spans == [{"page": 1, "start": 0, "end": 4}]


def test_build_sources_uses_fragment_material_and_page():
    fragments = [
        {"source": "第3章_二叉树.pdf", "material_id": 12, "page": 3},
        {"source": "第3章_二叉树.pdf", "material_id": 12, "page": 3},
        {"source": "实验指导.docx", "material_id": 13, "page": 1},
    ]
    sources = build_sources("", fragments=fragments, course_id=10)
    course_items = [item for item in sources if item["type"] == "course"]

    assert len(course_items) == 2
    assert course_items[0]["label"] == "第3章_二叉树.pdf 第 3 页"
    assert course_items[0]["url"] == "/api/course/10/materials/12/preview#page=3"
    footer = render_footer(sources)
    assert "[第3章_二叉树.pdf 第 3 页](/api/course/10/materials/12/preview#page=3)" in footer


def test_rag_search_keeps_fragment_metadata(monkeypatch):
    class _FakeManager:
        def search(self, query, course_id, scope, top_k):
            return [{
                "text": "二叉树的中序遍历", "source": "讲义.pdf", "scope": "courseware",
                "score": 0.9, "material_id": 7, "page": 2, "chunk_index": 1,
            }]

    monkeypatch.setattr(rag_module, "get_manager", lambda: _FakeManager())
    monkeypatch.setattr(rag_module, "agent_course_scope_error", lambda *a, **k: None)
    result = rag_module.rag_search("遍历", 10, user_id=1, top_k=3)

    assert "[1] (来源: 讲义.pdf)" in result["context"]
    assert result["fragments"][0]["material_id"] == 7
    assert result["fragments"][0]["page"] == 2


@pytest.fixture()
def scope_env(monkeypatch):
    """真实 SQLite 会话,用于验证工具层的课程范围强校验"""
    from app.services import course_access

    engine = create_engine("sqlite:///:memory:", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    db.add_all([
        User(id=1, role="student", name="已选课", email="s1@example.com",
             password_hash="x", status="active"),
        User(id=2, role="teacher", name="张老师", email="t1@example.com",
             password_hash="x", status="active"),
        User(id=3, role="student", name="未选课", email="s2@example.com",
             password_hash="x", status="active"),
        Course(id=10, teacher_id=2, name="数据结构", code="CS101",
               audit_status="approved"),
        Course(id=11, teacher_id=2, name="算法", code="CS102",
               audit_status="approved"),
        CourseEnrollment(course_id=10, student_id=1, source="self"),
    ])
    db.commit()

    monkeypatch.setattr(course_access, "SessionLocal", Session)
    yield db
    db.close()
    engine.dispose()


def test_rag_search_requires_user_context(scope_env, monkeypatch):
    monkeypatch.setattr(rag_module, "get_manager", lambda: object())

    result = rag_module.rag_search("遍历", 10)

    assert "用户上下文" in result["error"]
    assert result["fragments"] == []


def test_rag_search_rejects_course_outside_scope(scope_env, monkeypatch):
    monkeypatch.setattr(rag_module, "get_manager", lambda: object())

    result = rag_module.rag_search("遍历", 11, user_id=3)

    assert "无权访问该课程" in result["error"]
    assert result["fragments"] == []


def test_rag_search_allows_enrolled_student(scope_env, monkeypatch):
    class _FakeManager:
        def search(self, query, course_id, scope, top_k):
            return [{"text": "红黑树", "source": "讲义.pdf", "scope": "courseware"}]

    monkeypatch.setattr(rag_module, "get_manager", lambda: _FakeManager())

    result = rag_module.rag_search("红黑树", 10, user_id=1)

    assert "error" not in result
    assert result["fragments"][0]["text"] == "红黑树"


def test_stats_analyzer_rejects_course_outside_scope(scope_env):
    stats_module = importlib.import_module("app.agent.tools.stats_analyzer")

    result = stats_module.stats_analyzer(11, "weakness", user_id=3)

    assert "无权访问该课程" in result["error"]


@pytest.fixture()
def preview_env(tmp_path):
    engine = create_engine("sqlite:///:memory:", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    material_file = tmp_path / "讲义.pdf"
    material_file.write_bytes(b"%PDF-1.4 test")
    db.add_all([
        User(id=1, role="student", name="小明", email="s1@example.com",
             password_hash="x", status="active"),
        User(id=2, role="teacher", name="张老师", email="t1@example.com",
             password_hash="x", status="active"),
        User(id=3, role="student", name="小红", email="s2@example.com",
             password_hash="x", status="active"),
        Course(id=10, teacher_id=2, name="数据结构", code="CS101", audit_status="approved"),
        Course(id=11, teacher_id=2, name="算法", code="CS102", audit_status="approved"),
        CourseEnrollment(course_id=10, student_id=1, source="self"),
        CourseMaterial(id=50, course_id=10, type="courseware", title="讲义",
                       file_path=str(material_file), chunk_count=1),
        CourseMaterial(id=51, course_id=11, type="courseware", title="别的",
                       file_path=str(material_file), chunk_count=1),
    ])
    db.commit()
    yield db
    db.close()
    engine.dispose()


def test_preview_material_inline_for_enrolled_student(preview_env):
    response = preview_material(10, 50, preview_env.get(User, 1), preview_env)

    assert isinstance(response, FileResponse)
    assert response.media_type == "application/pdf"
    assert "inline" in response.headers["content-disposition"]


def test_preview_material_rejects_unenrolled_student(preview_env):
    with pytest.raises(HTTPException) as exc:
        preview_material(10, 50, preview_env.get(User, 3), preview_env)

    assert exc.value.status_code == 403


def test_preview_material_rejects_cross_course_material(preview_env):
    with pytest.raises(HTTPException) as exc:
        preview_material(10, 51, preview_env.get(User, 1), preview_env)

    assert exc.value.status_code == 404


# ---------- 索引重建与词法检索(生产无向量依赖时的兜底) ----------

def test_lexical_search_without_vector_deps(tmp_path, monkeypatch):
    monkeypatch.setattr(rag_module.settings, "RAG_VECTOR_ENABLED", False)
    manager = rag_module.RAGManager()
    manager._index_dir = str(tmp_path)

    documents = [
        {"content": "二叉树的中序遍历顺序是左子树、根节点、右子树。",
         "source": "第3章_二叉树.pdf", "scope": "courseware", "material_id": 7},
        {"content": "进程调度算法包括先来先服务、短作业优先与时间片轮转。",
         "source": "第4章_操作系统.pdf", "scope": "courseware", "material_id": 8},
    ]

    assert manager.build_index(10, documents) == 2
    assert manager.index_ready(10)

    hits = manager.search("二叉树的中序遍历", 10, top_k=1)
    assert hits and hits[0]["material_id"] == 7
    assert hits[0]["source"] == "第3章_二叉树.pdf"

    # 范围过滤与无关问题都不伪造来源
    assert manager.search("进程调度", 10, scope="syllabus") == []
    assert manager.search("量子纠缠实验", 10) == []


def test_rebuild_course_index_after_material_parse(scope_env, tmp_path, monkeypatch):
    from app.services.material_parse_jobs import enqueue, run_parse_job

    manager = rag_module.RAGManager()
    manager._index_dir = str(tmp_path)
    monkeypatch.setattr(rag_module, "_manager", manager)

    path = tmp_path / "第1章_基础.txt"
    path.write_text("等价类划分与边界值分析用于设计测试用例", encoding="utf-8")
    material = CourseMaterial(
        course_id=10, type="courseware", title="第1章_基础",
        file_path=str(path), chunk_count=0, moderation_status="pending",
    )
    scope_env.add(material)
    scope_env.commit()
    scope_env.refresh(material)

    job = enqueue(scope_env, material)
    done = run_parse_job(scope_env, job.id)
    scope_env.refresh(material)

    assert done.status == "done"
    assert material.chunk_count == 1
    assert manager.index_ready(10)
    hits = manager.search("边界值分析", 10, top_k=1)
    assert hits and hits[0]["material_id"] == material.id
    assert hits[0]["source"] == "第1章_基础"
