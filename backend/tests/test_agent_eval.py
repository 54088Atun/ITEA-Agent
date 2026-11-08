"""P2-1 评估体系:金标准任务集、离线跑分与基线门禁

CI 入口就是本文件:任务集数量/覆盖不足、离线指标低于基线,都会直接失败。
"""
import pytest

from evals import harness


def test_golden_dataset_covers_roles_and_refusal():
    cases = harness.load_cases()

    assert len(cases) >= 100
    ids = [case["id"] for case in cases]
    assert len(ids) == len(set(ids)), "任务 id 必须唯一"

    by_role = {role: 0 for role in ("student", "teacher", "admin")}
    for case in cases:
        by_role[case["role"]] += 1
    assert all(count >= 20 for count in by_role.values())

    assert sum(1 for case in cases if case["refusal"]) >= 15
    assert sum(1 for case in cases if case["tools"]) >= 40
    assert all(
        case["citation"] in ("required", "general_only", "none") for case in cases
    )
    assert all(
        case["branch"] in (
            "teacher", "tutor", "review", "interview", "admin", "team", "block",
        )
        for case in cases
    )


def test_offline_evaluation_has_no_failing_case():
    metrics, details = harness.evaluate_offline()

    assert details["failed_cases"] == []
    assert details["refusal_failures"] == []
    assert metrics["case_pass_rate"] == 1.0


def test_offline_metrics_do_not_drop_below_baseline():
    metrics, _ = harness.evaluate_offline()
    regressions = harness.compare_to_baseline(metrics, harness.load_baseline())

    assert regressions == [], f"核心指标低于基线: {regressions}"


# ---------- 强制确定性安全评测(不依赖外部模型) ----------
# 本节断言用于 CI 强制门禁;evaluate_live 的模型质量分数仅供人工审阅,
# 不得替代或抵消这里的安全断言。

def test_security_eval_code_executor_denied_everywhere():
    from app.agent.tools.gateway import available_tools, tool_schemas
    from app.services.capabilities import tool_denied_reason

    for role in ("student", "teacher", "admin"):
        assert tool_denied_reason(role, "code_executor"), f"{role} 不应允许宿主执行"
        assert "code_executor" not in {tool["name"] for tool in available_tools(role)}
        assert "code_executor" not in {
            schema["function"]["name"] for schema in tool_schemas(role)
        }


def test_security_eval_high_risk_tools_require_confirmation():
    from app.agent.tools.gateway import get_tool_spec

    for name in ("reminder_scheduler", "project.run_tests"):
        spec = get_tool_spec(name)
        assert spec is not None
        assert spec.requires_confirmation is True


def test_security_eval_course_required_argument_rejected():
    from app.agent.tools.gateway import get_tool_spec, validate_tool_arguments

    spec = get_tool_spec("course_evidence")
    assert validate_tool_arguments(spec, {"query": "等价类划分"})
    assert validate_tool_arguments(
        spec, {"query": "等价类划分", "course_id": 7},
    ) is None


def test_security_eval_has_no_standalone_tool_executor_node():
    """工具循环在业务节点内部完成,图里不再有不可达的独立执行节点"""
    from app.agent import graph as agent_graph

    built = agent_graph.build_graph().get_graph()
    assert "tool_executor" not in built.nodes
    edges = {(edge.source, edge.target) for edge in built.edges}
    for node in ("teacher", "tutor", "review", "interview", "admin"):
        assert (node, "plan_patch") in edges


def test_live_mode_requires_api_key(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "LLM_API_KEY", "")
    with pytest.raises(RuntimeError, match="LLM_API_KEY"):
        harness.evaluate_live(limit=1)
