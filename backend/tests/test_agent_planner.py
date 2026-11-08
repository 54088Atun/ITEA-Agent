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

# 计划必须只包含调用者角色可用的工具,因此按分支给出真实发起角色
ROLE_BY_BRANCH = {
    "teacher": "teacher",
    "tutor": "student",
    "review": "student",
    "interview": "student",
    "admin": "admin",
    "team": "student",
}


def _state(branch="tutor", question="统计近 4 周提交率", user_role=None, **extra):
    state = {
        "branch": branch,
        "user_id": 7,
        "course_id": 3,
        "user_role": user_role or ROLE_BY_BRANCH.get(branch, "student"),
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
        "course_evidence", "profile_query", "rag_search",
    ]


@pytest.mark.parametrize("branch", BRANCHES)
def test_plan_never_lists_tools_denied_for_role(branch):
    """A-03 回归:计划里出现调用者无权使用的工具会误导用户"""
    from app.services.capabilities import tool_denied_reason

    state = _state(branch)
    plan = asyncio.run(planner_node(state))["task_plan"]

    assert plan
    for item in plan:
        assert tool_denied_reason(state["user_role"], item["tool"]) is None, item["tool"]


def test_llm_planner_uses_question_and_drops_denied_tool(monkeypatch):
    """A-03:开启后由模型规划,越权工具被丢弃,检索参数自动补齐"""
    import app.agent.llm as llm_module
    from app.core.config import settings

    async def fake_llm(messages, temperature=None, sink=None):
        return (
            '{"steps":['
            '{"title":"检索课程资料","tool":"course_evidence","args":{}},'
            '{"title":"分析班级学情","tool":"stats_analyzer","args":{}}'
            ']}'
        )

    monkeypatch.setattr(llm_module, "llm_invoke", fake_llm)
    monkeypatch.setattr(settings, "PLANNER_LLM_ENABLED", True)

    plan = asyncio.run(planner_node(_state("tutor")))["task_plan"]

    assert [item["tool"] for item in plan] == ["course_evidence"]
    assert plan[0]["args"]["query"] == "统计近 4 周提交率"
    assert plan[0]["args"]["course_id"] == 3


def test_llm_planner_falls_back_to_template_on_failure(monkeypatch):
    import app.agent.llm as llm_module
    from app.core.config import settings

    async def boom(*args, **kwargs):
        raise RuntimeError("模型不可用")

    monkeypatch.setattr(llm_module, "llm_invoke", boom)
    monkeypatch.setattr(settings, "PLANNER_LLM_ENABLED", True)

    plan = asyncio.run(planner_node(_state("tutor")))["task_plan"]

    assert [item["tool"] for item in plan] == [
        "course_evidence", "profile_query", "rag_search",
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
    step = result["task_plan"][-1]
    assert step["tool"] == "course_evidence"
    # A-04 回归:重试步骤必须补齐检索必需参数,否则必然被网关拒绝
    assert step["args"]["query"] == "统计近 4 周提交率"
    assert step["args"]["course_id"] == 3


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


def _stub_graph(monkeypatch, tutor_result, calls):
    """把业务链路替换为轻量桩,用于验证图路由与节点实际调用次数"""
    planned = {"done": False}

    def planner(state):
        if planned["done"]:
            return {"plan_status": "skipped"}
        planned["done"] = True
        return {
            "plan_status": "planned",
            "task_plan": [{
                "step": 1, "title": "检索课程资料", "tool": "course_evidence",
                "status": "pending",
            }],
            "current_step": 1,
        }

    monkeypatch.setattr(agent_graph, "router_node", lambda state: {"branch": "tutor"})
    monkeypatch.setattr(agent_graph, "prepare_node", lambda state: {"course_id": None})
    monkeypatch.setattr(agent_graph, "planner_node", planner)
    monkeypatch.setattr(agent_graph, "tutor_node", lambda state: dict(tutor_result))

    def patch(state):
        calls["patch"] += 1
        return {"plan_revisions": []}

    monkeypatch.setattr(agent_graph, "plan_patch_node", patch)
    monkeypatch.setattr(agent_graph, "reflect_node", lambda state: {"reflection_passed": True})
    monkeypatch.setattr(agent_graph, "memory_write_node", lambda state: {})
    return agent_graph.build_graph()


def _graph_input():
    return {
        "messages": [{"role": "user", "content": "解释等价类划分"}],
        "user_id": 1,
        "branch": "tutor",
        "tool_calls": [],
    }


def test_graph_bypasses_executor_when_no_tool_calls(monkeypatch):
    calls = {"executor": 0, "patch": 0}
    graph = _stub_graph(
        monkeypatch, {"tool_calls": [], "final_output": "保留的回答"}, calls,
    )

    result = graph.invoke(_graph_input())

    assert calls == {"executor": 0, "patch": 1}
    assert result["final_output"] == "保留的回答"


def test_graph_trace_shows_plan_consumed_once(monkeypatch):
    """运行轨迹证明:计划生成后被 plan_patch 消费一次,空工具分支不进入执行节点"""
    calls = {"executor": 0, "patch": 0}
    graph = _stub_graph(monkeypatch, {"tool_calls": [], "final_output": "ok"}, calls)
    state = {**_graph_input(), "request_id": "trace-plan-1"}

    trace = [node for chunk in graph.stream(state, stream_mode="updates") for node in chunk]

    assert trace == [
        "router", "prepare", "planner", "tutor",
        "plan_patch", "planner", "reflect", "memory_write",
    ]
    assert trace.count("plan_patch") == 1
    assert "tool_executor" not in trace


def test_memory_load_node_is_not_advertised():
    """个性化入口运行时读学情,不再暴露无消费者的 memory_load 图节点"""
    from app.agent import nodes as nodes_module

    assert not hasattr(nodes_module, "memory_load_node")
    assert "memory_load" not in agent_graph.build_graph().get_graph().nodes


def test_graph_has_no_unreachable_tool_executor_node():
    """A-14:工具循环已内嵌在业务节点,图里不再保留不可达的执行节点"""
    built = agent_graph.build_graph().get_graph()

    assert "tool_executor" not in built.nodes
    edges = {(edge.source, edge.target) for edge in built.edges}
    for node in ("teacher", "tutor", "review", "interview", "admin", "collab_merge"):
        assert (node, "plan_patch") in edges
