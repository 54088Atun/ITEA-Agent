"""上传文件保留期清理(NF-03)"""
import os
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.core.deps import require_admin_write
from app.services.storage_cleanup import cleanup_uploads, cleanup_uploads_task


def _touch(path, age_days, now):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * 10)
    ts = (now - timedelta(days=age_days)).timestamp()
    os.utime(path, (ts, ts))
    return path


@pytest.fixture()
def uploads(tmp_path):
    now = datetime.utcnow()
    files = {
        "vision_old": _touch(tmp_path / "vision" / "1" / "old.png", 40, now),
        "vision_new": _touch(tmp_path / "vision" / "1" / "new.png", 0, now),
        "audio_old": _touch(tmp_path / "audio" / "2" / "old.webm", 40, now),
        "draft_old": _touch(tmp_path / "10" / "drafts" / "old.docx", 10, now),
        "draft_new": _touch(tmp_path / "10" / "drafts" / "new.docx", 0, now),
        "material": _touch(tmp_path / "10" / "outline.pdf", 40, now),
        "avatar_used": _touch(tmp_path / "avatar" / "1_keep.png", 40, now),
        "avatar_orphan": _touch(tmp_path / "avatar" / "1_orphan.png", 40, now),
        "avatar_new": _touch(tmp_path / "avatar" / "1_new.png", 0, now),
    }
    return tmp_path, files, now


def test_cleanup_respects_retention_periods(uploads):
    root, files, now = uploads
    stats = cleanup_uploads(
        now=now, upload_dir=root, referenced_avatars={"1_keep.png"},
    )

    assert stats["deleted"] == 4
    assert stats["by_category"] == {
        "vision": 1, "audio": 1, "drafts": 1, "avatar": 1,
    }
    assert not files["vision_old"].exists()
    assert not files["audio_old"].exists()
    assert not files["draft_old"].exists()
    assert not files["avatar_orphan"].exists()

    assert files["vision_new"].exists()
    assert files["draft_new"].exists()
    assert files["material"].exists(), "课程资料属于教学资产，不得清理"
    assert files["avatar_used"].exists(), "仍被用户引用的头像不得清理"
    assert files["avatar_new"].exists()


def test_cleanup_task_swallows_errors(monkeypatch):
    def boom(**kwargs):
        raise RuntimeError("disk broken")

    monkeypatch.setattr("app.services.storage_cleanup.cleanup_uploads", boom)
    result = cleanup_uploads_task()
    assert result["deleted"] == 0
    assert "disk broken" in result["error"]


def test_observer_cannot_trigger_cleanup():
    observer = SimpleNamespace(id=1, role="admin", admin_level="observer", status="active")
    with pytest.raises(HTTPException) as exc:
        require_admin_write(observer)
    assert exc.value.status_code == 403

    normal = SimpleNamespace(id=2, role="admin", admin_level="normal", status="active")
    assert require_admin_write(normal) is normal
