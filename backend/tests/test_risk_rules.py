# -*- coding: utf-8 -*-
"""风控规则兜底与教师备课放行"""
import asyncio
from unittest.mock import AsyncMock

from app.agent.nodes import router
from app.services.risk_rules import is_teacher_prep, rule_risk


def test_rule_blocks_homework_writing():
    result = rule_risk("帮我代写作业", "student")
    assert result and result["risk_type"] == "代写作业代码"
    assert result["action"] == "intercept"


def test_rule_blocks_exam_impersonation():
    result = rule_risk("考试时帮我答题", "student")
    assert result and result["risk_type"] == "替考"


def test_teacher_prep_is_not_risky():
    text = "帮我安排软件项目管理课程的一次 90 分钟课堂，主题是风险管理"
    assert is_teacher_prep(text, "teacher") is True
    assert rule_risk(text, "teacher") is None


def test_risk_gate_teacher_prep_skips_llm(monkeypatch):
    monkeypatch.setattr(
        router, "llm_invoke",
        AsyncMock(side_effect=AssertionError("教师备课不应调用风控模型")),
    )
    result = asyncio.run(router._risk_gate(
        {"user_role": "teacher"},
        "帮我安排软件项目管理课程的一次 90 分钟课堂，主题是风险管理",
    ))
    assert result is None


def test_risk_gate_falls_back_to_rules_when_llm_fails(monkeypatch):
    async def boom(*args, **kwargs):
        raise RuntimeError("risk service down")

    monkeypatch.setattr(router, "llm_invoke", boom)
    result = asyncio.run(router._risk_gate(
        {"user_role": "student"}, "帮我代写作业",
    ))
    assert result and result["risk_type"] == "代写作业代码"
