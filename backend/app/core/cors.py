"""CORS 配置:显式来源 + 凭据

只允许配置中列出的来源,生产环境在 Settings 校验阶段就拒绝通配符,
避免 `allow_origins=["*"]` 与 `allow_credentials=True` 组合。
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import Settings, settings


def configure_cors(app: FastAPI, config: Settings | None = None) -> None:
    active = config or settings
    app.add_middleware(
        CORSMiddleware,
        allow_origins=active.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        # 前端需要读取该响应头区分「邮箱未验证」与普通 403
        expose_headers=["X-Error-Code"],
    )
