"""Agent 全局工具池(Function Calling)"""
from app.agent.tools.rag_search import rag_search, RAGManager
from app.agent.tools.code_executor import code_executor
from app.agent.tools.doc_generator import doc_generator
from app.agent.tools.stats_analyzer import stats_analyzer
from app.agent.tools.reminder_scheduler import reminder_scheduler

# 工具注册表:供 tool_executor 与 LLM bind_tools 使用
TOOL_REGISTRY = {
    "rag_search": rag_search,
    "code_executor": code_executor,
    "doc_generator": doc_generator,
    "stats_analyzer": stats_analyzer,
    "reminder_scheduler": reminder_scheduler,
}

__all__ = [
    "rag_search", "RAGManager", "code_executor", "doc_generator",
    "stats_analyzer", "reminder_scheduler", "TOOL_REGISTRY",
]