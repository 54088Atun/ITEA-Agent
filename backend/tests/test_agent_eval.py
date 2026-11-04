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


def test_live_mode_requires_api_key(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "LLM_API_KEY", "")
    with pytest.raises(RuntimeError, match="LLM_API_KEY"):
        harness.evaluate_live(limit=1)
