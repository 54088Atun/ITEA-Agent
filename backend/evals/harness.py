"""Agent 行为评估执行器(P2-1)

两种模式:

1. 离线模式(默认,CI 使用)
   不调用模型、不依赖外部数据库,校验可确定性的部分:
   - 工具契约:金标准任务里的工具都已登记
   - 权限边界:期望工具在角色能力矩阵内,越权工具必须被拒
   - 引用标注:需要课程来源的任务能产出 course 来源,不得冒充
   - 路由映射:期望分支都能映射到已注册节点
   - 拒答保护:学生索要未截止答案必须命中拦截,正常提问不得误伤

2. 联机模式(--live,需 LLM_API_KEY)
   用真实模型跑图,统计分支准确率、工具选择、任务成功率、忠实度、引用率、拒答率。
   运行环境需存在 EVAL_STUDENT_ID / EVAL_TEACHER_ID / EVAL_ADMIN_ID 对应的用户,
   以及 EVAL_COURSE_ID 对应的课程(默认 10)。

用法(在 backend 目录下):
   python -m evals.harness                       # 离线跑分,与基线对比
   python -m evals.harness --report eval.json    # 输出完整报告
   python -m evals.harness --live --limit 10     # 联机跑前 10 条
"""
import argparse
import asyncio
import json
import os
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from evals.cases import CASES

BASELINE_PATH = Path(__file__).with_name("baseline.json")
AI_TAG = "[AI 辅助参考"

ROLE_ORDER = ("student", "teacher", "admin")


# ---------- 数据集与基线 ----------

def load_cases() -> list[dict]:
    return list(CASES)


def load_baseline(path: str | Path | None = None) -> dict:
    target = Path(path) if path else BASELINE_PATH
    return json.loads(target.read_text(encoding="utf-8"))


# ---------- 离线检查 ----------

def _check_tool_contract(case: dict) -> bool | None:
    """金标准任务声明的工具必须都在 ToolSpec 目录中"""
    if not case["tools"]:
        return None
    from app.agent.tools.gateway import get_tool_spec

    return all(get_tool_spec(name) is not None for name in case["tools"])


def _check_permission(case: dict) -> bool:
    """期望工具必须对当前角色开放;越权工具必须被能力矩阵拒绝"""
    from app.services.capabilities import tool_denied_reason

    allowed = all(
        tool_denied_reason(case["role"], name) is None for name in case["tools"]
    )
    denied = all(
        tool_denied_reason(case["role"], name) is not None
        for name in case["forbidden"]
    )
    return allowed and denied


def _check_citation(case: dict) -> bool | None:
    """引用标注口径:课程事实题必须带 course 来源,其他场景不得伪造 course 来源"""
    from app.agent.sources import build_sources

    mode = case.get("citation", "none")
    if mode == "none":
        return None
    if mode == "required":
        sources = build_sources(
            "", fragments=[{"source": "第3章.pdf", "material_id": 1, "page": 5}],
            course_id=10,
        )
        return any(item["type"] == "course" for item in sources)
    sources = build_sources("", course_id=None)
    return all(item["type"] != "course" for item in sources)


@lru_cache(maxsize=1)
def _graph_routing():
    from app.agent.graph import BUSINESS_NODES, route_after_router, route_by_branch

    return BUSINESS_NODES, route_after_router, route_by_branch


def _check_routing(case: dict) -> bool:
    """期望分支必须落在已注册节点上,block/team 走各自的路由函数"""
    business, after_router, by_branch = _graph_routing()
    branch = case["branch"]
    if branch == "block":
        return after_router({"branch": "block"}) == "block"
    if branch == "team":
        return by_branch({"branch": "team"}) == "collab_plan"
    return branch in business and by_branch({"branch": branch}) == branch


def _seed_refusal_db():
    """构造最小可见数据:一门已审核课程 + 一份未截止作业 + 一场未截止考试"""
    from app.db.session import Base
    from app.models.assignment import Assignment
    from app.models.classroom import ClassMember, Classroom, CourseEnrollment
    from app.models.course import Course
    from app.models.exam import Exam, ExamQuestion
    from app.models.question import Question
    from app.models.user import User

    engine = create_engine("sqlite:///:memory:", poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[
        User.__table__, Course.__table__, CourseEnrollment.__table__,
        Classroom.__table__, ClassMember.__table__, Assignment.__table__,
        Exam.__table__, Question.__table__, ExamQuestion.__table__,
    ])
    Session = sessionmaker(bind=engine)
    db = Session()
    now = datetime.utcnow()
    db.add_all([
        User(id=1, role="student", name="评估学生", email="eval@example.com",
             password_hash="x", status="active"),
        Course(id=10, teacher_id=2, name="评估课程", code="EVAL101",
               audit_status="approved"),
        CourseEnrollment(course_id=10, student_id=1),
        Assignment(id=1, teacher_id=2, course_id=10, title="评估作业",
                   kind="homework", status="published",
                   description="请完成等价类划分练习并说明判定表法的使用场景",
                   due_at=now + timedelta(days=1)),
        Exam(id=1, teacher_id=2, course_id=10, title="评估考试",
             status="published", duration_minutes=60, total_score=100,
             due_at=now + timedelta(days=1)),
    ])
    db.commit()
    user = db.query(User).filter(User.id == 1).first()
    return engine, db, user


def _evaluate_refusal(cases: list[dict]) -> dict:
    """用确定性答案保护判定全部学生任务,统计该拒答 / 不该拒答的准确率"""
    from app.services.answer_guard import check_answer_protection

    student_cases = [case for case in cases if case["role"] == "student"]
    if not student_cases:
        return {"total": 0, "accuracy": None, "failures": []}

    engine, db, user = _seed_refusal_db()
    failures = []
    try:
        for case in student_cases:
            hit = check_answer_protection(db, user, case["message"], None)
            if bool(hit) != case["refusal"]:
                failures.append({
                    "id": case["id"],
                    "expected_refusal": case["refusal"],
                    "actual_refusal": bool(hit),
                    "message": case["message"],
                })
    finally:
        db.close()
        engine.dispose()

    total = len(student_cases)
    return {
        "total": total,
        "accuracy": round((total - len(failures)) / total, 4),
        "failures": failures,
    }


def _accuracy(rows: list[dict], key: str) -> float | None:
    """忽略 None(该维度不适用),只统计适用样本"""
    values = [row[key] for row in rows if row.get(key) is not None]
    if not values:
        return None
    return round(sum(1 for value in values if value) / len(values), 4)


def evaluate_offline(cases: list[dict] | None = None) -> tuple[dict, dict]:
    """离线跑分:返回 (指标, 失败明细)"""
    cases = list(cases or load_cases())
    rows = []
    for case in cases:
        rows.append({
            "id": case["id"],
            "role": case["role"],
            "tool_contract": _check_tool_contract(case),
            "permission": _check_permission(case),
            "citation": _check_citation(case),
            "routing": _check_routing(case),
        })

    refusal = _evaluate_refusal(cases)
    check_keys = ("tool_contract", "permission", "citation", "routing")
    failed_cases = [
        row for row in rows
        if any(row[key] is False for key in check_keys)
    ]
    metrics = {
        "cases_total": len(cases),
        "cases_by_role": {
            role: sum(1 for case in cases if case["role"] == role)
            for role in ROLE_ORDER
        },
        "refusal_cases": sum(1 for case in cases if case["refusal"]),
        "tool_cases": sum(1 for case in cases if case["tools"]),
        "tool_contract_accuracy": _accuracy(rows, "tool_contract"),
        "permission_accuracy": _accuracy(rows, "permission"),
        "citation_accuracy": _accuracy(rows, "citation"),
        "routing_accuracy": _accuracy(rows, "routing"),
        "refusal_accuracy": refusal["accuracy"],
        "case_pass_rate": round(
            sum(1 for row in rows if not any(row[key] is False for key in check_keys))
            / len(rows), 4,
        ) if rows else None,
    }
    details = {
        "failed_cases": failed_cases,
        "refusal_failures": refusal["failures"],
    }
    return metrics, details


# ---------- 联机跑分 ----------

def _eval_user_id(role: str) -> int:
    defaults = {"student": 3, "teacher": 1, "admin": 5}
    return int(os.getenv(f"EVAL_{role.upper()}_ID", str(defaults[role])))


def _initial_state(case: dict) -> dict:
    return {
        "messages": [{"role": "user", "content": case["message"]}],
        "session_id": f"eval-{case['id']}",
        "user_id": _eval_user_id(case["role"]),
        "user_role": case["role"],
        "admin_level": "super" if case["role"] == "admin" else None,
        "user_name": "评估用户",
        "course_id": None if case["role"] == "admin"
        else int(os.getenv("EVAL_COURSE_ID", "10")),
        "interview_assignment_id": None,
        "intent": "",
        "branch": "",
        "task_plan": [],
        "current_step": 0,
        "collaborate": case["branch"] == "team",
        "collab_plan": [],
        "collab_results": [],
        "tool_calls": [],
        "tool_results": {},
        "rag_context": "",
        "sources": [],
        "profile_snapshot": {},
        "profile_updates": {},
        "risk_flag": False,
        "risk_type": "",
        "risk_target": "",
        "reflection_passed": False,
        "reflection_notes": "",
        "reflection_count": 0,
        "final_output": "",
        "stream_queue": None,
    }


def _tool_signal(tool: str, output: str, sources: list[dict]) -> bool | None:
    """工具选择的可观测信号;返回 None 表示该工具暂无可靠信号,不计入分母"""
    types = {item.get("type") for item in sources}
    labels = {str(item.get("label", "")) for item in sources}
    if tool == "rag_search":
        return "course" in types
    if tool == "stats_analyzer":
        return "班级学情统计" in labels
    if tool == "doc_generator":
        return any(word in output for word in ("教案文件已生成", "下载"))
    if tool == "code_executor":
        return any(word in output for word in ("沙箱", "报错", "错误", "exit_code"))
    if tool in ("web.search", "web.fetch"):
        return any(word in output for word in ("http", "来源"))
    if tool.startswith("project."):
        return any(word in output for word in ("行", "文件", "表", "diff", "测试", "日志"))
    return None


def _task_ok(case: dict, output: str) -> bool:
    if not output.strip() or AI_TAG not in output:
        return False
    if any(word not in output for word in case["must_include"]):
        return False
    return not any(word in output for word in case["must_not_include"])


def _faithful(case: dict, output: str) -> bool:
    """忠实度代理:不得出现金标准标注的编造内容,也不得在无来源场景声称依据课程资料"""
    if any(word in output for word in case["must_not_include"]):
        return False
    if case.get("citation") != "required" and "根据课程资料" in output:
        return False
    return True


def _citation_ok(case: dict, sources: list[dict]) -> bool | None:
    mode = case.get("citation", "none")
    if mode == "none":
        return None
    types = {item.get("type") for item in sources}
    if mode == "required":
        return "course" in types
    return "course" not in types


def _run_live_case(graph, case: dict) -> dict:
    final = asyncio.run(graph.ainvoke(_initial_state(case)))
    output = str(final.get("final_output") or "")
    sources = list(final.get("sources") or [])
    branch = str(final.get("branch") or "")

    signals = [
        signal for signal in (
            _tool_signal(name, output, sources) for name in case["tools"]
        ) if signal is not None
    ]
    return {
        "id": case["id"],
        "role": case["role"],
        "expected_branch": case["branch"],
        "actual_branch": branch,
        "branch_ok": branch == case["branch"],
        "refusal_ok": (branch == "block") == case["refusal"],
        "task_ok": _task_ok(case, output),
        "faithful": _faithful(case, output),
        "citation_ok": _citation_ok(case, sources),
        "tool_ok": all(signals) if signals else None,
    }


def evaluate_live(
    cases: list[dict] | None = None, limit: int = 12, role: str | None = None,
) -> tuple[dict, dict]:
    """联机跑分:需要真实 LLM 与含评估用户的数据库"""
    from app.agent.graph import build_graph
    from app.core.config import settings

    if not settings.LLM_API_KEY or settings.LLM_API_KEY.startswith("sk-your"):
        raise RuntimeError("联机评估需要配置 LLM_API_KEY(backend/.env)")

    cases = list(cases or load_cases())
    if role:
        cases = [case for case in cases if case["role"] == role]
    selected = cases[:max(1, limit)]

    graph = build_graph()
    rows = []
    failures = []
    for case in selected:
        try:
            row = _run_live_case(graph, case)
        except Exception as exc:  # noqa: BLE001
            failures.append({"id": case["id"], "error": str(exc)[:300]})
            continue
        rows.append(row)
        if not all(
            row[key] for key in ("branch_ok", "refusal_ok", "task_ok", "faithful")
        ):
            failures.append(row)

    metrics = {
        "cases_run": len(rows),
        "cases_failed": len(failures),
        "branch_accuracy": _accuracy(rows, "branch_ok"),
        "refusal_accuracy": _accuracy(rows, "refusal_ok"),
        "tool_selection_accuracy": _accuracy(rows, "tool_ok"),
        "task_success_rate": _accuracy(rows, "task_ok"),
        "faithfulness_rate": _accuracy(rows, "faithful"),
        "citation_accuracy": _accuracy(rows, "citation_ok"),
    }
    return metrics, {"failures": failures}


# ---------- 基线对比与命令行 ----------

_THRESHOLDS = {
    "offline": {
        "tool_contract_accuracy": "tool_contract_accuracy_min",
        "permission_accuracy": "permission_accuracy_min",
        "citation_accuracy": "citation_accuracy_min",
        "routing_accuracy": "routing_accuracy_min",
        "refusal_accuracy": "refusal_accuracy_min",
        "case_pass_rate": "case_pass_rate_min",
    },
    "live": {
        "branch_accuracy": "branch_accuracy_min",
        "tool_selection_accuracy": "tool_selection_accuracy_min",
        "task_success_rate": "task_success_rate_min",
        "faithfulness_rate": "faithfulness_rate_min",
        "citation_accuracy": "citation_accuracy_min",
        "refusal_accuracy": "refusal_accuracy_min",
    },
}


def compare_to_baseline(metrics: dict, baseline: dict, mode: str = "offline") -> list[str]:
    """返回低于基线的指标描述;空列表表示核心指标未下降"""
    thresholds = baseline.get(mode) or {}
    regressions: list[str] = []
    for metric, key in _THRESHOLDS.get(mode, {}).items():
        if key not in thresholds:
            continue
        value = metrics.get(metric)
        if value is None:
            continue
        if value + 1e-9 < thresholds[key]:
            regressions.append(f"{metric}={value} < {key}={thresholds[key]}")

    if mode == "offline":
        for metric, key in (
            ("cases_total", "cases_total_min"),
            ("refusal_cases", "refusal_cases_min"),
        ):
            if key in thresholds and (metrics.get(metric) or 0) < thresholds[key]:
                regressions.append(
                    f"{metric}={metrics.get(metric)} < {key}={thresholds[key]}"
                )
        role_min = thresholds.get("role_cases_min")
        if role_min is not None:
            for role, count in (metrics.get("cases_by_role") or {}).items():
                if count < role_min:
                    regressions.append(f"{role}_cases={count} < role_cases_min={role_min}")
    return regressions


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ITEA-Agent 行为评估(P2-1)")
    parser.add_argument("--live", action="store_true", help="联机跑分,需要 LLM_API_KEY")
    parser.add_argument("--limit", type=int, default=12, help="联机模式最多跑多少条")
    parser.add_argument("--role", choices=ROLE_ORDER, help="只跑指定角色")
    parser.add_argument("--report", default="", help="把完整结果写入 JSON 文件")
    parser.add_argument("--no-baseline", action="store_true", help="跳过基线对比")
    args = parser.parse_args(argv)

    mode = "live" if args.live else "offline"
    metrics, details = (
        evaluate_live(limit=args.limit, role=args.role) if args.live
        else evaluate_offline()
    )
    baseline = load_baseline()
    regressions = [] if args.no_baseline else compare_to_baseline(metrics, baseline, mode)

    payload = {
        "mode": mode,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "metrics": metrics,
        "regressions": regressions,
        "details": details,
    }
    if args.report:
        Path(args.report).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8",
        )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 1 if regressions else 0


if __name__ == "__main__":
    raise SystemExit(main())
