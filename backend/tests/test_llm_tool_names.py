"""工具名传输契约:function name 必须匹配 OpenAI 规范 ^[a-zA-Z0-9_-]+$

内部工具名用点号分组(project.search_code),历史上一直接把点号发给模型,
DeepSeek 直接返回 400 Invalid 'tools[5].function.name'。这里固定住两点:
发送时替换为下划线、回包时还原成注册表里的名字。
"""
import re

from app.agent.llm import (
    _normalize_messages,
    _to_openai_tools,
    from_wire_name,
    to_wire_name,
)
from app.agent.nodes.tool_executor import TOOL_SCHEMAS, tool_schemas_for_role

WIRE_NAME = re.compile(r"^[a-zA-Z0-9_-]+$")


def test_all_role_schemas_have_openai_legal_names():
    for role in ("student", "teacher", "admin"):
        wired = _to_openai_tools(tool_schemas_for_role(role))
        assert wired, f"{role} 未暴露任何工具"
        for tool in wired:
            assert WIRE_NAME.match(tool["function"]["name"]), tool["function"]["name"]


def test_wire_name_roundtrip_covers_every_registered_tool():
    for schema in TOOL_SCHEMAS:
        name = schema["name"]
        assert from_wire_name(to_wire_name(name)) == name


def test_wire_name_keeps_already_legal_names():
    assert to_wire_name("course_evidence") == "course_evidence"
    assert from_wire_name("course_evidence") == "course_evidence"


def test_unknown_wire_name_is_passed_through():
    assert from_wire_name("no_such_tool") == "no_such_tool"


def test_history_tool_calls_are_rewritten_to_wire_names():
    messages = [
        {"role": "user", "content": "查一下课程"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{
                "id": "call_1",
                "name": "course_evidence",
                "arguments": {"query": "考核方式", "course_id": 1},
            }],
            "reasoning_content": "",
        },
        {"role": "tool", "tool_call_id": "call_1", "content": "{}"},
    ]
    normalized = _normalize_messages(messages)

    assert normalized[1]["tool_calls"][0]["function"]["name"] == "course_evidence"
    assert normalized[2]["tool_call_id"] == "call_1"


def test_history_dotted_tool_call_is_sent_with_underscore():
    messages = [{
        "role": "assistant",
        "content": "",
        "tool_calls": [{
            "id": "call_2",
            "name": "project.search_code",
            "arguments": {"query": "itertools"},
        }],
        "reasoning_content": "",
    }]
    sent = _normalize_messages(messages)[0]["tool_calls"][0]["function"]["name"]

    assert sent == "project_search_code"
    assert from_wire_name(sent) == "project.search_code"
