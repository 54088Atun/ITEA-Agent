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

# 需要登录才能访问的静态资源前缀(上传文件/生成文件/检索索引)
PROTECTED_STATIC_PREFIXES = (
    "/uploads/", "/generated/", "/static/generated/", "/static/faiss_indexes/",
)


@app.middleware("http")
async def protect_static_files(request, call_next):
    """上传文件与生成文件必须携带登录 Cookie 或 Bearer Token。

    学生成绩、教案、用户图片等不在公网匿名暴露;后端端口只监听 127.0.0.1,
    因此该中间件对所有外部入口生效,无需额外网关配置。
    """
    if not request.url.path.startswith(PROTECTED_STATIC_PREFIXES):
        return await call_next(request)

    from fastapi import HTTPException
    from fastapi.responses import JSONResponse
    from app.api.auth import AUTH_COOKIE
    from app.core.deps import user_from_token
    from app.db.session import SessionLocal
    from app.services.static_acl import is_static_allowed

    token = request.cookies.get(AUTH_COOKIE) or ""
    if not token:
        header = request.headers.get("authorization") or ""
        if header.lower().startswith("bearer "):
            token = header[7:].strip()
    if not token:
        return JSONResponse({"detail": "未登录，无法访问该文件"}, status_code=401)

    db = SessionLocal()
    try:
        user = user_from_token(token, db)
        # 逐文件归属:学生图片/录音仅本人,课程素材按课程可见性,生成文档仅生成者
        if not is_static_allowed(request.url.path, user, db):
            logger.warning(
                "静态文件越权访问已拒绝: user=%s role=%s path=%s",
                user.id, user.role, request.url.path,
            )
            return JSONResponse({"detail": "无权访问该文件"}, status_code=403)
    except HTTPException as exc:
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
    finally:
        db.close()
    return await call_next(request)



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
    # 生产健康检查只暴露存活状态,不泄露模型与内部配置
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.APP_HOST,
        port=settings.APP_PORT,
        reload=True,
    )