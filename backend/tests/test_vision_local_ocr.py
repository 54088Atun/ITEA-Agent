"""本地 OCR:输出解析、启用判断与本地路径分流"""
import asyncio
from pathlib import Path

from app.core.config import settings
from app.services import vision


SAMPLE_OUTPUT = """
[INFO] OpenVINO model loaded successfully. Device: CPU
Models average inference time: 973.4 ms

二叉树前序遍历
[0.98] 公式: a2 + b2 = c2
手写内容测试

[OK] OCR complete | 1 image(s) | 3 line(s) | 1.38s | CPU
  Log: C:\\Users\\test\\.openvino\\log\\ocr.log
"""


def test_parse_local_ocr_output():
    text = vision.parse_local_ocr(SAMPLE_OUTPUT)
    assert "二叉树前序遍历" in text
    assert "公式: a2 + b2 = c2" in text
    assert "手写内容测试" in text
    assert "[OK]" not in text
    assert "average inference" not in text


def test_local_ocr_enabled_uses_script(monkeypatch, tmp_path):
    script = tmp_path / "run.ps1"
    script.write_text("# fake", encoding="utf-8")
    monkeypatch.setattr(settings, "VISION_PROVIDER", "local_ocr")
    monkeypatch.setattr(settings, "VISION_LOCAL_SCRIPT", str(script))

    assert vision.vision_enabled() is True

    monkeypatch.setattr(settings, "VISION_LOCAL_SCRIPT", str(tmp_path / "missing.ps1"))
    assert vision.vision_enabled() is False


def test_describe_image_dispatches_local_ocr(monkeypatch, tmp_path):
    script = tmp_path / "run.ps1"
    script.write_text("# fake", encoding="utf-8")
    image = tmp_path / "test.png"
    image.write_bytes(b"fake-image")

    monkeypatch.setattr(settings, "VISION_PROVIDER", "local_ocr")
    monkeypatch.setattr(settings, "VISION_LOCAL_SCRIPT", str(script))

    async def fake_local(path):
        return "本地识别结果"

    monkeypatch.setattr(vision, "_describe_local_ocr", fake_local)

    text = asyncio.run(vision.describe_image(Path(image), "image/png"))
    assert text == "本地识别结果"


def test_openai_vision_still_requires_model_and_key(monkeypatch):
    monkeypatch.setattr(settings, "VISION_PROVIDER", "openai")
    # 固定 base,避免本地 .env 的 DashScope 配置让密钥回退逻辑生效
    monkeypatch.setattr(settings, "VISION_API_BASE", "https://api.openai.com/v1")
    monkeypatch.setattr(settings, "VISION_MODEL", "vision-model")
    monkeypatch.setattr(settings, "VISION_API_KEY", "key")
    assert vision.vision_enabled() is True

    monkeypatch.setattr(settings, "VISION_API_KEY", "")
    assert vision.vision_enabled() is False
