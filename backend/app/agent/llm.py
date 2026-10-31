"""LLM 底座封装 —— DeepSeek(兼容 OpenAI 接口格式),支持流式与非流式

密钥安全:
- API Key 仅从环境变量 / .env 读取,不硬编码、不打印日志
- 启动时校验密钥非空,缺失则拒绝初始化
"""
import logging
from langchain_openai import ChatOpenAI
from app.core.config import settings

logger = logging.getLogger(__name__)

_llm_instance: ChatOpenAI | None = None

# 单次调用上限:超过即抛超时,避免网络抖动时请求无限挂起、占满数据库连接池
LLM_TIMEOUT_SECONDS = 90
LLM_MAX_RETRIES = 1


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


async def llm_invoke(messages: list[dict], temperature: float | None = None, sink=None) -> str:
    """调用 LLM,返回完整文本

    sink: 传入 asyncio.Queue 时改为流式生成,每产出一段就 put(("token", 文本)),
    同时累积成完整字符串返回。这样前端能在模型生成过程中就看到内容,
    而不是等整个节点跑完(首字延迟从"全流程耗时"降到"模型首个 token")。
    """
    llm = get_llm(temperature)
    from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
    lc_msgs = []
    for m in messages:
        if m["role"] == "system":
            lc_msgs.append(SystemMessage(content=m["content"]))
        elif m["role"] == "assistant":
            lc_msgs.append(AIMessage(content=m["content"]))
        else:
            lc_msgs.append(HumanMessage(content=m["content"]))

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
    from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
    lc_msgs = []
    for m in messages:
        if m["role"] == "system":
            lc_msgs.append(SystemMessage(content=m["content"]))
        elif m["role"] == "assistant":
            lc_msgs.append(AIMessage(content=m["content"]))
        else:
            lc_msgs.append(HumanMessage(content=m["content"]))
    async for chunk in llm.astream(lc_msgs):
        if chunk.content:
            yield chunk.content