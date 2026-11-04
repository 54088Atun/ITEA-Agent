"""统一多模态上下文:图片/语音/文本附件来源标注"""
from app.api.chat import _compose_user_content
from app.schemas.agent import ChatRequest


def test_compose_image_and_audio_sources():
    content = _compose_user_content("请结合两部分回答", [
        {"type": "image", "text": "二叉树前序遍历"},
        {"type": "audio", "text": "重点讲递归写法"},
    ])

    assert "来源：图片 OCR" in content
    assert "二叉树前序遍历" in content
    assert "来源：语音识别" in content
    assert "重点讲递归写法" in content
    assert content.endswith("请结合两部分回答")


def test_compose_empty_image_text():
    content = _compose_user_content("", [{"type": "image", "text": ""}])
    assert "图片未识别到文字" in content


def test_compose_image_with_semantic_description():
    content = _compose_user_content("这张图讲了什么", [{
        "type": "image",
        "text": "Data Pipeline",
        "description": "Input flows to Process and then Output.",
    }])
    assert "图片语义描述" in content
    assert "Input flows to Process" in content
    assert "Data Pipeline" in content


def test_compose_without_attachments_keeps_message():
    assert _compose_user_content("普通问题", []) == "普通问题"


def test_compose_unknown_attachment_type():
    content = _compose_user_content("", [{"type": "file", "text": "附件文本"}])
    assert "附件内容" in content
    assert "附件文本" in content


def test_chat_request_allows_attachment_only():
    req = ChatRequest(attachments=[{"type": "image", "text": "题目"}])
    assert req.message == ""
    assert req.attachments[0]["type"] == "image"
