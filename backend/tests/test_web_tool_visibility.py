# -*- coding: utf-8 -*-
"""不可用的联网搜索工具不应出现在工具表/工具执行目录中"""
from app.agent.nodes import tool_executor
from app.agent.tools import gateway
from app.services import web_access


def _names(tools):
    return {item["name"] for item in tools}


def test_web_search_hidden_without_provider(monkeypatch):
    monkeypatch.setattr(web_access, "web_search_enabled", lambda: False)
    assert "web.search" not in _names(gateway.available_tools("teacher"))
    assert "web.search" not in _names(tool_executor.tool_schemas_for_role("teacher"))


def test_web_search_visible_when_configured(monkeypatch):
    monkeypatch.setattr(web_access, "web_search_enabled", lambda: True)
    assert "web.search" in _names(gateway.available_tools("teacher"))
    assert "web.search" in _names(tool_executor.tool_schemas_for_role("teacher"))
