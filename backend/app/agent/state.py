"""Agent 核心状态定义 —— LangGraph 全局状态"""
from typing import TypedDict, List, Dict, Optional, Any


class AgentState(TypedDict):
    # === 会话上下文 ===
    messages: List[Dict]           # 对话历史 [{"role": "user/assistant", "content": "..."}]
    session_id: str                # 当前会话 ID
    user_id: int                   # 用户 ID
    user_role: str                 # teacher / student / admin
    admin_level: Optional[str]     # 管理员级别: super / normal / observer,非管理员为 None
    user_name: str                 # 用户姓名
    course_id: Optional[int]       # 关联课程
    interview_assignment_id: Optional[int]  # 面试来源作业,用于评分记录与可见范围

    # === 任务规划 ===
    intent: str                    # 识别意图: prepare/learn/review/interview/violation/chat
    branch: str                    # 路由分支: teacher/tutor/review/interview/admin/team/block
    review_submit: bool            # 复盘分支: true=提交错题并写入学情, false=查询/诊断
    task_plan: List[Dict]          # 拆解的子任务 [{"step": 1, "tool": "rag_search", "args": {...}}]
    current_step: int              # 当前执行步骤索引
    plan_status: str               # 计划状态: planned/replanned/skipped/exhausted
    replan_count: int              # 自动重规划次数(上限 1)
    replan_reason: str             # 最近一次重规划原因,未重规划为空
    run_id: Optional[int]          # 当前运行 ID,计划调整按运行生效
    plan_revisions: List[Dict]     # 本次生效的计划调整 [{"id","instruction",...}]

    # === 多 Agent 协作 ===
    collaborate: bool              # 是否启用多 Agent 协作
    collab_plan: List[Dict]        # 协作计划 [{"agent": "tutor", "task": "..."}]
    collab_results: List[Dict]     # 各专家结论 [{"agent", "label", "task", "output", "status"}]

    # === 工具与检索 ===
    tool_calls: List[Dict]         # 待调用工具 [{"name": "...", "args": {...}}]
    tool_approvals: Optional[List[str]]  # 服务端可信审批:用户已确认的高危工具名
    tool_results: Dict             # 工具返回结果 {"tool_name": result}
    tool_trace: List[Dict]         # 节点内工具循环轨迹 [{"name", "arguments", "result"}]
    rag_context: str               # RAG 检索注入的上下文(带来源标注)
    sources: List[Dict]            # 回答来源清单 [{"type","label"}],由对话层渲染页脚

    # === 写操作确认 ===
    pending_action: Dict           # 待确认写动作 {action, params, label, confirmation_token, idempotency_key, expires_at}

    # === 记忆 ===
    profile_snapshot: Dict         # 学情档案快照(进入时读取)
    profile_updates: Dict          # 学情档案更新(退出时回写)
    profile_write_result: Dict     # 回写结果 {written, skipped_review_plans, reason}

    # === 校验与输出 ===
    risk_flag: bool                # 风控标记
    risk_type: str                 # 风险类型
    risk_target: str               # 风控命中目标(如 作业#12),供风控日志追溯
    reflection_passed: bool        # 反思是否通过
    reflection_notes: str          # 反思意见
    reflection_count: int          # 反思循环计数
    final_output: str              # 最终输出内容
    stream_queue: Any              # 流式输出通道:asyncio.Queue,节点边生成边 put(("token", 文本))