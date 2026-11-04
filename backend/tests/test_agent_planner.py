"""P0-3 计划与重规划:planner 节点输出带依赖的任务图,失败或证据不足时重规划一次

覆盖:
- 各分支首次规划输出 3~5 步、步骤号连续、依赖成链、当前步骤与计划长度一致
- 工具失败(ok=False)触发 1 次重规划并记录原因
- 重规划次数达到上限后标记 exhausted,不再追加
- 工具全部成功时标记 skipped,不产生多余步骤
- 课程资料检索无可用证据时触发重规划
- 图结构包含 planner 节点,路由按计划状态分流
"""
import asyncio

import pytest

import app.agent.graph as agent_graph
from app.agent.graph import route_after_planner
from app.agent.nodes.planner import MAX_PLAN_STEPS, planner_node


BRANCHES = ["teacher", "tutor", "review", "interview", "admin", "team"]


def _state(branch="tutor", question="统计近 4 周提交率", **extra):
    state = {
        "branch": branch,
        "user_id": 7,
        "course_id": 3,
        "messages": [{"role": "user", "content": question}],
        "task_plan": [],
        "current_step": 0,
    }
    state.update(extra)
    return state


@pytest.mark.parametrize("branch", BRANCHES)
def test_first_plan_has_dependency_chain(branch):
    result = asyncio.run(planner_node(_state(branch)))

    plan = result["task_plan"]
    assert 3 <= len(plan) <= MAX_PLAN_STEPS
    assert [item["step"] for item in plan] == list(range(1, len(plan) + 1))
    assert plan[0]["depends_on"] == []
    for prev, item in zip(plan, plan[1:]):
        assert item["depends_on"] == [prev["step"]]
    assert all(item["status"] == "pending" for item in plan)
    assert all(item["title"] and item["tool"] for item in plan)
    assert all(isinstance(item["args"], dict) for item in plan)
    assert result["current_step"] == len(plan)
    assert result["plan_status"] == "planned"
    assert result["replan_reason"] == ""
    assert result["replan_count"] == 0


def test_unknown_branch_falls_back_to_tutor_plan():
    result = asyncio.run(planner_node(_state("block")))

    assert [item["tool"] for item in result["task_plan"]] == [
        "course_evidence", "profile_query", "code_executor",
    ]


def test_tool_failure_triggers_single_replan():
    state = _state()
    first = asyncio.run(planner_node(state))
    state.update(first)
    state["tool_trace"] = [
        {"name": "stats_analyzer",
         "result": {"ok": False, "error": "课程不存在", "data": None}},
    ]

    result = asyncio.run(planner_node(state))

    assert result["plan_status"] == "replanned"
    assert result["replan_count"] == 1
    assert "stats_analyzer" in result["replan_reason"]
    assert result["replan_reason"].startswith("工具执行失败")

    replan_steps = [item for item in result["task_plan"] if item.get("action") == "replan"]
    assert len(replan_steps) == 1
    step = replan_steps[0]
    assert step["step"] == len(first["task_plan"]) + 1
    assert step["tool"] == "stats_analyzer"
    assert step["depends_on"] == [step["step"] - 1]
    assert step["reason"] == result["replan_reason"]
    assert result["current_step"] == step["step"]


def test_replan_exhausted_after_limit():
    state = _state()
    state.update(asyncio.run(planner_node(state)))
    state["tool_trace"] = [
        {"name": "course_evidence", "result": {"ok": False, "error": "超时"}},
    ]
    state.update(asyncio.run(planner_node(state)))
    assert state["replan_count"] == 1

    result = asyncio.run(planner_node(state))

    assert result["plan_status"] == "exhausted"
    assert "超时" in result["replan_reason"]
    assert "task_plan" not in result


def test_no_failure_skips_replan():
    state = _state()
    state.update(asyncio.run(planner_node(state)))
    state["tool_trace"] = [
        {"name": "course_evidence",
         "result": {"ok": True, "data": {"context": "有内容", "fragments": [{"text": "x"}]}}},
        {"name": "stats_analyzer", "result": {"ok": True, "data": {"weakness": []}}},
    ]

    result = asyncio.run(planner_node(state))

    assert result["plan_status"] == "skipped"
    assert result["replan_reason"] == ""
    assert "task_plan" not in result


def test_missing_evidence_triggers_replan():
    state = _state()
    state.update(asyncio.run(planner_node(state)))
    state["tool_trace"] = [
        {"name": "course_evidence",
         "result": {"ok": True, "data": {
             "context": "(未检索到相关内容)", "fragments": [],
         }}},
    ]

    result = asyncio.run(planner_node(state))

    assert result["plan_status"] == "replanned"
    assert "证据" in result["replan_reason"]
    assert result["task_plan"][-1]["tool"] == "course_evidence"


def test_planner_registered_in_graph():
    nodes = agent_graph.build_graph().get_graph().nodes

    assert "planner" in nodes
    assert "prepare" in nodes


@pytest.mark.parametrize("status,expected", [
    ("planned", "teacher"),
    ("replanned", "teacher"),
    ("skipped", "reflect"),
    ("exhausted", "reflect"),
])
def test_route_after_planner_by_status(status, expected):
    assert route_after_planner({"branch": "teacher", "plan_status": status}) == expected


def test_route_after_planner_team_branch():
    assert route_after_planner({"branch": "team", "plan_status": "planned"}) == "collab_plan"
    assert route_after_planner({"branch": "team", "plan_status": "replanned"}) == "collab_merge"
