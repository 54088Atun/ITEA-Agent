import io
import logging

from app.core.log_sanitizer import (
    SensitiveLogFilter, content_meta, mask_email, mask_emails, safe_exception,
)


def test_mask_email_keeps_only_first_local_character_and_domain():
    assert mask_email("alice@example.com") == "a***@example.com"


def test_mask_emails_sanitizes_every_email_in_text():
    text = "联系 alice@example.com 或 bob.smith+work@example.co.uk"
    assert mask_emails(text) == "联系 a***@example.com 或 b***@example.co.uk"


def test_mask_emails_handles_email_adjacent_to_chinese_text():
    assert mask_emails("联系alice@example.com谢谢") == "联系a***@example.com谢谢"


def test_content_meta_returns_only_character_count():
    assert content_meta("敏感正文") == "[内容已脱敏 chars=4]"


def test_safe_exception_returns_type_without_exception_body():
    result = safe_exception(RuntimeError("会话正文 secret@example.com"))
    assert result == "RuntimeError"
    assert "会话正文" not in result
    assert "secret@example.com" not in result


def test_sensitive_log_filter_masks_formatted_handler_output():
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.addFilter(SensitiveLogFilter())
    logger = logging.getLogger("tests.log_sanitizer.filter")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    logger.addHandler(handler)
    try:
        logger.info("联系 %s", "alice@example.com")
    finally:
        logger.removeHandler(handler)
        handler.close()

    output = stream.getvalue()
    assert "alice@example.com" not in output
    assert "a***@example.com" in output


def test_main_installs_sensitive_filter_on_root_handlers(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "LLM_API_KEY", "test-key")
    import app.main  # noqa: F401

    root_handlers = logging.getLogger().handlers
    assert root_handlers
    assert all(
        any(isinstance(item, SensitiveLogFilter) for item in handler.filters)
        for handler in root_handlers
    )


def test_auth_register_and_login_logs_use_masked_email(caplog, monkeypatch):
    from sqlalchemy import create_engine, event
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from app.api import auth as auth_api
    from app.db.session import Base
    from app.models.user import User
    from app.schemas.auth import LoginRequest, RegisterRequest

    engine = create_engine("sqlite:///:memory:", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()

    def assign_sqlite_id(session, context, instances):
        for item in session.new:
            if isinstance(item, User) and item.id is None:
                item.id = 1

    event.listen(db, "before_flush", assign_sqlite_id)
    email = "alice@example.com"
    masked_calls = []

    def spy_mask_email(value):
        masked_calls.append(value)
        return mask_email(value)

    monkeypatch.setattr(auth_api, "mask_email", spy_mask_email, raising=False)
    monkeypatch.setattr(auth_api, "hash_password", lambda password: "hashed")
    monkeypatch.setattr(auth_api, "verify_password", lambda password, hashed: True)
    monkeypatch.setattr(auth_api, "_token_response", lambda user: user)

    with caplog.at_level(logging.INFO, logger="app.api.auth"):
        auth_api.register(RegisterRequest(
            role="student", name="Alice", email=email, password="secret",
        ), db)
        auth_api.login(LoginRequest(email=email, password="secret"), db)

    assert masked_calls == [email, email]
    assert email not in caplog.text
    assert caplog.text.count("a***@example.com") == 2
    assert db.query(User).filter(User.email == email).count() == 1
    db.close()
    engine.dispose()


def test_chat_persistence_exception_log_omits_sensitive_body(caplog, monkeypatch):
    from app.api import chat as chat_api

    sensitive_body = "完整会话正文 secret@example.com"

    class FailingDB:
        rolled_back = False
        closed = False

        def query(self, *args):
            raise RuntimeError(sensitive_body)

        def rollback(self):
            self.rolled_back = True

        def close(self):
            self.closed = True

    db = FailingDB()
    monkeypatch.setattr(chat_api, "SessionLocal", lambda: db)
    with caplog.at_level(logging.WARNING, logger="app.api.chat"):
        chat_api._persist_turn_sync(1, "session-1", "tutor", None, "正文", "回答")

    assert sensitive_body not in caplog.text
    assert "RuntimeError" in caplog.text
    assert db.rolled_back and db.closed


def test_upload_vision_exception_log_omits_sensitive_body(
    caplog, monkeypatch, tmp_path,
):
    import asyncio
    from types import SimpleNamespace

    from app.api import uploads as uploads_api

    sensitive_body = "上传图片识别正文 secret@example.com"

    class FakeFile:
        content_type = "image/png"
        filename = "question.png"

        async def read(self):
            return b"image-data"

    async def fail_describe(path, mime):
        raise RuntimeError(sensitive_body)

    monkeypatch.setattr(uploads_api, "settings", SimpleNamespace(upload_path=tmp_path))
    monkeypatch.setattr(uploads_api, "assert_image_upload_allowed", lambda *args: None)
    monkeypatch.setattr(uploads_api, "record_image_upload", lambda *args: None)
    monkeypatch.setattr(uploads_api, "vision_enabled", lambda: True)
    monkeypatch.setattr(uploads_api, "vlm_enabled", lambda: False)
    monkeypatch.setattr(uploads_api, "describe_image", fail_describe)

    with caplog.at_level(logging.WARNING, logger="app.api.uploads"):
        result = asyncio.run(uploads_api._process_image(
            FakeFile(), SimpleNamespace(id=7), object(),
        ))

    assert sensitive_body not in caplog.text
    assert "RuntimeError" in caplog.text
    assert result["error"] == "识图服务暂时不可用，请手动输入题目内容"


def test_material_parse_exception_log_omits_sensitive_body(caplog, monkeypatch):
    from app.db import session as db_session
    from app.services import material_parse_jobs

    sensitive_body = "素材全文 secret@example.com"

    class FakeDB:
        rolled_back = False
        closed = False

        def rollback(self):
            self.rolled_back = True

        def query(self, *args):
            return self

        def filter(self, *args):
            return self

        def first(self):
            return None

        def close(self):
            self.closed = True

    db = FakeDB()

    def fail_parse(db, job_id):
        raise RuntimeError(sensitive_body)

    monkeypatch.setattr(db_session, "SessionLocal", lambda: db)
    monkeypatch.setattr(material_parse_jobs, "run_parse_job", fail_parse)
    with caplog.at_level(logging.ERROR, logger="app.services.material_parse_jobs"):
        material_parse_jobs.process_parse_job(99)

    assert sensitive_body not in caplog.text
    assert "RuntimeError" in caplog.text
    assert db.rolled_back and db.closed
