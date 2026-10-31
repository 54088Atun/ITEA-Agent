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

    # === 任务规划 ===
    intent: str                    # 识别意图: prepare/learn/review/interview/violation/chat
    branch: str                    # 路由分支: teacher/tutor/review/interview/admin/block
    task_plan: List[Dict]          # 拆解的子任务 [{"step": 1, "tool": "rag_search", "args": {...}}]
    current_step: int              # 当前执行步骤索引

    # === 工具与检索 ===
    tool_calls: List[Dict]         # 待调用工具 [{"name": "...", "args": {...}}]
    tool_results: Dict             # 工具返回结果 {"tool_name": result}
    rag_context: str               # RAG 检索注入的上下文(带来源标注)

    # === 记忆 ===
    profile_snapshot: Dict         # 学情档案快照(进入时读取)
    profile_updates: Dict          # 学情档案更新(退出时回写)

    # === 校验与输出 ===
    risk_flag: bool                # 风控标记
    risk_type: str                 # 风险类型
    reflection_passed: bool        # 反思是否通过
    reflection_notes: str          # 反思意见
    reflection_count: int          # 反思循环计数
    final_output: str              # 最终输出内容
    stream_queue: Any              # 流式输出通道:asyncio.Queue,节点边生成边 put(("token", 文本))