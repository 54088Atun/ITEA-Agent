"""本地 CPU 视觉模型:启用判断、语义描述与失败降级"""
import asyncio
from pathlib import Path

from app.core.config import settings
from app.services import vision


def test_vlm_enabled_reads_model_config(monkeypatch):
    monkeypatch.setattr(settings, "VISION_VLM_MODEL", "HuggingFaceTB/SmolVLM-256M-Instruct")
    assert vision.vlm_enabled() is True

    monkeypatch.setattr(settings, "VISION_VLM_MODEL", "")
    assert vision.vlm_enabled() is False


def test_describe_image_semantics(monkeypatch, tmp_path):
    image = tmp_path / "diagram.png"
    image.write_bytes(b"fake-image")
    monkeypatch.setattr(settings, "VISION_VLM_MODEL", "fake-model")
    monkeypatch.setattr(vision, "_run_local_vlm_sync", lambda path: "Input flows to Process and Output.")

    text = asyncio.run(vision.describe_image_semantics(Path(image)))

    assert text == "Input flows to Process and Output."


def test_describe_image_semantics_degrades_on_failure(monkeypatch, tmp_path):
    image = tmp_path / "diagram.png"
    image.write_bytes(b"fake-image")
    monkeypatch.setattr(settings, "VISION_VLM_MODEL", "fake-model")

    def boom(path):
        raise RuntimeError("model unavailable")

    monkeypatch.setattr(vision, "_run_local_vlm_sync", boom)

    assert asyncio.run(vision.describe_image_semantics(Path(image))) == ""


def test_describe_image_semantics_disabled(monkeypatch, tmp_path):
    image = tmp_path / "diagram.png"
    image.write_bytes(b"fake-image")
    monkeypatch.setattr(settings, "VISION_VLM_MODEL", "")

    assert asyncio.run(vision.describe_image_semantics(Path(image))) == ""
