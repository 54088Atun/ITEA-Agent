"""LLM 底座封装 —— DeepSeek(兼容 OpenAI 接口),支持流式与工具调用

密钥安全:
- API Key 仅从环境变量 / .env 读取,不硬编码、不打印日志
- 启动时校验密钥非空,缺失则拒绝初始化

思考模式(thinking):
- 模型本轮产生 tool_calls 时,后续请求必须把该 assistant 轮次的
  `reasoning_content` 原样回传,否则服务端返回 400。
- langchain-openai 0.2.x 在消息转换时既不保留响应里的 reasoning_content,
  也不会把它写回请求,因此这里直接用 openai SDK 收发,消息保持 dict 形态。
"""
import inspect
import json
import logging
from dataclasses import dataclass, field

from openai import AsyncOpenAI

from app.core.config import settings

logger = logging.getLogger(__name__)

_client: AsyncOpenAI | None = None

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
    reasoning: 思考模式下本轮产生的 reasoning_content,回灌下轮时必须带回
    """

    content: str = ""
    tool_calls: list[dict] = field(default_factory=list)
    reasoning: str = ""


@dataclass
class _Resp:
    """一次完整(非流式)调用结果"""

    content: str = ""
    tool_calls: list[dict] = field(default_factory=list)
    reasoning: str = ""


@dataclass
class _Chunk:
    """流式增量:文本 / 思考内容 / 工具调用分片(以 index 归并)"""

    content: str = ""
    reasoning: str = ""
    tool_calls: list[dict] = field(default_factory=list)


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        if not settings.LLM_API_KEY or settings.LLM_API_KEY.startswith("sk-your"):
            raise RuntimeError(
                "LLM_API_KEY 未配置!请在 backend/.env 中填入真实的 DeepSeek API 密钥"
                "(复制 .env.example 为 .env 后修改),切勿将密钥提交到版本库。"
            )
        _client = AsyncOpenAI(
            base_url=settings.LLM_API_BASE,   # https://api.deepseek.com
            api_key=settings.LLM_API_KEY,     # 仅内存传递,不落盘不打印
            timeout=LLM_TIMEOUT_SECONDS,
            max_retries=LLM_MAX_RETRIES,
        )
        logger.info(
            "LLM 底座已初始化: model=%s, base=%s",
            settings.LLM_MODEL, settings.LLM_API_BASE,
        )
    return _client


def _normalize_messages(messages: list[dict]) -> list[dict]:
    """把内部消息 dict 规范成 OpenAI 请求格式

    - assistant + tool_calls 必须带 reasoning_content:思考模式下缺省即 400,
      真实轮次回传模型原文,预置的强制检索轮次回传空串(服务端接受)。
    - 工具调用参数统一序列化为字符串,并补 type=function(服务端强校验)。
    """
    normalized = []
    for message in messages:
        role = message.get("role") or "user"
        item = {"role": role, "content": message.get("content") or ""}
        if role == "assistant":
            calls = message.get("tool_calls") or []
            if calls:
                item["tool_calls"] = [
                    _to_openai_call(call, index)
                    for index, call in enumerate(calls)
                ]
                item["reasoning_content"] = message.get("reasoning_content") or ""
        elif role == "tool":
            item["tool_call_id"] = message.get("tool_call_id") or "call_0"
        normalized.append(item)
    return normalized


def _to_openai_call(call: dict, index: int) -> dict:
    """内部 {id,name,arguments} → OpenAI function call 格式"""
    arguments = call.get("arguments")
    if not isinstance(arguments, str):
        arguments = json.dumps(arguments or {}, ensure_ascii=False)
    return {
        "id": call.get("id") or f"call_{index}",
        "type": "function",
        "function": {
            "name": str(call.get("name") or ""),
            "arguments": arguments or "{}",
        },
    }


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


def _parse_arguments(raw: str) -> dict:
    try:
        parsed = json.loads(raw or "{}")
    except json.JSONDecodeError:
        logger.warning("工具调用参数不是合法 JSON: %s", raw[:200])
        return {}
    return parsed if isinstance(parsed, dict) else {}


class _Bound:
    """绑定工具后的调用入口,保持与旧 ChatOpenAI.bind_tools(...) 一致的用法"""

    def __init__(self, temperature: float, tools: list[dict] | None = None):
        self._temperature = temperature
        self._tools = tools

    def _payload(self, messages: list[dict]) -> dict:
        payload = {
            "model": settings.LLM_MODEL,
            "messages": _normalize_messages(messages),
            "temperature": self._temperature,
        }
        if self._tools:
            payload["tools"] = self._tools
            payload["tool_choice"] = "auto"
        return payload

    async def ainvoke(self, messages: list[dict]) -> _Resp:
        response = await _get_client().chat.completions.create(
            **self._payload(messages), stream=False,
        )
        message = response.choices[0].message
        calls = []
        for call in message.tool_calls or []:
            calls.append({
                "id": call.id,
                "name": call.function.name,
                "arguments": _parse_arguments(call.function.arguments),
            })
        return _Resp(
            content=message.content or "",
            tool_calls=calls,
            reasoning=getattr(message, "reasoning_content", None) or "",
        )

    async def astream(self, messages: list[dict]):
        stream = await _get_client().chat.completions.create(
            **self._payload(messages), stream=True,
        )
        async for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if not delta:
                continue
            reasoning = getattr(delta, "reasoning_content", None)
            if reasoning:
                yield _Chunk(reasoning=reasoning)
            if delta.content:
                yield _Chunk(content=delta.content)
            for call in delta.tool_calls or []:
                function = call.function
                yield _Chunk(tool_calls=[{
                    "index": call.index,
                    "id": call.id,
                    "name": function.name if function else None,
                    "arguments": function.arguments if function else None,
                }])


class _LLMClient:
    """轻量客户端:按调用温度固化参数,对外暴露 bind_tools / astream"""

    def __init__(self, temperature: float):
        self._temperature = temperature

    def bind_tools(self, tools: list[dict]) -> _Bound:
        return _Bound(self._temperature, tools)

    def astream(self, messages: list[dict]):
        return _Bound(self._temperature).astream(messages)


def get_llm(temperature: float | None = None) -> _LLMClient:
    """获取 LLM 客户端(DeepSeek 兼容 OpenAI 接口)"""
    return _LLMClient(
        settings.LLM_TEMPERATURE if temperature is None else temperature
    )


async def _stream_decision(bound_llm, messages: list[dict], sink) -> _Resp:
    """流式执行模型决策:边生成边推送文本,返回合并后的完整响应

    工具调用参数同样以分片形式下发,按 index 归并后用 JSON 还原,
    因此工具决策阶段也能做真流式,无需等整段生成。
    """
    parts: list[str] = []
    reasoning: list[str] = []
    calls: dict[int, dict] = {}

    async for chunk in bound_llm.astream(messages):
        text = getattr(chunk, "content", "") or ""
        if text:
            parts.append(text)
            await sink.put(("token", text))
        thought = getattr(chunk, "reasoning", "") or ""
        if thought:
            reasoning.append(thought)
        for item in getattr(chunk, "tool_calls", None) or []:
            slot = calls.setdefault(
                item.get("index") or 0,
                {"id": "", "name": "", "arguments": ""},
            )
            if item.get("id"):
                slot["id"] = item["id"]
            if item.get("name"):
                slot["name"] = item["name"]
            if item.get("arguments"):
                slot["arguments"] += item["arguments"]

    final_calls = []
    for index in sorted(calls):
        slot = calls[index]
        if not slot["name"]:
            continue
        final_calls.append({
            "id": slot["id"] or f"call_{index}",
            "name": slot["name"],
            "arguments": _parse_arguments(slot["arguments"]),
        })
    return _Resp(
        content="".join(parts),
        tool_calls=final_calls,
        reasoning="".join(reasoning),
    )


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
    if tools:
        # 工具决策同样走流式:模型直接作答时可逐字渲染,
        # 需要调用工具时文本说明先推送,工具参数由分片合并还原
        bound = llm.bind_tools(_to_openai_tools(tools))
        if sink is not None:
            resp = await _stream_decision(bound, messages, sink)
        else:
            resp = await bound.ainvoke(messages)
        calls = _extract_tool_calls(resp)
        content = _content_text(resp)
        if calls:
            return ToolPlan(
                content=content,
                tool_calls=calls,
                reasoning=getattr(resp, "reasoning", "") or "",
            )
        return content

    if sink is not None:
        parts = []
        async for chunk in llm.astream(messages):
            text = getattr(chunk, "content", "") or ""
            if text:
                parts.append(text)
                await sink.put(("token", text))
        return "".join(parts)

    resp = await llm.bind_tools([]).ainvoke(messages)
    return resp.content


async def llm_stream(messages: list[dict], temperature: float | None = None):
    """流式调用,逐 token 生成"""
    llm = get_llm(temperature)
    async for chunk in llm.astream(messages):
        text = getattr(chunk, "content", "") or ""
        if text:
            yield text
