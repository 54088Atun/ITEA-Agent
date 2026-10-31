"""全局配置,从环境变量 / .env 文件加载"""
import os
from pathlib import Path
from pydantic_settings import BaseSettings

BASE_DIR = Path(__file__).resolve().parent.parent.parent  # backend/


class Settings(BaseSettings):
    # 数据库
    DATABASE_URL: str = "mysql+pymysql://root:123456@localhost:3306/itea_agent?charset=utf8mb4"

    # JWT
    SECRET_KEY: str = "change-this-to-a-random-secret-key"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440

    # LLM(DeepSeek,兼容 OpenAI 接口格式)
    LLM_API_BASE: str = "https://api.deepseek.com"
    LLM_API_KEY: str = ""  # 必须从 .env 或环境变量注入,禁止硬编码
    LLM_MODEL: str = "deepseek-flash"  # 统一使用 flash,覆盖全部场景
    LLM_TEMPERATURE: float = 0.3

    # 视觉模型(识图,可选):留空则关闭图片解析,前端提示未启用
    VISION_API_BASE: str = ""
    VISION_API_KEY: str = ""
    VISION_MODEL: str = ""

    # 向量模型
    EMBEDDING_MODEL: str = "all-MiniLM-L6-v2"

    # 应用
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8000
    STATIC_DIR: str = "static"
    UPLOAD_DIR: str = "uploads"

    # 反思循环最大次数
    MAX_REFLECTION_ROUNDS: int = 2

    # 代码沙箱限制
    CODE_EXEC_TIMEOUT: int = 10
    CODE_EXEC_MEMORY_MB: int = 256

    class Config:
        env_file = str(BASE_DIR / ".env")
        env_file_encoding = "utf-8"

    @property
    def static_path(self) -> Path:
        p = BASE_DIR / self.STATIC_DIR
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def upload_path(self) -> Path:
        p = BASE_DIR / self.UPLOAD_DIR
        p.mkdir(parents=True, exist_ok=True)
        return p


settings = Settings()