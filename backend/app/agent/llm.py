"""LLM 底座封装 —— DeepSeek(兼容 OpenAI 接口格式),支持流式与非流式

密钥安全:
- API Key 仅从环境变量 / .env 读取,不硬编码、不打印日志
- 启动时校验密钥非空,缺失则拒绝初始化
"""
import inspect
import logging
from dataclasses import dataclass, field

from langchain_openai import ChatOpenAI
from app.core.config import settings

logger = logging.getLogger(__name__)

_llm_instance: ChatOpenAI | None = None

# 单次调用上限:超过即抛超时,避免网络抖动时请求无限挂起、占满数据库连接池
LLM_TIMEOUT_SECONDS = 90
LLM_MAX_RETRIES = 1


def accepts_tools(fn) -> bool:
    """判断调用方是否接受 tools 关键字

    用于兼容只带 sink 的测试替身/旧实现。此前用 except TypeError 探测,
    会把模型调用内部的真实类型错误误判为"签名不兼容"并静默降级。
    """
    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return True
    return "tools" in params or any(
        param.kind == param.VAR_KEYWORD for param in params.values()
    )


@dataclass
class ToolPlan:
    """一次带工具的模型决策

    content: 模型在调用工具前的说明文字(可能为空)
    tool_calls: 待执行调用 [{"id", "name", "arguments"}]
    """

    content: str = ""
    tool_calls: list[dict] = field(default_factory=list)


def get_llm(temperature: float | None = None) -> ChatOpenAI:
    """获取 LLM 单例(DeepSeek 兼容 OpenAI 接口,直接使用 ChatOpenAI 客户端)"""
    global _llm_instance
    if _llm_instance is None:
        if not settings.LLM_API_KEY or settings.LLM_API_KEY.startswith("sk-your"):
            raise RuntimeError(
                "LLM_API_KEY 未配置!请在 backend/.env 中填入真实的 DeepSeek API 密钥"
                "(复制 .env.example 为 .env 后修改),切勿将密钥提交到版本库。"
            )
        _llm_instance = ChatOpenAI(
            base_url=settings.LLM_API_BASE,   # https://api.deepseek.com
            api_key=settings.LLM_API_KEY,     # 仅内存传递,不落盘不打印
            model=settings.LLM_MODEL,         # deepseek-flash
            temperature=settings.LLM_TEMPERATURE,
            timeout=LLM_TIMEOUT_SECONDS,
            max_retries=LLM_MAX_RETRIES,
        )
        logger.info("LLM 底座已初始化: model=%s, base=%s", settings.LLM_MODEL, settings.LLM_API_BASE)
    if temperature is not None:
        return _llm_instance.bind(temperature=temperature)
    return _llm_instance


def _to_lc_messages(messages: list[dict]):
    """统一转换消息,支持工具调用的 assistant / tool 往返"""
    from langchain_core.messages import (
        AIMessage, HumanMessage, SystemMessage, ToolMessage,
    )

    lc_msgs = []
    for m in messages:
        role = m.get("role")
        content = m.get("content") or ""
        if role == "system":
            lc_msgs.append(SystemMessage(content=content))
        elif role == "assistant":
            calls = m.get("tool_calls") or []
            if calls:
                lc_msgs.append(AIMessage(
                    content=content,
                    tool_calls=[
                        {
                            "name": call.get("name", ""),
                            "args": call.get("arguments") or {},
                            "id": call.get("id") or f"call_{i}",
                        }
                        for i, call in enumerate(calls)
                    ],
                ))
            else:
                lc_msgs.append(AIMessage(content=content))
        elif role == "tool":
            lc_msgs.append(ToolMessage(
                content=content,
                tool_call_id=m.get("tool_call_id") or "call_0",
            ))
        else:
            lc_msgs.append(HumanMessage(content=content))
    return lc_msgs


def _to_openai_tools(tools: list[dict]) -> list[dict]:
    """把裸 Schema 转成 OpenAI function calling 格式;已是完整格式的原样保留"""
    converted = []
    for tool in tools or []:
        if tool.get("type") == "function":
            converted.append(tool)
            continue
        converted.append({
            "type": "function",
            "function": {
                "name": tool.get("name", ""),
                "description": tool.get("description", ""),
                "parameters": tool.get("parameters") or {
                    "type": "object", "properties": {},
                },
            },
        })
    return converted


def _extract_tool_calls(resp) -> list[dict]:
    """从模型响应提取工具调用,统一成 {id, name, arguments}"""
    calls = getattr(resp, "tool_calls", None) or []
    extracted = []
    for index, call in enumerate(calls):
        if not isinstance(call, dict):
            continue
        name = call.get("name") or ""
        if not name:
            continue
        extracted.append({
            "id": call.get("id") or f"call_{index}",
            "name": name,
            "arguments": call.get("args") or call.get("arguments") or {},
        })
    return extracted


def _content_text(resp) -> str:
    content = getattr(resp, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            part.get("text", "") if isinstance(part, dict) else str(part)
            for part in content
        )
    return str(content or "")


async def _stream_decision(bound_llm, lc_msgs, sink):
    """流式执行模型决策:边生成边推送文本,返回合并后的完整响应

    工具调用参数同样以分片形式下发,LangChain 的 AIMessageChunk 相加即可
    还原出完整的 tool_calls,因此工具决策阶段也能做真流式,无需等整段生成。
    """
    merged = None
    async for chunk in bound_llm.astream(lc_msgs):
        merged = chunk if merged is None else merged + chunk
        text = _content_text(chunk)
        if text:
            await sink.put(("token", text))
    return merged


async def llm_invoke(
    messages: list[dict],
    temperature: float | None = None,
    sink=None,
    tools: list[dict] | None = None,
) -> str | ToolPlan:
    """调用 LLM,返回完整文本

    sink: 传入 asyncio.Queue 时改为流式生成,每产出一段就 put(("token", 文本)),
    同时累积成完整字符串返回。这样前端能在模型生成过程中就看到内容,
    而不是等整个节点跑完(首字延迟从"全流程耗时"降到"模型首个 token")。
    """
    llm = get_llm(temperature)
    lc_msgs = _to_lc_messages(messages)

    if tools:
        # 工具决策同样走流式:模型直接作答时可逐字渲染,
        # 需要调用工具时文本说明先推送,工具参数由分片合并还原
        bound = llm.bind_tools(_to_openai_tools(tools))
        if sink is not None:
            resp = await _stream_decision(bound, lc_msgs, sink)
        else:
            resp = await bound.ainvoke(lc_msgs)
        calls = _extract_tool_calls(resp)
        content = _content_text(resp)
        if calls:
            return ToolPlan(content=content, tool_calls=calls)
        return content

    if sink is not None:
        parts = []
        async for chunk in llm.astream(lc_msgs):
            text = chunk.content
            if text:
                parts.append(text)
                await sink.put(("token", text))
        return "".join(parts)

    resp = await llm.ainvoke(lc_msgs)
    return resp.content


async def llm_stream(messages: list[dict], temperature: float | None = None):
    """流式调用,逐 token 生成"""
    llm = get_llm(temperature)
    lc_msgs = _to_lc_messages(messages)
    async for chunk in llm.astream(lc_msgs):
        if chunk.content:
            yield chunk.content