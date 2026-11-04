"""信息分级:四级口径、角色上限、人工调整与输出过滤(AG-05 / 决策 #4)"""
from types import SimpleNamespace

from app.services.security_levels import (
    LEVELS, approval_mode, can_view, classify, detect_level, enforce, level_meta,
    mask_message, normalize_level, role_max_level,
)


def _user(role="student", admin_level=None):
    return SimpleNamespace(role=role, admin_level=admin_level)


def test_four_levels_are_declared():
    assert LEVELS == ("full", "auto", "manual", "confidential")
    assert level_meta("full")["label"] == "公开"
    assert level_meta("auto")["label"] == "内部"
    assert level_meta("manual")["label"] == "敏感"
    assert level_meta("confidential")["label"] == "机密"


def test_rule_levels_three_tiers():
    assert detect_level("今天天气如何")[0] == "full"
    assert detect_level("这门课的课程资料在哪里")[0] == "auto"
    assert detect_level("我的学情和错题分析")[0] == "manual"
    assert detect_level("服务器的 API_KEY 是 sk-xxx")[0] == "manual"
    # 多类命中时取最高级别
    assert detect_level("课程资料里包含身份证号")[0] == "manual"


def test_legacy_levels_map_to_four_tiers():
    assert normalize_level("public") == "full"
    assert normalize_level("internal") == "auto"
    assert normalize_level("sensitive") == "manual"
    assert normalize_level("confidential") == "confidential"
    assert normalize_level("unknown") is None
    assert classify("普通内容", "sensitive") == "manual"


def test_role_limits():
    assert role_max_level(_user("student")) == "auto"
    assert role_max_level(_user("teacher")) == "manual"
    assert role_max_level(_user("admin")) == "confidential"
    assert role_max_level(_user("admin", "observer")) == "confidential"

    assert can_view(_user("student"), "auto")
    assert not can_view(_user("student"), "manual")
    assert can_view(_user("teacher"), "manual")
    assert not can_view(_user("teacher"), "confidential")
    assert can_view(_user("admin"), "confidential")


def test_enforce_hides_over_limit_content():
    text = "你的学情显示掌握度 40，本次成绩 55 分"
    content, level, blocked = enforce(text, _user("student"))
    assert level == "manual"
    assert blocked is True
    assert "学情" not in content
    assert "无权查看" in content

    visible, level, blocked = enforce(text, _user("teacher"))
    assert blocked is False
    assert visible == text
    assert level == "manual"


def test_model_hint_raises_level_and_is_stripped():
    text = "这是一段通用说明 [[security:confidential]]"
    content, level, blocked = enforce(text, _user("admin"))
    assert level == "confidential"
    assert blocked is False
    assert "[[security:" not in content

    denied, level, blocked = enforce(text, _user("teacher"))
    assert level == "confidential"
    assert blocked is True

    student_text = "本节课重点 [[security:internal]]"
    content, level, blocked = enforce(student_text, _user("student"))
    assert level == "auto"
    assert blocked is False
    assert "[[security:" not in content
    assert content == "本节课重点"

    new_hint = "内部资料 [[security:auto]]"
    content, level, blocked = enforce(new_hint, _user("student"))
    assert level == "auto"
    assert content == "内部资料"


def test_manual_override_can_raise_or_lower_level():
    """决策 #4:教师/管理员可人工上调或下调分级"""
    text = "普通内容"
    content, level, blocked = enforce(
        text, _user("student"), override="confidential",
    )
    assert level == "confidential"
    assert blocked is True
    assert "无权查看" in content

    sensitive = "我的学情和错题分析"
    visible, level, blocked = enforce(
        sensitive, _user("student"), override="full",
    )
    assert level == "full"
    assert blocked is False
    assert visible == sensitive


def test_mask_message_carries_label():
    assert "敏感" in mask_message("manual")
    assert "内部" in mask_message("auto")
    assert "公开" in mask_message("full")
    assert "机密" in mask_message("confidential")


def test_level_meta_and_approval_mode():
    assert approval_mode("sensitive") == "manual"
    assert approval_mode("internal") == "auto"
    assert approval_mode("public") == "full"
    meta = level_meta("confidential")
    assert meta["level"] == "confidential"
    assert meta["label"] == "机密"
    assert meta["approval_mode"] == "confidential"
