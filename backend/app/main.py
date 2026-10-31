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
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.core.config import settings, BASE_DIR

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
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

# ---------- CORS(允许前端跨域) ----------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 生产环境应限定域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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

    # 3. 预构建 LangGraph 图(首次编译较慢,提前完成)
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