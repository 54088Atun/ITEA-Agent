"""ITEA-Agent 应用入口

启动流程:
1. 校验 LLM_API_KEY(密钥安全防线:启动即拦截)
2. 初始化数据库表
3. 启动提醒调度器(APScheduler)
4. 挂载 API 路由与静态资源
"""
import logging
import sys

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.core.config import settings, BASE_DIR
from app.core.cors import configure_cors
from app.core.log_sanitizer import SensitiveLogFilter
from app.core.request_context import RequestContextMiddleware, RequestIdLogFilter


def _ensure_utf8_streams() -> None:
    """Windows 控制台默认 GBK,统一改为 UTF-8,避免中文/异常日志编码失败"""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if not callable(reconfigure):
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass


_ensure_utf8_streams()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(request_id)s] %(name)s: %(message)s",
)
for handler in logging.getLogger().handlers:
    if not any(isinstance(item, RequestIdLogFilter) for item in handler.filters):
        handler.addFilter(RequestIdLogFilter())
    if not any(isinstance(item, SensitiveLogFilter) for item in handler.filters):
        handler.addFilter(SensitiveLogFilter())
logger = logging.getLogger(__name__)

# ---------- 密钥安全防线:启动即校验 ----------
if not settings.LLM_API_KEY:
    logger.error("LLM_API_KEY 未配置!请在 backend/.env 中设置后重启。")
    sys.exit(1)
logger.info("LLM 配置: base=%s, model=%s", settings.LLM_API_BASE, settings.LLM_MODEL)

app = FastAPI(
    title="ITEA-Agent",
    description="面向高校师生一体化教学生态智能助教 Agent",
    version="1.0.0",
)

# ---------- CORS(仅允许显式配置的前端来源) ----------
configure_cors(app)
# 请求级 request_id:日志/审计/上传拒绝/通知/轨迹共用同一标识
app.add_middleware(RequestContextMiddleware)


# ---------- 启动事件 ----------
@app.on_event("startup")
async def startup():
    # 1. 建表(开发环境)
    from app.db.session import init_db
    init_db()
    logger.info("数据库表已就绪")

    # 2. 启动提醒调度器
    from app.agent.tools.reminder_scheduler import start_scheduler
    start_scheduler()

    # 3. 收尾上次进程遗留的 running 运行,转入死信队列待恢复
    try:
        from app.services.agent_runs import mark_stale_running_as_failed
        stale = mark_stale_running_as_failed()
        if stale:
            logger.info("已将 %s 条中断运行转入死信队列", stale)
    except Exception as e:
        logger.warning("中断运行收尾失败: %s", e)

    # 4. 预构建 LangGraph 图(首次编译较慢,提前完成)
    try:
        from app.agent.graph import get_graph
        get_graph()
        logger.info("LangGraph 图预构建完成")
    except Exception as e:
        logger.warning("LangGraph 图预构建失败(首次请求时重试): %s", e)


# ---------- 路由挂载 ----------
from app.api import api_router  # noqa: E402

app.include_router(api_router)


# ---------- 静态资源 ----------
static_dir = settings.static_path
upload_dir = settings.upload_path
generated_dir = BASE_DIR / "static" / "generated"
generated_dir.mkdir(parents=True, exist_ok=True)

app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
app.mount("/uploads", StaticFiles(directory=str(upload_dir)), name="uploads")
app.mount("/generated", StaticFiles(directory=str(generated_dir)), name="generated")


# ---------- 健康检查 ----------
@app.get("/health")
def health():
    return {"status": "ok", "model": settings.LLM_MODEL}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.APP_HOST,
        port=settings.APP_PORT,
        reload=True,
    )